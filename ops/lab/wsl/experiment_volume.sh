#!/usr/bin/env bash
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export HADOOP_HOME=/opt/lab/hadoop
export PATH="$HADOOP_HOME/bin:$PATH"
OUT="${1:-/opt/lab/evidence}"
mkdir -p "$OUT"
START=$(date -u +%FT%TZ)
hdfs dfs -mkdir -p /lab
LAST=""
for i in $(seq 1 80); do
  dd if=/dev/zero of=/tmp/w bs=1M count=1 status=none
  if ! hdfs dfs -Ddfs.blocksize=1048576 -put -f /tmp/w "/lab/w$i" >/dev/null 2>&1; then
    LAST="failed at block $i"
    break
  fi
done
END=$(date -u +%FT%TZ)
{
  echo "fault_start=$START"
  echo "fault_end=$END"
  echo "result=${LAST:-all blocks succeeded}"
  echo "--- df ---"
  df -h /mnt/labvol
  echo "--- dn enospc ---"
  grep -m2 -A2 "DiskOutOfSpace" /opt/lab/dn.log || true
} > "$OUT/evidence.txt"
cat "$OUT/evidence.txt"
