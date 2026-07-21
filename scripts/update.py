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
from pathlib import Path, PurePosixPath


REPOSITORY = "agentpipe/pipebuilder"
ARCHIVE = "pipebuilder-skill.zip"
SKILL_NAME = "pipebuilder"
PACKAGE_SCHEMA = "pipebuilder-skill-package.v1"
PACKAGE_MANIFEST = ".skill-package.json"
ROOT_FILES = frozenset({"SKILL.md", "pipebuilder.py"})
RESOURCE_DIRS = frozenset({".pipe-agents", "agents", "assets", "references", "scripts"})
REQUIRED_FILES = frozenset({"SKILL.md", "pipebuilder.py", "scripts/update.py"})
IGNORED_NAMES = frozenset({".DS_Store", "__pycache__"})
IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
NAME_RE = re.compile(r"^name:\s*pipebuilder\s*$", re.MULTILINE)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


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


def validate_package_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"unsafe package path: {value!r}")
    path = PurePosixPath(value)
    if value != path.as_posix() or path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"unsafe package path: {value!r}")
    if any(part in IGNORED_NAMES for part in path.parts) or path.suffix in IGNORED_SUFFIXES:
        raise RuntimeError(f"unsupported package path: {value}")
    if value in ROOT_FILES:
        return value
    if len(path.parts) > 1 and path.parts[0] in RESOURCE_DIRS:
        return value
    raise RuntimeError(f"package path is outside the Skill directory convention: {value}")


def parse_manifest(payload: bytes) -> dict[str, tuple[str, int]]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("package manifest must be valid UTF-8 JSON") from exc
    if not isinstance(document, dict) or document.get("schema") != PACKAGE_SCHEMA:
        raise RuntimeError(f"package manifest must declare schema {PACKAGE_SCHEMA}")
    entries = document.get("files")
    if not isinstance(entries, list):
        raise RuntimeError("package manifest files must be an array")
    files: dict[str, tuple[str, int]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "mode"}:
            raise RuntimeError("package manifest entries require path, sha256, and mode")
        relative = validate_package_path(entry["path"])
        digest = entry["sha256"]
        mode = entry["mode"]
        if relative in files:
            raise RuntimeError(f"duplicate package manifest path: {relative}")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise RuntimeError(f"invalid package SHA-256: {relative}")
        if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o777:
            raise RuntimeError(f"invalid package mode: {relative}")
        files[relative] = (digest, mode)
    missing = sorted(REQUIRED_FILES.difference(files))
    if missing:
        raise RuntimeError("package is missing required Skill files: " + ", ".join(missing))
    return files


def inspect_archive(payload: bytes) -> tuple[dict[str, bytes], dict[str, int], bytes, str]:
    manifest_name = f"{SKILL_NAME}/{PACKAGE_MANIFEST}"
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise RuntimeError("release archive contains duplicate paths")
            if manifest_name not in names:
                raise RuntimeError(f"release archive is missing {manifest_name}")
            manifest_payload = archive.read(manifest_name)
            entries = parse_manifest(manifest_payload)
            expected = {manifest_name} | {
                f"{SKILL_NAME}/{relative}" for relative in entries
            }
            if set(names) != expected:
                raise RuntimeError("release archive paths do not match its package manifest")
            for info in infos:
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if info.is_dir() or stat.S_ISLNK(unix_mode):
                    raise RuntimeError(f"release archive contains a non-file path: {info.filename}")
            files: dict[str, bytes] = {}
            modes: dict[str, int] = {}
            for relative, (expected_digest, mode) in entries.items():
                content = archive.read(f"{SKILL_NAME}/{relative}")
                if hashlib.sha256(content).hexdigest() != expected_digest:
                    raise RuntimeError(f"package file SHA-256 mismatch: {relative}")
                files[relative] = content
                modes[relative] = mode
    except zipfile.BadZipFile as exc:
        raise RuntimeError("release asset is not a valid ZIP archive") from exc

    try:
        skill = files["SKILL.md"].decode("utf-8")
        source = files["pipebuilder.py"].decode("utf-8")
        updater = files["scripts/update.py"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("required Skill text files must be valid UTF-8") from exc
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
    return files, modes, manifest_payload, match.group(1)


def installed_files(root: Path) -> set[str]:
    manifest = root / PACKAGE_MANIFEST
    if not manifest.exists():
        return set(REQUIRED_FILES)
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError(f"installed {PACKAGE_MANIFEST} is not a regular file")
    try:
        return set(parse_manifest(manifest.read_bytes()))
    except RuntimeError:
        # Recover a damaged local manifest without guessing which optional files
        # are safe to delete.
        return set(REQUIRED_FILES)


def safe_target(root: Path, relative: str) -> Path:
    target = root / relative
    parent = root
    for part in PurePosixPath(relative).parts[:-1]:
        parent = parent / part
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise RuntimeError(f"unsafe installed Skill directory: {parent}")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise RuntimeError(f"unsafe installed Skill file: {target}")
    return target


def write_temporary(target: Path, payload: bytes, mode: int) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=str(target.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(str(temporary), mode)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise
    return temporary


def replace_skill(
    root: Path,
    files: dict[str, bytes],
    modes: dict[str, int],
    manifest_payload: bytes,
    stale: set[str],
) -> None:
    updates = dict(files)
    updates[PACKAGE_MANIFEST] = manifest_payload
    update_modes = dict(modes)
    update_modes[PACKAGE_MANIFEST] = 0o644
    ordered_updates = sorted(files) + [PACKAGE_MANIFEST]
    touched_paths = set(ordered_updates) | stale
    targets = {relative: safe_target(root, relative) for relative in touched_paths}
    originals = {
        relative: (
            (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))
            if target.is_file()
            else None
        )
        for relative, target in targets.items()
    }
    temporary: dict[str, Path] = {}
    touched: list[str] = []
    try:
        for relative in ordered_updates:
            temporary[relative] = write_temporary(
                targets[relative], updates[relative], update_modes[relative]
            )
        for relative in sorted(files):
            os.replace(str(temporary[relative]), str(targets[relative]))
            touched.append(relative)
        for relative in sorted(stale):
            target = targets[relative]
            if target.exists():
                target.unlink()
                touched.append(relative)
        os.replace(str(temporary[PACKAGE_MANIFEST]), str(targets[PACKAGE_MANIFEST]))
        touched.append(PACKAGE_MANIFEST)
    except OSError:
        for relative in reversed(touched):
            target = targets[relative]
            original = originals[relative]
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                rollback = write_temporary(target, original[0], original[1])
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
        files, modes, manifest_payload, version = inspect_archive(archive_payload)
        root = skill_root()
        previous_files = installed_files(root)
        for relative in set(files) | previous_files | {PACKAGE_MANIFEST}:
            safe_target(root, relative)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"update failed: {exc}", file=sys.stderr)
        return 1

    stale = previous_files.difference(files)
    changed = (
        not (root / PACKAGE_MANIFEST).is_file()
        or (root / PACKAGE_MANIFEST).read_bytes() != manifest_payload
        or any(
            not (root / relative).is_file()
            or (root / relative).read_bytes() != payload
            or stat.S_IMODE((root / relative).stat().st_mode) != modes[relative]
            for relative, payload in files.items()
        )
        or any((root / relative).exists() for relative in stale)
    )
    if not args.dry_run and changed:
        try:
            replace_skill(root, files, modes, manifest_payload, stale)
        except (OSError, RuntimeError) as exc:
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
                "files": sorted(files),
                "removed": sorted(stale),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
