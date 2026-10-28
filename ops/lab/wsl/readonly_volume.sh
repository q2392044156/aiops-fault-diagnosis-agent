#!/usr/bin/env bash
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export HADOOP_HOME=/opt/lab/hadoop
export PATH="$HADOOP_HOME/bin:$PATH"
OUT="${1:-/opt/lab/evidence}"

pgrep -f org.apache.hadoop.hdfs.server.datanode.DataNode | xargs -r kill -9
sleep 3
umount /mnt/labvol 2>/dev/null || true
DEV=$(losetup -j /opt/lab/vol.img | cut -d: -f1)
mount -o ro "$DEV" /mnt/labvol

nohup hdfs datanode > /opt/lab/dn_ro.log 2>&1 &
sleep 15

mkdir -p "$OUT"
{
  echo "--- mount ---"
  mount | grep labvol
  echo "--- dn failure ---"
  grep -m1 -A2 "DiskErrorException: Too many failed volumes" /opt/lab/dn_ro.log || true
} > "$OUT/readonly_evidence.txt"

umount /mnt/labvol 2>/dev/null || true
sleep 2
mount -o rw "$DEV" /mnt/labvol
nohup hdfs datanode > /opt/lab/dn.log 2>&1 &
sleep 12
hdfs dfsadmin -report 2>&1 | grep -E 'Live datanodes' | head -1
