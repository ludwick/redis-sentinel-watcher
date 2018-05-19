#!/usr/bin/python

import gevent
import gevent.event
from functools import reduce
import json
import operator
import os
import os.path
import requests
import signal
import subprocess
import sys

from gevent import monkey
monkey.patch_all()

# the environment
K8SBASE = os.getenv('K8SBASE') or 'http://127.0.0.1:8000'
NAMESPACE = os.getenv('NAMESPACE') or 'default'
WATCH_APP = os.getenv('WATCH_APP') or 'redis-ha'
WATCH_RELEASE = os.getenv('WATCH_RELEASE') or ''
WATCH_ROLES = os.getenv('WATCH_ROLES').split(',') or ['sentinel', 'slave']

# simplistic log level because default python logger is annoying to setup
LOG_LEVEL = os.getenv('LOG_LEVEL') or 'INFO'
LEVELS = {
    'DEBUG': 1,
    'INFO': 2,
    'WARN': 3,
    'ERROR': 4,
}
LOG_LEVEL_NUM = LEVELS.get(LOG_LEVEL, LEVELS['INFO'])

# actually the k8s service name
REDIS_SENTINEL_HOST = os.getenv('REDIS_SENTINEL_HOST') or 'redis-sentinel'
REDIS_SENTINEL_PORT = os.getenv('REDIS_SENTINEL_PORT') or 26379
REDIS_MASTER = os.getenv('REDIS_MASTER') or 'mymaster'

WATCH_PODS_PATH = K8SBASE + '/api/v1/watch/namespaces/{}/pods'.format(NAMESPACE)
GET_SERVICE_PATH = K8SBASE + '/api/v1/namespaces/{}/endpoints/{}'.format(
        NAMESPACE, REDIS_SENTINEL_HOST)

LABEL_MATCHES = {
    'app': WATCH_APP,
    'release': WATCH_RELEASE,
}
# do not trigger resets on master deletion since we might be in the middle of failover
ROLE_SELECTOR = 'role in (sentinel,slave)'
ALL_SELECTORS = ['{}={}'.format(k, v) for k, v in LABEL_MATCHES.items()] + [ROLE_SELECTOR]
LABEL_SELECTOR = ','.join(ALL_SELECTORS)

RESET_CMD = '/usr/bin/redis-cli'


delete_event = gevent.event.Event()


def do_log(msg, fh, level, extra):
    if LOG_LEVEL_NUM > LEVELS[level]:
        return
    payload = extra.copy()
    payload.update({'severity': level, 'message': msg})
    fh.write(json.dumps(payload) + "\n")
    fh.flush()


def error(msg, extra={}):
    do_log(msg, sys.stderr, 'ERROR', extra)


def info(msg, extra={}):
    do_log(msg, sys.stderr, 'INFO', extra)


def debug(msg, extra={}):
    do_log(msg, sys.stderr, 'DEBUG', extra)


def dig(d, keys):
    try:
        return reduce(operator.getitem, keys, d)
    except:
        return None


class Terminator:
    stopping = False

    def __init__(self, notify):
        signal.signal(signal.SIGINT, self.start_exiting)
        signal.signal(signal.SIGTERM, self.start_exiting)
        self.notify = notify

    def start_exiting(self, signum, frame):
        info('Received signal {}, shutting down.'.format(signum))
        self.stopping = True
        self.notify.shutdown()


class PodDeletionWatcher(gevent.Greenlet):
    def __init__(self):
        super(PodDeletionWatcher, self).__init__()
        self.stopping = False
        self.current_request = None
        self.event_data = None

    def _run(self):
        query = {'labelSelector': LABEL_SELECTOR, 'watch': 'true'}
        debug("watching pod stream", {'query': query})
        while True:
            try:
                self.current_request = requests.get(WATCH_PODS_PATH, params=query, stream=True)
                lines = self.current_request.iter_lines()
                for line in lines:
                    if self.should_stop():
                        self.current_request.close()
                        return
                    self._process_line(line)
            except requests.exceptions.RequestException as e:
                if self.should_stop():
                    return
                error("watch failed", {'exception': str(e)})
                gevent.sleep(5)

    def _process_line(self, line):
        data = json.loads(line)
        return self._process_json(data)

    def _process_json(self, data):
        kind = dig(data, ['object', 'kind'])
        if kind != 'Pod':
            return
        if data['type'] != 'DELETED':
            return
        self.event_data = data['object']
        delete_event.set()

    def shutdown(self):
        if self.current_request is not None:
            try:
                self.current_request.close()
            except:
                pass
        self.stopping = True

    def should_stop(self):
        return self.stopping


def pod_matches(pod):
    labels = dig(pod, ['metadata', 'labels'])
    if not labels:
        error('pod data invalid', {'object': pod})
        return False

    # re-check labels just in case something weird happen
    for name, expected in LABEL_MATCHES.items():
        if name in labels and expected and labels[name] != expected:
            return False
    return 'role' in labels and labels['role'] in WATCH_ROLES


# This entire function does not validate structure so caller should catch
# exceptions in case something is horribly awry.
def list_sentinels():
    req = requests.get(GET_SERVICE_PATH)
    data = json.loads(req.text)
    return [(item['ip'], dig(ss, ['ports', 0, 'port']))
            for ss in data['subsets']
            for item in ss['addresses']]


def reset_sentinel(ip, port):
    args = [RESET_CMD, '-h', ip, '-p', str(port), '--raw', 'sentinel', 'reset', REDIS_MASTER]
    info("resetting sentinel", {'cmd': args})
    try:
        output = subprocess.check_output(args)
        info('done resetting sentinel.', {'result': output.rstrip()})
    except subprocess.CalledProcessError as e:
        error('reset command failed: {}', {'exception': str(e)})


def reset_sentinels():
    try:
        # enumerate redis-sentinel containers
        info("resetting sentinels!")
        pairs = list_sentinels()
        info("sentinels listed", {'sentinel_count': len(pairs), 'sentinels': pairs})
        first = True
        for ip, port in pairs:
            if not first:
                # per documentation, sleep 30 seconds
                gevent.sleep(30)
                first = False
            reset_sentinel(ip, port)
        info("done resetting all sentinels.")
    except Exception as e:
        error("unable to reset sentinels", {'exception': str(e)})


# wait a bit before trying to startup to let k8s api pod be available. it
# does mean we might miss pod deletion in this period, but likely if that
# is an issue, sentinels are constantly restarting anyway.
gevent.sleep(10.0)

info("starting redis-sentinel-watcher")

pod_watcher = PodDeletionWatcher()
terminator = Terminator(pod_watcher)
pod_watcher.start()
gevent.sleep(0.25)

if __name__ == "__main__":
    while True:
        if terminator.stopping:
            gevent.joinall([pod_watcher])
            break
        if delete_event.wait(30):
            delete_event.clear()
            pod = pod_watcher.event_data
            info("pod delete event", {'deleted_pod_name': dig(pod, ['metadata', 'name'])})
            if pod_matches(pod):
                reset_sentinels()
            else:
                msg = 'ignoring non-matching delete event'
                debug(msg, {'metadata': pod['metadata']})
    info('Exiting...')
