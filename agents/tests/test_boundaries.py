"""The agents package must stay independent of the web layer and the other layers."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_TOP_LEVEL = {"fastapi", "starlette", "uvicorn", "app", "backend", "frontend", "nuxt"}
SKIPPED_DIRS = {
    ".venv",
    "build",
    "dist",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _python_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if not any(part in SKIPPED_DIRS for part in path.relative_to(PACKAGE_ROOT).parts)
    )


def _imported_top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_package_files_are_scanned() -> None:
    files = _python_files()
    assert PACKAGE_ROOT / "core" / "agent.py" in files
    assert PACKAGE_ROOT / "implementations" / "example_agent.py" in files
    assert not any(".venv" in path.parts for path in files)


def test_no_forbidden_imports() -> None:
    offenders = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            _imported_top_level_names(path) & FORBIDDEN_TOP_LEVEL
        )
        for path in _python_files()
    }
    offenders = {file: names for file, names in offenders.items() if names}
    assert offenders == {}, f"forbidden imports found: {offenders}"


def test_runtime_dependencies_are_only_pydantic() -> None:
    pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dependencies_line = next(
        line for line in pyproject.splitlines() if line.startswith("dependencies = ")
    )
    assert "pydantic>=2.11" in dependencies_line
    assert "pydantic-settings>=2.10" in dependencies_line
    assert "fastapi" not in dependencies_line
