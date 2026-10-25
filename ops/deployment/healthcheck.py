"""模块说明：实现 healthcheck 相关的辅助流程。"""

import sys
import urllib.request


# 变量说明：`url` 保存本模块或数据模型使用的稳定值。
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        if response.status != 200:
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
