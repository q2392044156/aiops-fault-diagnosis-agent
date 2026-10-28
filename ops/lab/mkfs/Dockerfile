FROM alpine:3.20
RUN apk add --no-cache e2fsprogs
ENTRYPOINT ["sh", "-c", "mkdir -p /data && dd if=/dev/zero of=/data/data.img bs=1M count=64 status=none && mkfs.ext4 -q -F /data/data.img && echo formatted"]
