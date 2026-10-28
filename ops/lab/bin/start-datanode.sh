#!/usr/bin/env bash
set -euo pipefail
export HADOOP_HOME=/opt/hadoop
export HADOOP_LOG_DIR=/tmp/logs
mkdir -p /tmp/logs /tmp/hadoop-root/dfs/data
sleep 5
exec hdfs datanode
