"""验证功能目录、模块 README，以及"模块 docstring 必填 + 禁止机械注释标签"两条源码规则。"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

# `ROOT` 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[2]
# `SOURCE_ROOT` 指向 Python 业务包目录。
SOURCE_ROOT = ROOT / "src" / "aiops_diag"
# `MODULE_DIRS` 列出必须保持内聚的功能模块。
MODULE_DIRS = (
    SOURCE_ROOT,
    SOURCE_ROOT / "platform",
    SOURCE_ROOT / "release",
    ROOT / "ops" / "scripts",
    ROOT / "ops" / "deployment",
    ROOT / "tests",
    ROOT / "src" / "offline",
    ROOT / "src" / "offline" / "ingestion",
    ROOT / "src" / "offline" / "case",
    ROOT / "src" / "evaluation",
    ROOT / "src" / "evaluation" / "agent",
    ROOT / "src" / "evaluation" / "retrieval",
    ROOT / "src" / "online",
    ROOT / "src" / "online" / "diagnosis",
    ROOT / "src" / "online" / "diagnosis" / "framework",
    ROOT / "src" / "online" / "knowledge",
    ROOT / "src" / "online" / "knowledge" / "generation",
)
# `LEGACY_DIRS` 列出重构后不应重新出现的旧目录。
LEGACY_DIRS = (
    ROOT / "src" / "offline" / "evaluation",
    ROOT / "configs",
    ROOT / "deployment",
    ROOT / "deliverables",
    ROOT / "docs",
    ROOT / "evaluation",
    ROOT / "knowledge",
    ROOT / "scripts",
    ROOT / "src" / "offline" / "capture",
    ROOT / "src" / "offline" / "detection",
    ROOT / "src" / "online" / "reporting",
    SOURCE_ROOT / "agent",
    SOURCE_ROOT / "agent_v11",
    SOURCE_ROOT / "comparison",
    SOURCE_ROOT / "framework_v12",
    SOURCE_ROOT / "modeling",
    SOURCE_ROOT / "rag",
    SOURCE_ROOT / "retrieval",
    SOURCE_ROOT / "selection",
    SOURCE_ROOT / "service",
)
# `LEGACY_IMPORT` 检测已经迁移的旧 Python 包名。
LEGACY_IMPORT = re.compile(
    r"aiops_diag\.(?:agent_v11|agent|comparison|framework_v12|modeling|rag|retrieval|selection|service)"
)
# `CHINESE` 用于确认源码包含中文职责说明。
CHINESE = re.compile(r"[\u4e00-\u9fff]")
# `MECHANICAL_COMMENT` 匹配历史上批量生成的机械注释前缀，禁止再出现。
MECHANICAL_COMMENT = re.compile(r"^\s*#\s*(?:方法说明|类说明|变量说明)：")


# `_module_readme_errors` 检查每个 README 是否覆盖目录内所有 Python 文件。
def _module_readme_errors() -> list[str]:
    errors: list[str] = []
    for directory in MODULE_DIRS:
        readme = directory / "README.md"
        if not readme.is_file():
            errors.append(f"missing README: {readme.relative_to(ROOT).as_posix()}")
            continue
        text = readme.read_text(encoding="utf-8")
        for source in directory.glob("*.py"):
            if f"`{source.name}`" not in text:
                errors.append(
                    f"README does not describe {source.relative_to(ROOT).as_posix()}"
                )
    return errors


# `_source_comment_errors` 检查两条规则：模块 docstring 必填且含中文；不得出现机械注释标签。
def _source_comment_errors() -> list[str]:
    errors: list[str] = []
    python_files = sorted({source for directory in MODULE_DIRS for source in directory.glob("*.py")})
    for source in python_files:
        text = source.read_text(encoding="utf-8")
        relative = source.relative_to(ROOT).as_posix()
        docstring = ast.get_docstring(ast.parse(text))
        if not docstring or not CHINESE.search(docstring):
            errors.append(f"missing Chinese module docstring: {relative}")
        for number, line in enumerate(text.splitlines(), 1):
            if MECHANICAL_COMMENT.match(line):
                errors.append(f"mechanical comment label: {relative}:{number}")
    return errors


# `validate` 汇总目录、导入、README 和注释检查结果。
def _typed_source_errors() -> list[str]:
    """要求 `[tool.mypy] files` 列出的边界模块，所有函数都带返回标注。"""
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = settings.get("tool", {}).get("mypy", {}).get("files", [])
    errors: list[str] = []
    for relative in listed:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is None:
                errors.append(f"missing return annotation: {relative}:{node.lineno} {node.name}")
    return errors


def validate() -> dict:
    errors = _module_readme_errors() + _source_comment_errors() + _typed_source_errors()
    python_files = sorted({source for directory in MODULE_DIRS for source in directory.glob("*.py")})
    for directory in LEGACY_DIRS:
        if directory.exists():
            errors.append(f"legacy directory remains: {directory.relative_to(ROOT).as_posix()}")
    for source in SOURCE_ROOT.rglob("*.py"):
        if LEGACY_IMPORT.search(source.read_text(encoding="utf-8")):
            errors.append(f"legacy import remains: {source.relative_to(ROOT).as_posix()}")
    return {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "module_directory_count": len(MODULE_DIRS),
        "python_file_count": len(python_files),
        "errors": errors,
    }


# `main` 输出机器可读检查结果并设置进程退出码。
def main() -> int:
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
