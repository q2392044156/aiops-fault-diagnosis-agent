"""校验文档里写下的 `python -m` 命令都指向真实存在的模块，防止文档随重构漂移。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
COMMAND = re.compile(r"python\s+-m\s+([A-Za-z_][\w.]*)")
OWNED = ("online", "offline", "aiops_diag", "evaluation")
SKIPPED = {"__pycache__", "artifacts", "experiments", "runtime"}


def documented_modules() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in ROOT.rglob("*.md"):
        relative = path.relative_to(ROOT)
        if SKIPPED & set(relative.parts) or any(part.startswith(".") for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for match in COMMAND.finditer(line):
                module = match.group(1)
                if module.split(".")[0] in OWNED:
                    found.append((path.relative_to(ROOT).as_posix(), number, module))
    return found


def module_path(module: str) -> Path | None:
    parts = module.split(".")
    module_file = SOURCE.joinpath(*parts).with_suffix(".py")
    package_file = SOURCE.joinpath(*parts, "__init__.py")
    for candidate in (module_file, package_file):
        if candidate.is_file():
            return candidate
    return None


def test_documented_module_commands_exist() -> None:
    commands = documented_modules()
    assert commands, "没有解析到任何 python -m 命令，正则或文档结构变了"
    missing = [f"{path}:{number}: {module}" for path, number, module in commands if module_path(module) is None]
    assert not missing, "文档命令指向不存在的模块：\n" + "\n".join(missing)
