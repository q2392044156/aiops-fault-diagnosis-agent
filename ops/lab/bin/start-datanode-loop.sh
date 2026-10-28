#!/usr/bin/env bash
set -euo pipefail
export HADOOP_HOME=/opt/hadoop
export HADOOP_LOG_DIR=/tmp/logs
mkdir -p /tmp/logs /tmp/hadoop-root/dfs/data
if mountpoint -q /tmp/hadoop-root/dfs/data; then
  umount /tmp/hadoop-root/dfs/data
fi
for dev in $(losetup -j /data/data.img 2>/dev/null | cut -d: -f1); do
  losetup -d "$dev" 2>/dev/null || true
done
DEV=$(losetup -f)
losetup "$DEV" /data/data.img
mount "$DEV" /tmp/hadoop-root/dfs/data
sleep 5
exec hdfs datanode
