# Redis Sentinel Watcher #

This package contains a very simple dockerfile plus python script intended to be
run as a sidecar along with a container running redis-sentinel that can detect
when redis-sentinels go away. This is primarily aimed at being used with the
redis-ha chart.

### Building and Running ###

Run script:

```
./build.sh
```

Builds and pushes an image named `redis-sentinel-watcher:<version>` where
`<version>` is the contents of the file `version.txt`. Note 

Then consume as a sidecar container along with any redis-sentinel container.
For example, in a redis sentinel deployment:

```
apiVersion: extensions/v1beta1
kind: Deployment
metadata:
  name: brazen-ladybug-redis-ha-sentinel
spec:
  replicas: 3
  template:
    metadata:
      labels:
        name: redis-sentinel
        redis-sentinel: "true"
        role: sentinel
        app: redis-ha
        heritage: "Tiller"
        release: "brazen-ladybug"
        chart: redis-ha-1.0.0
    spec:
      containers:
      - name: sentinel
        image: gcr.io/your_project/smileisak-redis-fork:4.0.2
        resources:
          limits:
            memory: 200Mi
          requests:
            cpu: 100m
            memory: 200Mi
        env:
          - name: SENTINEL
            value: "true"
        ports:
          - containerPort: 26379
      - name: redis-sentinel-watcher
        image: gcr.io/your_project/redis-sentinel-watcher:0.1 
        env:
          - name: WATCH_NAME
            value: redis-sentinel
          - name: WATCH_APP
            value: redis-ha
          - name: WATCH_RELEASE
            value: brazen-ladybug
```

Note that `smileisak-redis-fork:4.0.2` refers to a fork of a docker image used in the original redis-ha chart.
It should be built off [this commit](https://github.com/ludwick/docker-images/commit/997377ee301fe71e8bc9f0a766361de5e38ea610)

