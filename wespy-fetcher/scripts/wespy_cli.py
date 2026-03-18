#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeSpy skill wrapper.

- Prefers an explicit WESPY_REPO_DIR
- Reuses the current repository if the skill lives inside a WeSpy checkout
- Clones the forked repository automatically when missing
- Delegates CLI behavior to wespy.main.main
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

FORK_REPO = "https://github.com/whynpc9/WeSpy.git"
DEFAULT_BASE_DIR = Path.home() / "Documents" / "QNSZ" / "project"
DEFAULT_WESPY_DIR = DEFAULT_BASE_DIR / "WeSpy"


def resolve_repo_dir() -> Path:
    env_dir = os.environ.get("WESPY_REPO_DIR")
    if env_dir:
        repo_dir = Path(env_dir).expanduser().resolve()
        validate_repo_dir(repo_dir)
        return repo_dir

    script_path = Path(__file__).resolve()
    repo_candidate = script_path.parents[2]
    if (repo_candidate / "wespy" / "main.py").exists():
        return repo_candidate

    DEFAULT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_WESPY_DIR.exists():
        print(f"[wespy-fetcher] 未检测到 WeSpy，正在克隆到: {DEFAULT_WESPY_DIR}")
        subprocess.run(["git", "clone", FORK_REPO, str(DEFAULT_WESPY_DIR)], check=True)

    validate_repo_dir(DEFAULT_WESPY_DIR)
    return DEFAULT_WESPY_DIR


def validate_repo_dir(repo_dir: Path) -> None:
    if not (repo_dir / "wespy" / "main.py").exists():
        raise RuntimeError(f"无效的 WeSpy 目录: {repo_dir}")


def main() -> int:
    repo_dir = resolve_repo_dir()
    sys.path.insert(0, str(repo_dir))

    try:
        from wespy.main import main as wespy_main  # type: ignore
    except Exception as exc:
        print(f"[wespy-fetcher] 导入 wespy.main 失败: {exc}", file=sys.stderr)
        print("请检查依赖是否已安装：pip3 install -r scripts/requirements.txt", file=sys.stderr)
        return 1

    wespy_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
