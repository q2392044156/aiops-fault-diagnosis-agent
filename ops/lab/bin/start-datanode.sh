#!/usr/bin/env bash
set -euo pipefail
export HADOOP_HOME=/opt/hadoop
sleep 5
exec hdfs datanode
