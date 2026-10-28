#!/usr/bin/env bash
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export HADOOP_HOME=/opt/lab/hadoop
export PATH="$HADOOP_HOME/bin:$PATH"
jps 2>/dev/null | awk '/DataNode/ {print $1}' | xargs -r kill -9 || true
sleep 3
umount /mnt/labvol 2>/dev/null || true
for dev in $(losetup -j /opt/lab/vol.img 2>/dev/null | cut -d: -f1); do
  losetup -d "$dev" 2>/dev/null || true
done
rm -f /opt/lab/vol.img
dd if=/dev/zero of=/opt/lab/vol.img bs=1M count=64 status=none
DEV=$(losetup -f)
losetup "$DEV" /opt/lab/vol.img
mkfs.ext4 -m 0 -q "$DEV"
mount "$DEV" /mnt/labvol
nohup hdfs datanode > /opt/lab/dn.log 2>&1 &
sleep 12
hdfs dfsadmin -report 2>&1 | grep -E 'Live datanodes|DFS Remaining' | head -3
