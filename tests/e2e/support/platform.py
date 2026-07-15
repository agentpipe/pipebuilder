from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from .sandbox import Sandbox


def try_symlink(target: Path, link: Path, *, target_is_directory: bool = False) -> None:
    """Create a symlink fixture; skip the case when the host cannot create one."""
    try:
        if link.exists() or link.is_symlink():
            if link.is_symlink() or link.is_file():
                link.unlink()
            else:
                raise OSError(f"refusing to replace non-symlink path: {link}")
        os.symlink(str(target), str(link), target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        raise unittest.SkipTest(f"symlink fixture unavailable: {exc}") from exc


def write_reserved_device_source(box: Sandbox, relative: str, content: str) -> Path:
    """Write a Windows reserved device-name source file when the OS allows it."""
    path = box.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        extended = "\\\\?\\" + str(path.resolve())
        try:
            with open(extended, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            return path
        except OSError as exc:
            raise unittest.SkipTest(f"Windows reserved device-name fixture unavailable: {exc}") from exc
    return box.write_text(relative, content)


def git_stores_symlink(repo: Path, relative: str) -> bool:
    """Return True when git index records the path as a symlink (mode 120000)."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-s", "--", relative],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return False
    lines = completed.stdout.strip().splitlines()
    if not lines:
        return False
    return lines[0].startswith("120000 ")


def require_git_symlink_fixture(repo: Path, relative: str) -> None:
    if not git_stores_symlink(repo, relative):
        raise unittest.SkipTest(
            "Git did not store a symlink at "
            f"{relative}; archive symlink rejection cannot be exercised on this platform."
        )
