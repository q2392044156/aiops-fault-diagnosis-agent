"""模块说明：验证功能目录、模块 README 和中文源码说明是否完整。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


# 变量说明：`ROOT` 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[2]
# 变量说明：`SOURCE_ROOT` 指向 Python 业务包目录。
SOURCE_ROOT = ROOT / "src" / "aiops_diag"
# 变量说明：`MODULE_DIRS` 列出必须保持内聚的功能模块。
MODULE_DIRS = (
    SOURCE_ROOT,
    SOURCE_ROOT / "data",
    SOURCE_ROOT / "detection",
    SOURCE_ROOT / "detection" / "selection",
    SOURCE_ROOT / "knowledge",
    SOURCE_ROOT / "knowledge" / "generation",
    SOURCE_ROOT / "diagnosis",
    SOURCE_ROOT / "diagnosis" / "query_v11",
    SOURCE_ROOT / "diagnosis" / "framework",
    SOURCE_ROOT / "evaluation",
    SOURCE_ROOT / "platform",
    SOURCE_ROOT / "release",
    ROOT / "ops" / "scripts",
    ROOT / "ops" / "deployment",
    ROOT / "tests",
    ROOT / "src" / "offline",
    ROOT / "src" / "offline" / "capture",
    ROOT / "src" / "offline" / "ingestion",
    ROOT / "src" / "offline" / "detection",
    ROOT / "src" / "offline" / "evaluation",
    ROOT / "src" / "online",
    ROOT / "src" / "online" / "diagnosis",
    ROOT / "src" / "online" / "knowledge",
    ROOT / "src" / "online" / "reporting",
)
# 变量说明：`LEGACY_DIRS` 列出重构后不应重新出现的旧目录。
LEGACY_DIRS = (
    ROOT / "configs",
    ROOT / "deployment",
    ROOT / "deliverables",
    ROOT / "docs",
    ROOT / "evaluation",
    ROOT / "knowledge",
    ROOT / "scripts",
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
# 变量说明：`LEGACY_IMPORT` 检测已经迁移的旧 Python 包名。
LEGACY_IMPORT = re.compile(
    r"aiops_diag\.(?:agent_v11|agent|comparison|framework_v12|modeling|rag|retrieval|selection|service)"
)
# 变量说明：`CHINESE` 用于确认源码包含中文职责说明。
CHINESE = re.compile(r"[\u4e00-\u9fff]")


# 方法说明：`_module_readme_errors` 检查每个 README 是否覆盖目录内所有 Python 文件。
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


# 方法说明：`_source_comment_errors` 检查每个源码文件及其类和方法是否具有中文说明。
def _source_comment_errors() -> list[str]:
    errors: list[str] = []
    python_files = sorted({source for directory in MODULE_DIRS for source in directory.glob("*.py")})
    for source in python_files:
        text = source.read_text(encoding="utf-8")
        if not CHINESE.search(text):
            errors.append(f"missing Chinese explanation: {source.relative_to(ROOT).as_posix()}")
            continue
        tree = ast.parse(text)
        lines = text.splitlines()
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first_line = min([node.lineno, *(item.lineno for item in node.decorator_list)])
                label = "callable"
            elif (isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                  and isinstance(parents.get(node), (ast.Module, ast.ClassDef))):
                first_line = node.lineno
                label = "module or model variable"
            else:
                continue
            before = lines[first_line - 2].strip() if first_line > 1 else ""
            if not (before.startswith("#") and CHINESE.search(before)):
                errors.append(
                    f"missing Chinese {label} comment: "
                    f"{source.relative_to(ROOT).as_posix()}:{first_line}"
                )
    return errors


# 方法说明：`validate` 汇总目录、导入、README 和注释检查结果。
def validate() -> dict:
    errors = _module_readme_errors() + _source_comment_errors()
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


# 方法说明：`main` 输出机器可读检查结果并设置进程退出码。
def main() -> int:
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
