"""验证离线/在线一级目录及二级流程入口可导入。"""

import importlib


def test_offline_online_architecture_is_importable():
    modules = [
        "offline", "offline.ingestion", "offline.detection", "evaluation",
        "online", "online.diagnosis", "online.knowledge",
    ]
    for name in modules:
        assert importlib.import_module(name) is not None
