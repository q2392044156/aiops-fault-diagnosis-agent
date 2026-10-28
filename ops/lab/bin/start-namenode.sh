#!/usr/bin/env bash
set -euo pipefail
export HADOOP_HOME=/opt/hadoop
if [ ! -f /tmp/hadoop-root/dfs/name/current/VERSION ]; then
  hdfs namenode -format -force -nonInteractive
fi
exec hdfs namenode
