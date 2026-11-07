"""模块说明：验证离线/在线一级目录及二级流程入口。"""

import importlib


# 方法说明：验证两个一级目录和七个二级入口可导入。
def test_offline_online_architecture_is_importable():
    modules = [
        "offline", "offline.capture", "offline.ingestion",
        "offline.detection", "offline.evaluation",
        "online", "online.diagnosis", "online.knowledge", "online.reporting",
    ]
    for name in modules:
        assert importlib.import_module(name) is not None
