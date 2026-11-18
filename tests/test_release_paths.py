"""发布清单的源码路径必须指向现存文件，且不得再手写路径。"""

from pathlib import Path

import pytest

from aiops_diag.common import source_files
from aiops_diag.platform.runtime import _strict_source
from online.diagnosis.framework.release import _code_hashes as framework_code_hashes
from online.diagnosis.framework.release_checkpointed import _code_paths as v12_code_paths
from online.diagnosis.release_candidate import _code_hashes as candidate_code_hashes

# `ROOT` 是本仓库根目录，用于把清单里的相对路径还原成真实文件。
ROOT = Path(__file__).resolve().parents[1]


# 校验三份清单的源码条目都是合法 sha256：路径解析不到文件会在构造时就抛错。
def test_code_hashes_are_sha256_of_real_modules():
    for hashes in (framework_code_hashes(), candidate_code_hashes()):
        assert hashes
        assert all(len(value) == 64 for value in hashes.values())
        assert all(set(value) <= set("0123456789abcdef") for value in hashes.values())


# 校验 v1.2 清单的每条 glob 都落到现存文件，防止再次出现"清单指向不存在路径"。
def test_v12_code_paths_are_existing_files():
    paths = v12_code_paths(ROOT)
    assert paths
    assert all(path.is_file() for path in paths)


# 校验模式匹配不到文件时立即报错，而不是悄悄生成空清单。
def test_source_files_rejects_pattern_that_matches_nothing():
    with pytest.raises(ValueError, match="没有匹配到文件"):
        source_files(ROOT, "src/online/diagnosis/not_a_package/*.py")


# 校验运行期默认不做源码复核，只有显式打开 verify.strict_source 才开启。
def test_runtime_source_hashing_is_opt_in():
    assert _strict_source({}) is False
    assert _strict_source({"verify": {"strict_source": True}}) is True
