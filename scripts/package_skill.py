#!/usr/bin/env python3
"""Build the release ZIP for the PipeBuilder Agent Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path


SKILL_NAME = "pipebuilder"
PACKAGE_SCHEMA = "pipebuilder-skill-package.v1"
PACKAGE_MANIFEST = ".skill-package.json"
ROOT_FILES = ("SKILL.md", "pipebuilder.py")
RESOURCE_DIRS = (".pipe-agents", "agents", "assets", "references", "scripts")
REQUIRED_FILES = ("SKILL.md", "pipebuilder.py", "scripts/update.py")
IGNORED_NAMES = frozenset({".DS_Store", "__pycache__"})
IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})
NAME_RE = re.compile(r"^name:\s*pipebuilder\s*$", re.MULTILINE)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def ignored(relative: Path) -> bool:
    return (
        any(part in IGNORED_NAMES for part in relative.parts)
        or relative.suffix in IGNORED_SUFFIXES
    )


def discover_sources(root: Path) -> list[str]:
    files: list[str] = []
    for relative in ROOT_FILES:
        source = root / relative
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"missing or unsafe Skill file: {relative}")
        files.append(relative)
    for directory in RESOURCE_DIRS:
        source_root = root / directory
        if not source_root.exists():
            continue
        if source_root.is_symlink() or not source_root.is_dir():
            raise RuntimeError(f"unsafe Skill resource directory: {directory}")
        for source in sorted(source_root.rglob("*")):
            relative_path = source.relative_to(root)
            if ignored(relative_path):
                continue
            if source.is_symlink() or (source.exists() and not source.is_file() and not source.is_dir()):
                raise RuntimeError(f"unsafe Skill resource: {relative_path.as_posix()}")
            if source.is_file():
                files.append(relative_path.as_posix())
    missing = sorted(set(REQUIRED_FILES).difference(files))
    if missing:
        raise RuntimeError("missing required Skill files: " + ", ".join(missing))
    return sorted(files)


def validate_sources(root: Path) -> list[str]:
    files = discover_sources(root)
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    if not skill.startswith("---\n") or NAME_RE.search(skill) is None:
        raise RuntimeError("SKILL.md must declare name: pipebuilder")
    return files


def zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (mode & 0o777)) << 16
    return info


def package_manifest(root: Path, files: list[str]) -> bytes:
    entries = []
    for relative in files:
        source = root / relative
        payload = source.read_bytes()
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mode": stat.S_IMODE(source.stat().st_mode),
            }
        )
    return (
        json.dumps(
            {"schema": PACKAGE_SCHEMA, "files": entries},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def build_archive(root: Path, output: Path) -> None:
    files = validate_sources(root)
    manifest = package_manifest(root, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(output), "w") as archive:
        members = [(PACKAGE_MANIFEST, manifest, 0o644)]
        members.extend(
            (
                relative,
                (root / relative).read_bytes(),
                stat.S_IMODE((root / relative).stat().st_mode),
            )
            for relative in files
        )
        for relative, payload, mode in sorted(members):
            archive.writestr(
                zip_info(f"{SKILL_NAME}/{relative}", mode),
                payload,
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
