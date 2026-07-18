#!/usr/bin/env python3
"""Update an installed PipeBuilder Skill from a GitHub Release ZIP."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


REPOSITORY = "agentpipe/pipebuilder"
ARCHIVE = "pipebuilder-skill.zip"
SKILL_NAME = "pipebuilder"
MEMBERS = (
    "SKILL.md",
    "pipebuilder.py",
    "scripts/update.py",
)
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
NAME_RE = re.compile(r"^name:\s*pipebuilder\s*$", re.MULTILINE)


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def release_url(tag: str | None) -> str:
    if tag:
        selector = "download/" + urllib.parse.quote(tag, safe="")
    else:
        selector = "latest/download"
    base = f"https://github.com/{REPOSITORY}/releases/{selector}"
    return f"{base}/{ARCHIVE}"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pipebuilder-skill-updater"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def checksum_url(archive_url: str) -> str:
    return archive_url + ".sha256"


def verify_checksum(payload: bytes, checksum_payload: bytes) -> str:
    try:
        checksum_text = checksum_payload.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("release checksum must be ASCII") from exc
    match = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?\S+)?", checksum_text)
    if match is None:
        raise RuntimeError("release checksum is not a valid SHA-256 record")
    expected = match.group(1).lower()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RuntimeError("release archive SHA-256 mismatch")
    return actual


def inspect_archive(payload: bytes) -> tuple[dict[str, bytes], str]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            expected = {f"{SKILL_NAME}/{relative}" for relative in MEMBERS}
            names = set(archive.namelist())
            if names != expected:
                raise RuntimeError(
                    "archive must contain exactly: " + ", ".join(sorted(expected))
                )
            files = {
                relative: archive.read(f"{SKILL_NAME}/{relative}")
                for relative in MEMBERS
            }
    except zipfile.BadZipFile as exc:
        raise RuntimeError("release asset is not a valid ZIP archive") from exc

    try:
        skill = files["SKILL.md"].decode("utf-8")
        source = files["pipebuilder.py"].decode("utf-8")
        updater = files["scripts/update.py"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Skill text files must be valid UTF-8") from exc
    if not skill.startswith("---\n") or NAME_RE.search(skill) is None:
        raise RuntimeError("SKILL.md must declare name: pipebuilder")
    match = VERSION_RE.search(source)
    if match is None:
        raise RuntimeError("pipebuilder.py is missing the VERSION declaration")
    try:
        compile(source, "pipebuilder.py", "exec", dont_inherit=True)
        compile(updater, "scripts/update.py", "exec", dont_inherit=True)
    except SyntaxError as exc:
        raise RuntimeError(f"release Python does not compile: {exc}") from exc
    if "independently distributable single-file CLI" not in source[:8000]:
        raise RuntimeError("pipebuilder.py is not a PipeBuilder standalone CLI")
    return files, match.group(1)


def write_temporary(target: Path, payload: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=str(target.parent))
    temporary = Path(name)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    previous_mode = target.stat().st_mode if target.exists() else None
    if previous_mode is not None:
        os.chmod(str(temporary), stat.S_IMODE(previous_mode))
    elif target.suffix == ".py":
        os.chmod(
            str(temporary),
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IROTH,
        )
    return temporary


def replace_skill(root: Path, files: dict[str, bytes]) -> None:
    temporary: dict[str, Path] = {}
    originals: dict[str, tuple[bytes, int] | None] = {}
    replaced: list[str] = []
    try:
        for relative, payload in files.items():
            target = root / relative
            originals[relative] = (
                (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))
                if target.is_file()
                else None
            )
            temporary[relative] = write_temporary(target, payload)
        for relative in MEMBERS:
            os.replace(str(temporary[relative]), str(root / relative))
            replaced.append(relative)
    except OSError:
        for relative in reversed(replaced):
            target = root / relative
            original = originals[relative]
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                rollback = write_temporary(target, original[0])
                os.chmod(str(rollback), original[1])
                os.replace(str(rollback), str(target))
        raise
    finally:
        for path in temporary.values():
            if path.exists():
                path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update an installed PipeBuilder Skill from GitHub Releases"
    )
    parser.add_argument("--tag", help="Release tag to install; defaults to the latest Release")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and validate the Release without replacing files",
    )
    parser.add_argument("--archive-url", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    archive_url = args.archive_url or release_url(args.tag)
    archive_checksum_url = checksum_url(archive_url)
    try:
        archive_payload = download(archive_url)
        archive_checksum = verify_checksum(
            archive_payload,
            download(archive_checksum_url),
        )
        files, version = inspect_archive(archive_payload)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"update failed: {exc}", file=sys.stderr)
        return 1

    root = skill_root()
    changed = any(
        not (root / relative).is_file()
        or (root / relative).read_bytes() != payload
        for relative, payload in files.items()
    )
    if not args.dry_run and changed:
        try:
            replace_skill(root, files)
        except OSError as exc:
            print(f"update failed: {exc}", file=sys.stderr)
            return 1
    print(
        json.dumps(
            {
                "ok": True,
                "dryRun": args.dry_run,
                "changed": changed,
                "version": version,
                "archive": archive_url,
                "archiveSha256": archive_checksum,
                "checksum": archive_checksum_url,
                "target": str(root),
                "files": list(MEMBERS),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
