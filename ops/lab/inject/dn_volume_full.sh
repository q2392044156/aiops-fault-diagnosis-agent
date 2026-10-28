#!/usr/bin/env bash
set -euo pipefail
dd if=/dev/zero of=/tmp/hadoop-root/dfs/data/lab.fill bs=1M count=256 status=none
sync
