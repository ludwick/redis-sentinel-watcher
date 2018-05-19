FROM alpine:edge

# Based partly off of kubernetes-haproxy

# ENV variables. May be overridden in container spec
ENV K8SBASE="http://127.0.0.1:8000"
ENV LOG_LEVEL="INFO"
ENV WATCH_APP="redis-ha"
# Empty string means by default helm chart release is ignored
ENV WATCH_RELEASE=""
ENV WATCH_ROLES="sentinel,slave"
ENV REDIS_SENTINEL_HOST="redis-sentinel"
ENV REDIS_SENTINEL_PORT=26379
ENV REDIS_MASTER="mymaster"

RUN apk --no-cache add --update python py-requests py-gevent ca-certificates redis=4.0.2-r1

WORKDIR /
COPY watch.py /

CMD ["./watch.py"]
