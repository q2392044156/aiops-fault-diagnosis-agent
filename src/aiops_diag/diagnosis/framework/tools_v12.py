"""兼容模块：实际实现为 online.diagnosis.framework.tools_v12。"""

import importlib
import sys

# 变量说明：将兼容模块替换为实际实现模块。
sys.modules[__name__] = importlib.import_module("online.diagnosis.framework.tools_v12")
