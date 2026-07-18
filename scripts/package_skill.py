#!/usr/bin/env python3
"""Build the release ZIP for the PipeBuilder Agent Skill."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path


SKILL_NAME = "pipebuilder"
MEMBERS = (
    "SKILL.md",
    "pipebuilder.py",
    "scripts/update.py",
)
NAME_RE = re.compile(r"^name:\s*pipebuilder\s*$", re.MULTILINE)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def validate_sources(root: Path) -> None:
    for relative in MEMBERS:
        if not (root / relative).is_file():
            raise RuntimeError(f"missing Skill file: {relative}")
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    if not skill.startswith("---\n") or NAME_RE.search(skill) is None:
        raise RuntimeError("SKILL.md must declare name: pipebuilder")


def zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def build_archive(root: Path, output: Path) -> None:
    validate_sources(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(output), "w") as archive:
        for relative in MEMBERS:
            source = root / relative
            archive.writestr(
                zip_info(f"{SKILL_NAME}/{relative}", source.stat().st_mode),
                source.read_bytes(),
            )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(
        f"{digest}  {output.name}\n",
        encoding="ascii",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the PipeBuilder Agent Skill")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/pipebuilder-skill.zip"),
        help="ZIP output path",
    )
    args = parser.parse_args()
    root = repository_root()
    output = args.output.resolve()
    build_archive(root, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
