"""为依赖本地发布制品的测试提供统一的跳过策略。"""

import sys
from pathlib import Path

import pytest

# ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[1]
# SRC 是 src 布局，加入 sys.path 以支持 offline/online 包。
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# LEGACY_RELEASE 是 v1.0 发布制品的注册表，缺失说明本地尚未构建发布制品。
LEGACY_RELEASE = ROOT / "artifacts" / "releases" / "v1.0_service" / "registry.json"


# requires_artifacts 在缺少发布制品时跳过用例，避免新克隆仓库与 CI 误报失败。
@pytest.fixture
def requires_artifacts():
    if not LEGACY_RELEASE.is_file():
        pytest.skip("需要本地发布制品 artifacts/releases/v1.0_service（见 README 的发布步骤）")
