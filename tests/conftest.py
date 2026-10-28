"""模块说明：为依赖本地发布制品的测试提供统一的跳过策略。"""

from pathlib import Path

import pytest


# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[1]
# 变量说明：LEGACY_RELEASE 是 v1.0 发布制品的注册表，缺失说明本地尚未构建发布制品。
LEGACY_RELEASE = ROOT / "artifacts" / "releases" / "v1.0_service" / "registry.json"


# 方法说明：requires_artifacts 在缺少发布制品时跳过用例，避免新克隆仓库与 CI 误报失败。
@pytest.fixture
def requires_artifacts():
    if not LEGACY_RELEASE.is_file():
        pytest.skip("需要本地发布制品 artifacts/releases/v1.0_service（见 README 的发布步骤）")
