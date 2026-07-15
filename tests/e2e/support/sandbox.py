from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from .model import CommandResult


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPEBUILDER = REPO_ROOT / "pipebuilder.py"
EXAMPLES = REPO_ROOT / "examples"


def _remove_readonly(func, path: str, exc_info) -> None:
    error = exc_info[1]
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    func(path)


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(str(path), onerror=_remove_readonly)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copytree_merge(source: Path, destination: Path) -> None:
    """Python 3.7-compatible equivalent of copytree(..., dirs_exist_ok=True)."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir() and not item.is_symlink():
            _copytree_merge(item, target)
        elif item.is_symlink():
            target.symlink_to(os.readlink(str(item)), target_is_directory=item.is_dir())
        else:
            shutil.copy2(str(item), str(target))


def snapshot_tree(root: Path, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    excluded = tuple(item.rstrip("/") for item in exclude)
    result: list[dict[str, Any]] = []
    if not root.exists():
        return result
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if any(relative == item or relative.startswith(item + "/") for item in excluded):
            continue
        mode = path.lstat().st_mode
        if path.is_symlink():
            result.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_dir():
            result.append({"path": relative, "kind": "directory"})
        elif path.is_file():
            result.append(
                {
                    "path": relative,
                    "kind": "file",
                    "sha256": _digest(path),
                    "executable": bool(mode & stat.S_IXUSR),
                    "size": path.stat().st_size,
                }
            )
        else:
            result.append({"path": relative, "kind": "other"})
    return result


class Sandbox:
    def __init__(self, example: str | None = None) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="pipebuilder-e2e-")
        self.base = Path(self._temporary.name)
        self.root = self.base / "space"
        self.home = self.base / "home"
        self.tmp = self.base / "tmp"
        self.captures = self.base / "captures"
        for path in (self.root, self.home, self.tmp, self.captures):
            path.mkdir(parents=True, exist_ok=True)
        self.commands: list[CommandResult] = []
        if example:
            self._load_example_inputs(example)

    def _load_example_inputs(self, name: str) -> None:
        source = EXAMPLES / name
        if not (source / "space").is_dir():
            raise AssertionError(f"example input not found: {source}")
        for directory in ("space", "providers", "projects"):
            candidate = source / directory
            if candidate.is_dir():
                _copytree_merge(candidate, self.base / directory)

    def copy_example(self, name: str, *, destination: Path | None = None) -> Path:
        source = EXAMPLES / name
        if not source.is_dir():
            raise AssertionError(f"example not found: {source}")
        target = destination or (self.base / "example")
        _copytree_merge(source, target)
        return target

    def close(self) -> None:
        _remove_tree(self.base)
        try:
            self._temporary.cleanup()
        except FileNotFoundError:
            pass

    def archive(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _remove_tree(destination)

        def ignore_sensitive(source: str, names: list[str]) -> set[str]:
            ignored = {name for name in names if name == "auth.json" or name.endswith((".pem", ".key"))}
            if Path(source) == self.base and "home" in names:
                ignored.add("home")
            return ignored

        shutil.copytree(
            self.base,
            destination,
            symlinks=True,
            ignore=ignore_sensitive,
        )
        (destination / "commands.json").write_text(
            json.dumps([item.report_record() for item in self.commands], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_text(self, relative: str, content: str, *, executable: bool = False, base: Path | None = None) -> Path:
        path = (base or self.root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def write_bytes(self, relative: str, content: bytes, *, base: Path | None = None) -> Path:
        path = (base or self.root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def write_json(self, relative: str, value: Any, *, base: Path | None = None) -> Path:
        return self.write_text(relative, json.dumps(value, ensure_ascii=False, indent=2) + "\n", base=base)

    def manifest(
        self,
        *,
        name: str = "fixture-space",
        agents: list[str] | None = None,
        skills: list[str] | None = None,
        tags: list[str] | None = None,
        providers: list[dict[str, str]] | None = None,
        folders: list[dict[str, str]] | None = None,
        description: str | None = None,
        children_scan_depth: int | None = None,
    ) -> None:
        value: dict[str, Any] = {
            "schema": "pipespace.v1",
            "name": name,
            "agents": agents if agents is not None else ["codex", "cursor", "codebuddy", "claude-code"],
            "skills": skills or [],
            "tags": tags or [],
            "skillProviders": providers or [],
        }
        if description is not None:
            value["description"] = description
        if children_scan_depth is not None:
            value["children"] = {"scanDepth": children_scan_depth}
        self.write_json("pipespace.json", value)
        self.write_json(f"{name}.code-workspace", {"folders": folders or [{"name": "project", "path": "."}]})

    def skill(
        self,
        base: str,
        name: str,
        *,
        tags: list[str] | None = None,
        description: str | None = None,
        body: str = "Fixture body.\n",
    ) -> Path:
        tag_lines = ""
        if tags:
            tag_lines = "tags:\n" + "".join(f"  - {tag}\n" for tag in tags)
        self.write_text(
            f"{base}/{name}/SKILL.md",
            f"---\nname: {name}\ndescription: {description or ('Fixture ' + name + '.')}\n{tag_lines}---\n\n{body}",
        )
        return self.root / base / name

    def controlled_env(self, extra: dict[str, str] | None = None, *, inherit_auth: bool = False) -> dict[str, str]:
        allow = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR")
        if inherit_auth:
            allow += ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR")
        env = {key: os.environ.get(key, "") for key in allow}
        env["HOME"] = str(self.home)
        env["USERPROFILE"] = str(self.home)
        env["APPDATA"] = str(self.home / "AppData" / "Roaming")
        env["LOCALAPPDATA"] = str(self.home / "AppData" / "Local")
        env.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
                "TZ": "UTC",
                "TMPDIR": str(self.tmp),
                "TEMP": str(self.tmp),
                "TMP": str(self.tmp),
                "NO_COLOR": "1",
            }
        )
        if extra:
            env.update(extra)
        return {key: value for key, value in env.items() if value is not None}

    def run_command(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30,
        inherit_auth: bool = False,
    ) -> CommandResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd or self.root),
                env=self.controlled_env(env, inherit_auth=inherit_auth),
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
            )
            result = CommandResult(argv, str(cwd or self.root), completed.returncode, completed.stdout, completed.stderr, time.monotonic() - started)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            result = CommandResult(argv, str(cwd or self.root), 124, stdout, stderr, time.monotonic() - started, True)
        self.commands.append(result)
        return result

    def builder(
        self,
        command: str,
        *args: str,
        env: dict[str, str] | None = None,
        from_cwd: bool = False,
        output_format: str = "json",
        timeout: float = 30,
    ) -> CommandResult:
        argv = [sys.executable, str(PIPEBUILDER), command]
        if not from_cwd:
            argv.append(str(self.root))
        argv.extend(("--format", output_format))
        argv.extend(args)
        return self.run_command(argv, cwd=self.root, env=env, timeout=timeout)

    def file_digest(self, relative: str) -> str:
        return _digest(self.root / relative)

    def snapshot_inputs(self) -> dict[str, list[dict[str, Any]]]:
        roots: dict[str, Path] = {"space": self.root}
        for name in ("providers", "projects"):
            candidate = self.base / name
            if candidate.exists():
                roots[name] = candidate
        snapshots = {
            name: snapshot_tree(
                path,
                exclude=(
                    ".pipebuilder/cache",
                    ".pipebuilder/generated",
                    ".pipebuilder/lock.json",
                    ".pipebuilder/build.lock",
                    ".agents",
                    ".codex",
                    ".cursor",
                    ".codebuddy",
                    ".claude",
                    "AGENTS.md",
                    "CLAUDE.md",
                    ".mcp.json",
                ) if name == "space" else (),
            )
            for name, path in roots.items()
        }
        snapshots["space"] = [item for item in snapshots["space"] if item["path"] != ".pipebuilder"]
        return snapshots

    def managed_tree(self) -> list[dict[str, Any]]:
        lock_path = self.root / ".pipebuilder" / "lock.json"
        if not lock_path.is_file():
            return []
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        targets = {item["target"] for item in lock["artifacts"]}
        targets.add(".pipebuilder/lock.json")
        result: list[dict[str, Any]] = []
        for relative in sorted(targets):
            path = self.root / relative
            result.append(
                {
                    "path": relative,
                    "sha256": _digest(path),
                    "executable": bool(path.stat().st_mode & stat.S_IXUSR),
                    "size": path.stat().st_size,
                }
            )
        return result
