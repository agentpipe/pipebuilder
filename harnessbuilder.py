#!/usr/bin/env python3
"""HarnessBuilder：可独立分发的单文件 Harness Space 编译器。

发布与运行要求
------------
只需要分发本文件，不依赖本仓库中的 README、docs、tests 或 Python 第三方包。
运行环境要求 Python 3.7+；只有使用 Git Provider 时才需要系统安装 git。

快速使用
--------
    python3 harnessbuilder.py init [SPACE] [--name NAME] [--format text|json]
    python3 harnessbuilder.py check [SPACE] [--format text|json] [--offline]
    python3 harnessbuilder.py explain [SPACE] [--format text|json] [--offline]
    python3 harnessbuilder.py build [SPACE] [--format text|json] [--offline] [--dry-run]
    python3 harnessbuilder.py clean [SPACE] [--format text|json]
    python3 harnessbuilder.py --version
    python3 harnessbuilder.py --help

SPACE 省略时使用当前目录。建议先运行 check 或 build --dry-run，再运行 build。
--offline 只从已有 lock 和本地 immutable Git cache 解析 Git Provider，不访问 origin。

Harness Space 最小输入
---------------------
    <space>/
    ├── harness-space.json
    └── <manifest.name>.code-workspace

最小 harness-space.json：
    {"schema":"harness-space.v1", "name":"my-space", "agents":["codex"],
     "skills":[], "tags":[], "skillProviders":[]}

最小 my-space.code-workspace：
    {"folders":[{"name":"project", "path":"."}]}

可选的 Space-level source：
    .harness-builder/agents/<agent>/
    .harness-builder/skills/<skill>/SKILL.md

外部 Skill Provider 在 harness-space.json.skillProviders 中声明。支持：
    {"type":"folder", "path":"../shared-skills"}
    {"type":"folder", "path":"../component", "subdir":"skills",
     "command":{"cwd":".", "args":["node","build.mjs","--output","{spaceRoot}"]}}
    {"type":"git", "url":"https://example/repo.git", "branch":"main", "subdir":"skills"}
    {"type":"git", "url":"https://example/repo.git", "tag":"v1.0.0", "subdir":"skills"}

Git Provider 的 branch/tag 严格二选一；认证交给 Git credential helper 或 SSH agent，
不得把 credential 写入 manifest。HARNESSBUILDER_CACHE_DIR 可覆盖默认用户 cache，
但 cache 必须位于 Harness Space 之外。

Folder/Git 的 subdir 是 Skill Provider 根，默认为 .。可选 command 默认在正常 build 后调用；
cwd 相对 Provider 源根，args 不经 shell，并展开 {spaceRoot}、{sourceRoot}、{providerRoot}。
check、explain 和 build --dry-run 不调用 command。

所有权与输出
-----------
平台配置和安装后的 Skill 是 Builder-owned target；Human-owned source 只能放在
.harness-builder/agents、.harness-builder/skills 或外部 Provider 中。build 将 ownership
写入 .harness-builder/lock.json；clean 只删除有效 lock 证明由 Builder 管理的文件。
不要直接维护生成的 AGENTS.md、CLAUDE.md、.codex、.cursor、.codebuddy、.claude 或
.agents/skills 内容，应修改 source 后重新 build。

自动化应使用 --format json，并依赖 harnessbuilder-report.v1 中稳定的 diagnostic code，
不要解析人类可读 message。完整命令说明可随时运行本文件的 --help 查看。
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from datetime import datetime, timezone
from urllib.parse import urlsplit

try:
    import tomllib as _tomllib
except ImportError:  # Python 3.7-3.10 use the dependency-free compatibility parser below.
    _tomllib = None


VERSION = "0.3.0"
REPORT_SCHEMA = "harnessbuilder-report.v1"
LOCK_SCHEMA = "harnessbuilder-lock.v1"
SPACE_SCHEMA = "harness-space.v1"
AGENTS = ("codex", "cursor", "codebuddy", "claude-code")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
BARE_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SECRET_KEY_RE = re.compile(
    r"(^|[_-])(token|password|passwd|secret|api[_-]?key|authorization|credential)([_-]|$)",
    re.IGNORECASE,
)
LEGACY_NAMES = (
    "tagents",
    "private",
    ".harness-agents",
    ".harness-space.yaml",
    ".harness-lock.yaml",
)
ADAPTER_VERSIONS = {"codex": "2", "cursor": "1", "codebuddy": "2", "claude-code": "2"}
ADAPTER_STATUS = {
    "codex": "client-verified",
    "cursor": "generated-only",
    "codebuddy": "generated-only",
    "claude-code": "generated-only",
}
CODEX_FORBIDDEN_PROJECT_KEYS = {
    "openai_base_url",
    "chatgpt_base_url",
    "apps_mcp_product_sku",
    "model_provider",
    "model_providers",
    "notify",
    "profile",
    "profiles",
    "experimental_realtime_ws_base_url",
    "otel",
}
DIAGNOSTIC_ACTIONS = {
    "HB001": "Correct harness-space.json or the ownership lock to match the documented schema.",
    "HB002": "Use a lowercase kebab-case Harness Space name.",
    "HB003": "Create the required <manifest-name>.code-workspace file.",
    "HB004": "Correct the workspace folders and paths.",
    "HB005": "Correct the Provider path or create the directory.",
    "HB006": "Use a supported Skill Provider type.",
    "HB007": "Add the Skill to a configured Provider or remove it from the explicit selection.",
    "HB008": "Correct the Skill package and SKILL.md frontmatter.",
    "HB009": "Use the supported native artifact grammar for this Agent.",
    "HB010": "Resolve the ownership, target, or semantic conflict and rebuild.",
    "HB011": "Remove the unsafe path, secret, or configuration and retry.",
    "HB012": "Use an implemented Agent adapter.",
    "HB013": "Wait for the active build or clean operation to finish.",
    "HB014": "Confirm the process is gone, then remove the stale build.lock.",
    "HB015": "Migrate the legacy THarness layout before building.",
    "HB016": "Correct the Provider post command or its runtime dependencies and retry.",
    "HBW001": "Review the selected Provider and shadowed Skill candidates.",
    "HBW002": "Prefer a standard Skill for new Claude Code workflows.",
    "HBW003": "Review the generated platform security surface before use.",
}


@dataclasses.dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    sources: tuple[str, ...] = ()
    target: str | None = None
    semantic_key: str | None = None
    suggested_action: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "sources": list(self.sources),
        }
        if self.target is not None:
            result["target"] = self.target
        if self.semantic_key is not None:
            result["semanticKey"] = self.semantic_key
        if self.target is None and self.semantic_key is None:
            result["semanticKey"] = self.code
        result["suggestedAction"] = self.suggested_action or DIAGNOSTIC_ACTIONS.get(
            self.code,
            "Review the diagnostic source and correct the Harness Space input.",
        )
        return result


class HarnessError(Exception):
    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def fail(
    code: str,
    message: str,
    *,
    sources: Iterable[str] = (),
    target: str | None = None,
    semantic_key: str | None = None,
    action: str | None = None,
) -> None:
    raise HarnessError(
        Diagnostic(
            "error",
            code,
            message,
            tuple(sources),
            target,
            semantic_key,
            action,
        )
    )


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def portable_rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return path.as_posix()


def read_json(path: Path, code: str, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(code, f"{label} not found: {path.name}", sources=(path.as_posix(),))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(code, f"Invalid {label}: {exc}", sources=(path.as_posix(),))


def require_string_list(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        fail("HB001", f"manifest.{field} must be an array of non-empty strings")
    if nonempty and not value:
        fail("HB001", f"manifest.{field} must contain at least one item")
    if len(set(value)) != len(value):
        fail("HB001", f"manifest.{field} must not contain duplicates")
    return list(value)


def yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
        return parsed if isinstance(parsed, str) else value
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def yaml_inline_list(value: str, path: Path, key: str, code: str = "HB008") -> list[Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            if value.startswith("[") and value.endswith("]"):
                parsed = [yaml_scalar(item) for item in value[1:-1].split(",") if item.strip()]
            else:
                parsed = None
    if not isinstance(parsed, list):
        fail(code, f"Invalid inline list for {key}", sources=(path.as_posix(),))
    return parsed


def yaml_block_scalar(marker: str, body: list[str]) -> str:
    nonempty = [len(line) - len(line.lstrip()) for line in body if line.strip()]
    indent = min(nonempty) if nonempty else 0
    values = [line[indent:] if line.strip() else "" for line in body]
    if marker.startswith("|"):
        result = "\n".join(values)
    else:
        chunks: list[str] = []
        for value in values:
            if not value:
                chunks.append("\n")
            elif chunks and not chunks[-1].endswith("\n"):
                chunks.append(" " + value)
            else:
                chunks.append(value)
        result = "".join(chunks)
    if marker.endswith("-"):
        return result.rstrip("\n")
    return result.rstrip("\n") + "\n"


def parse_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        fail("HB008", "SKILL.md must be UTF-8", sources=(path.as_posix(),))
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail("HB008", "SKILL.md is missing YAML frontmatter", sources=(path.as_posix(),))
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        fail("HB008", "SKILL.md frontmatter is not closed", sources=(path.as_posix(),))
    fields: list[tuple[str, str, list[str]]] = []
    i = 1
    while i < end:
        raw = lines[i]
        i += 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[:1].isspace() or ":" not in raw:
            fail("HB008", f"Unsupported SKILL.md frontmatter syntax: {stripped}", sources=(path.as_posix(),))
        key, raw_value = raw.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            fail("HB008", "Empty SKILL.md frontmatter key", sources=(path.as_posix(),))
        body: list[str] = []
        while i < end and (not lines[i].strip() or lines[i][:1].isspace() or lines[i].lstrip().startswith("#")):
            body.append(lines[i])
            i += 1
        fields.append((key, value, body))
    data: dict[str, Any] = {}
    for key, value, body in fields:
        if key in data:
            fail("HB008", f"Duplicate SKILL.md frontmatter key: {key}", sources=(path.as_posix(),))
        if key not in {"name", "description", "tags"}:
            continue
        if key == "tags":
            if value:
                data[key] = yaml_inline_list(value, path, key) if value.startswith("[") else yaml_scalar(value)
            else:
                items: list[str] = []
                for nested_raw in body:
                    nested = nested_raw.strip()
                    if not nested or nested.startswith("#"):
                        continue
                    if not nested.startswith("- "):
                        fail("HB008", "Skill tags must be a YAML list", sources=(path.as_posix(),))
                    items.append(yaml_scalar(nested[2:]))
                data[key] = items
        elif value.startswith(("|", ">")):
            if not re.fullmatch(r"[>|](?:[+-]?[1-9]?|[1-9][+-]?)", value):
                fail("HB008", f"Invalid block scalar marker for {key}", sources=(path.as_posix(),))
            data[key] = yaml_block_scalar(value, body)
        elif any(line.strip() and not line.lstrip().startswith("#") for line in body):
            fail("HB008", f"{key} must be a scalar", sources=(path.as_posix(),))
        else:
            data[key] = yaml_scalar(value)
    return data


def valid_string_or_string_list(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())) or (
        isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
    )


def validate_codebuddy_agent(path: Path) -> None:
    data = parse_frontmatter_generic(path)
    for key in ("name", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            fail("HB009", f"{path.name} must declare non-empty {key} frontmatter", sources=(path.as_posix(),))
    if "mode" in data and (not isinstance(data["mode"], str) or not data["mode"].strip()):
        fail("HB009", "CodeBuddy agent mode must be a non-empty string", sources=(path.as_posix(),))
    for key in ("tools", "allowedTools", "disallowedTools"):
        if key in data and not valid_string_or_string_list(data[key]):
            fail("HB009", f"CodeBuddy agent {key} must be a string or string list", sources=(path.as_posix(),))


def validate_claude_agent(path: Path) -> dict[str, Any]:
    data = parse_frontmatter_generic(path)
    for key in ("name", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            fail("HB009", f"{path.name} must declare non-empty {key} frontmatter", sources=(path.as_posix(),))
    for key in ("tools", "disallowedTools", "skills"):
        if key in data and not valid_string_or_string_list(data[key]):
            fail("HB009", f"Claude agent {key} must be a string or string list", sources=(path.as_posix(),))
    if "isolation" in data and data["isolation"] != "worktree":
        fail("HB009", "Claude agent isolation must be worktree", sources=(path.as_posix(),))
    if "hooks" in data and not isinstance(data["hooks"], dict):
        fail("HB009", "Claude agent hooks must be a mapping", sources=(path.as_posix(),))
    return data


def validate_claude_rule(path: Path) -> None:
    try:
        first = path.read_text(encoding="utf-8-sig").splitlines()[0]
    except (UnicodeDecodeError, IndexError):
        fail("HB009", "Claude rule must be UTF-8 and non-empty", sources=(path.as_posix(),))
    if first.strip() != "---":
        return
    data = parse_frontmatter_generic(path)
    if "paths" in data and not valid_string_or_string_list(data["paths"]):
        fail("HB009", "Claude rule paths must be a string or string list", sources=(path.as_posix(),))


def parse_frontmatter_generic(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        fail("HB009", "Agent Markdown must be UTF-8", sources=(path.as_posix(),))
    if not lines or lines[0].strip() != "---":
        fail("HB009", "Agent Markdown is missing frontmatter", sources=(path.as_posix(),))
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        fail("HB009", "Agent Markdown frontmatter is not closed", sources=(path.as_posix(),))
    fields: list[tuple[str, str, list[str]]] = []
    i = 1
    while i < end:
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[:1].isspace() or ":" not in raw:
            fail("HB009", f"Unsupported Agent Markdown frontmatter syntax: {raw.strip()}", sources=(path.as_posix(),))
        key, value = raw.split(":", 1)
        body: list[str] = []
        while i < end and (not lines[i].strip() or lines[i][:1].isspace() or lines[i].lstrip().startswith("#")):
            body.append(lines[i])
            i += 1
        fields.append((key.strip(), value.strip(), body))
    data: dict[str, Any] = {}
    for key, value, body in fields:
        if not key or key in data:
            fail("HB009", f"Invalid or duplicate Agent Markdown frontmatter key: {key}", sources=(path.as_posix(),))
        if value.startswith("["):
            data[key] = yaml_inline_list(value, path, key, "HB009")
        elif value.startswith(("|", ">")):
            data[key] = yaml_block_scalar(value, body)
        elif not value and body:
            items: list[str] = []
            list_shaped = True
            for nested_raw in body:
                nested = nested_raw.strip()
                if not nested or nested.startswith("#"):
                    continue
                if not nested.startswith("- "):
                    list_shaped = False
                    break
                items.append(yaml_scalar(nested[2:]))
            data[key] = items if list_shaped else {"__raw__": "\n".join(body)}
        else:
            data[key] = yaml_scalar(value)
    return data


@dataclasses.dataclass
class Manifest:
    path: Path
    name: str
    description: str | None
    agents: list[str]
    skills: list[str]
    tags: list[str]
    providers: list[dict[str, Any]]


@dataclasses.dataclass
class WorkspaceFolder:
    name: str
    path: str
    resolved: Path


@dataclasses.dataclass
class Workspace:
    path: Path
    folders: list[WorkspaceFolder]


@dataclasses.dataclass
class Provider:
    provider_id: str
    root: Path
    source_root: Path
    configured_path: str
    priority: int
    digest: str
    provider_type: str = "folder"
    url: str | None = None
    selector_kind: str | None = None
    selector_value: str | None = None
    commit: str | None = None
    subdir: str | None = None
    command: dict[str, Any] | None = None


@dataclasses.dataclass
class Skill:
    name: str
    description: str
    tags: list[str]
    root: Path
    provider: Provider
    digest: str
    selected_by: str = ""
    matched_tags: list[str] = dataclasses.field(default_factory=list)
    shadowed: list[dict[str, str]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Contribution:
    target: str
    content: bytes
    source: str
    logical_type: str
    merge: str = "plain"
    executable: bool = False
    semantic_key: str | None = None
    risks: list[dict[str, str]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Operation:
    target: str
    content: bytes
    sources: list[str]
    logical_type: str
    operation: str
    executable: bool = False
    semantic_key: str = ""
    risks: list[dict[str, str]] = dataclasses.field(default_factory=list)

    @property
    def digest(self) -> str:
        return sha256_bytes(self.content)


def detect_legacy(root: Path) -> None:
    found = [name for name in LEGACY_NAMES if (root / name).exists() or (root / name).is_symlink()]
    found.extend(path.name for path in root.glob("*.code-workspace.src"))
    if found:
        fail(
            "HB015",
            "Legacy THarness layout detected: " + ", ".join(sorted(set(found))),
            sources=tuple(sorted(set(found))),
            action="Migrate sources to harness-space.json and .harness-builder before building.",
        )


def validate_provider_subdir(value: Any, index: int) -> str:
    subdir = value if value is not None else "."
    if not isinstance(subdir, str) or not subdir.strip():
        fail("HB001", f"skillProviders[{index}].subdir must be a non-empty relative POSIX path")
    subdir_path = Path(subdir)
    if subdir_path.is_absolute() or "\\" in subdir or any(part in {"", ".."} for part in subdir.split("/")):
        fail("HB001", f"skillProviders[{index}].subdir must be a safe relative POSIX path")
    return subdir_path.as_posix()


def validate_provider_command(value: Any, index: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"cwd", "args"} or "args" not in value:
        fail("HB001", f"skillProviders[{index}].command accepts cwd and required args")
    cwd = value.get("cwd", ".")
    if (
        not isinstance(cwd, str)
        or not cwd.strip()
        or Path(cwd).is_absolute()
        or "\\" in cwd
        or any(part in {"", ".."} for part in cwd.split("/"))
    ):
        fail("HB001", f"skillProviders[{index}].command.cwd must be a safe relative POSIX path")
    arguments = value.get("args")
    if (
        not isinstance(arguments, list)
        or not arguments
        or any(not isinstance(argument, str) or not argument or any(ord(char) < 32 for char in argument) for argument in arguments)
    ):
        fail("HB001", f"skillProviders[{index}].command.args must be an array of non-empty strings")
    return {"cwd": Path(cwd).as_posix(), "args": list(arguments)}


def load_manifest(root: Path) -> Manifest:
    path = root / "harness-space.json"
    raw = read_json(path, "HB001", "manifest")
    if not isinstance(raw, dict):
        fail("HB001", "harness-space.json must contain a JSON object", sources=(path.as_posix(),))
    required = {"schema", "name", "agents", "skills", "tags", "skillProviders"}
    missing = sorted(required - raw.keys())
    unknown = sorted(raw.keys() - required - {"description"})
    if missing:
        fail("HB001", "Missing manifest fields: " + ", ".join(missing), sources=(path.as_posix(),))
    if unknown:
        fail("HB001", "Unknown manifest fields: " + ", ".join(unknown), sources=(path.as_posix(),))
    if raw.get("schema") != SPACE_SCHEMA:
        fail("HB001", f"manifest.schema must be {SPACE_SCHEMA}", sources=(path.as_posix(),))
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        fail("HB002", "manifest.name must match ^[a-z][a-z0-9-]*$", sources=(path.as_posix(),))
    agents = require_string_list(raw.get("agents"), "agents", nonempty=True)
    unknown_agents = [agent for agent in agents if agent not in AGENTS]
    if unknown_agents:
        fail("HB001", "Unknown agents: " + ", ".join(unknown_agents), sources=(path.as_posix(),))
    skills = require_string_list(raw.get("skills"), "skills")
    for skill in skills:
        if not NAME_RE.fullmatch(skill):
            fail("HB001", f"Invalid skill name in manifest: {skill}", sources=(path.as_posix(),))
    tags = require_string_list(raw.get("tags"), "tags")
    providers_raw = raw.get("skillProviders")
    if not isinstance(providers_raw, list):
        fail("HB001", "manifest.skillProviders must be an array", sources=(path.as_posix(),))
    providers: list[dict[str, Any]] = []
    seen_provider_specs: set[str] = set()
    for index, item in enumerate(providers_raw):
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            fail("HB001", f"skillProviders[{index}] must be an object with a type", sources=(path.as_posix(),))
        kind = item["type"]
        if kind == "folder":
            allowed = {"type", "path", "subdir", "command"}
            if set(item) - allowed or not {"type", "path"}.issubset(item):
                fail("HB001", f"skillProviders[{index}] folder accepts type, path, optional subdir and command", sources=(path.as_posix(),))
            configured = item.get("path")
            if not isinstance(configured, str) or not configured.strip():
                fail("HB001", f"skillProviders[{index}].path must be a non-empty string", sources=(path.as_posix(),))
            if Path(configured).is_absolute():
                fail("HB001", f"skillProviders[{index}].path must be relative", sources=(path.as_posix(),))
            normalized_subdir = validate_provider_subdir(item.get("subdir"), index)
            command = validate_provider_command(item.get("command"), index)
            normalized_provider_path = Path(os.path.normpath(configured)).as_posix()
            normalized = {"type": kind, "path": os.path.normcase(normalized_provider_path), "subdir": normalized_subdir}
            provider = {"type": kind, "path": configured, "subdir": normalized_subdir}
            if command is not None:
                normalized["command"] = command
                provider["command"] = command
        elif kind == "git":
            allowed = {"type", "url", "branch", "tag", "subdir", "command"}
            if set(item) - allowed or not {"type", "url"}.issubset(item):
                fail(
                    "HB001",
                    f"skillProviders[{index}] git accepts type, url, exactly one of branch/tag, and optional subdir",
                    sources=(path.as_posix(),),
                )
            selectors = [key for key in ("branch", "tag") if key in item]
            if len(selectors) != 1:
                fail("HB001", f"skillProviders[{index}] git requires exactly one of branch or tag", sources=(path.as_posix(),))
            url = item.get("url")
            if not isinstance(url, str) or not url.strip() or any(ord(char) < 32 for char in url):
                fail("HB001", f"skillProviders[{index}].url must be a non-empty string", sources=(path.as_posix(),))
            parsed_url = urlsplit(url)
            if parsed_url.password is not None or (parsed_url.scheme in {"http", "https"} and parsed_url.username is not None):
                fail("HB011", f"skillProviders[{index}].url must not contain credentials", sources=(path.as_posix(),))
            if parsed_url.scheme in {"http", "https"} and (parsed_url.query or parsed_url.fragment):
                fail("HB011", f"skillProviders[{index}].url must not contain query credentials or fragments", sources=(path.as_posix(),))
            selector_kind = selectors[0]
            selector_value = item.get(selector_kind)
            if (
                not isinstance(selector_value, str)
                or not selector_value.strip()
                or selector_value.startswith(("-", "refs/"))
                or selector_value.endswith(("/", ".", ".lock"))
                or ".." in selector_value
                or "//" in selector_value
                or "@{" in selector_value
                or selector_value == "@"
                or "\\" in selector_value
                or any(part.startswith(".") or part.endswith(".lock") for part in selector_value.split("/"))
                or any(char.isspace() or ord(char) < 32 or char in "~^:?*[" for char in selector_value)
            ):
                fail("HB001", f"skillProviders[{index}].{selector_kind} is not a safe Git name", sources=(path.as_posix(),))
            normalized_subdir = validate_provider_subdir(item.get("subdir"), index)
            command = validate_provider_command(item.get("command"), index)
            normalized = {
                "type": kind,
                "url": url,
                selector_kind: selector_value,
                "subdir": normalized_subdir,
            }
            provider = dict(normalized)
            if command is not None:
                normalized["command"] = command
                provider["command"] = command
        else:
            fail("HB006", f"Unsupported provider type: {kind}", sources=(path.as_posix(),))
        spec = canonical_json(normalized)
        if spec in seen_provider_specs:
            fail("HB001", f"Duplicate skill provider at index {index}", sources=(path.as_posix(),))
        seen_provider_specs.add(spec)
        providers.append(provider)
    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        fail("HB001", "manifest.description must be a string", sources=(path.as_posix(),))
    return Manifest(path, name, description, agents, skills, tags, providers)


def load_workspace(root: Path, manifest: Manifest) -> Workspace:
    path = root / f"{manifest.name}.code-workspace"
    if not path.exists():
        fail("HB003", f"workspace not found: {path.name}", sources=(path.as_posix(),))
    raw = read_json(path, "HB004", "workspace")
    if not isinstance(raw, dict) or not isinstance(raw.get("folders"), list) or not raw["folders"]:
        fail("HB004", "workspace.folders must be a non-empty array", sources=(path.as_posix(),))
    folders: list[WorkspaceFolder] = []
    names: set[str] = set()
    resolved_keys: set[str] = set()
    for index, item in enumerate(raw["folders"]):
        if not isinstance(item, dict):
            fail("HB004", f"workspace.folders[{index}] must be an object", sources=(path.as_posix(),))
        name, configured = item.get("name"), item.get("path")
        if not isinstance(name, str) or not name.strip():
            fail("HB004", f"workspace.folders[{index}].name must be non-empty", sources=(path.as_posix(),))
        if name in names:
            fail("HB004", f"Duplicate workspace folder name: {name}", sources=(path.as_posix(),))
        if not isinstance(configured, str) or not configured.strip() or Path(configured).is_absolute():
            fail("HB004", f"workspace folder path must be a non-empty relative path: {name}", sources=(path.as_posix(),))
        resolved = (root / configured).resolve()
        if not resolved.is_dir():
            fail("HB004", f"Workspace folder does not exist: {configured}", sources=(path.as_posix(), configured))
        key = os.path.normcase(str(resolved))
        if key in resolved_keys:
            fail("HB004", f"Duplicate resolved workspace folder path: {configured}", sources=(path.as_posix(),))
        names.add(name)
        resolved_keys.add(key)
        folders.append(WorkspaceFolder(name, Path(configured).as_posix(), resolved))
    return Workspace(path, folders)


def default_space_name(root: Path) -> str:
    """Use the Space directory name when init does not receive --name."""
    return root.name


def init_space(root: Path, requested_name: str | None = None) -> tuple[Manifest, list[str], list[str]]:
    """Create missing required inputs and validate required inputs that already exist."""
    detect_legacy(root)
    manifest_path = root / "harness-space.json"
    created: list[str] = []
    validated: list[str] = []

    if requested_name is not None and not NAME_RE.fullmatch(requested_name):
        fail("HB002", "--name must match ^[a-z][a-z0-9-]*$", sources=(manifest_path.as_posix(),))

    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = load_manifest(root)
        if requested_name is not None and requested_name != manifest.name:
            fail(
                "HB002",
                f"--name {requested_name!r} does not match existing manifest.name {manifest.name!r}",
                sources=(manifest_path.as_posix(),),
            )
        validated.append(manifest_path.name)
        manifest_content: bytes | None = None
    else:
        name = requested_name or default_space_name(root)
        if not NAME_RE.fullmatch(name):
            fail(
                "HB002",
                f"Space directory name {name!r} is not a valid manifest.name; use --name",
                sources=(root.as_posix(),),
                action="Use --name with a lowercase kebab-case name, or rename the Space directory.",
            )
        manifest = Manifest(manifest_path, name, None, list(AGENTS), [], [], [])
        manifest_content = json_bytes(
            {
                "schema": SPACE_SCHEMA,
                "name": name,
                "agents": list(AGENTS),
                "skills": [],
                "tags": [],
                "skillProviders": [],
            }
        )

    workspace_path = root / f"{manifest.name}.code-workspace"
    if workspace_path.exists() or workspace_path.is_symlink():
        load_workspace(root, manifest)
        validated.append(workspace_path.name)
        workspace_content: bytes | None = None
    else:
        workspace_content = json_bytes({"folders": [{"name": "project", "path": "."}]})

    # All existing required inputs have been validated before the first write.
    for path, content, logical_type in (
        (manifest_path, manifest_content, "space-manifest"),
        (workspace_path, workspace_content, "vscode-workspace"),
    ):
        if content is None:
            continue
        atomic_write(root, Operation(path.name, content, ["core:init"], logical_type, "render"))
        created.append(path.name)
    return manifest, created, validated


def tree_digest(root: Path, *, exclude_agent_extensions: bool = False) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return "sha256:" + digest.hexdigest()
    for path in walk_tree(root, exclude_agent_extensions=exclude_agent_extensions):
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        digest.update(rel.encode() + b"\0")
        digest.update(oct(stat.S_IMODE(st.st_mode)).encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def walk_tree(root: Path, *, exclude_agent_extensions: bool = False) -> list[Path]:
    output: list[Path] = []
    if not root.exists():
        return output
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        if exclude_agent_extensions and current_path == root:
            dirs[:] = [name for name in dirs if name != ".harness-agents"]
        dirs[:] = sorted(name for name in dirs if name != ".DS_Store")
        for dirname in list(dirs):
            candidate = current_path / dirname
            if candidate.is_symlink():
                fail("HB011", "Symlinks are not allowed in generated source trees", sources=(candidate.as_posix(),))
        for filename in sorted(files):
            if filename == ".DS_Store":
                continue
            path = current_path / filename
            if path.is_symlink():
                fail("HB011", "Symlinks are not allowed in generated source trees", sources=(path.as_posix(),))
            if not path.is_file():
                fail("HB011", "Unsupported source file kind", sources=(path.as_posix(),))
            output.append(path)
    return output


def provider_cache_root(root: Path) -> Path:
    configured = os.environ.get("HARNESSBUILDER_CACHE_DIR")
    if configured:
        cache = Path(configured).expanduser()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        cache = Path(os.environ["LOCALAPPDATA"]) / "HarnessBuilder" / "Cache"
    elif os.environ.get("XDG_CACHE_HOME"):
        cache = Path(os.environ["XDG_CACHE_HOME"]) / "harnessbuilder"
    else:
        cache = Path.home() / ".cache" / "harnessbuilder"
    try:
        resolved = cache.resolve()
    except (OSError, RuntimeError) as exc:
        fail("HB011", f"Unsafe HarnessBuilder cache path: {exc}")
    if resolved == root or root in resolved.parents:
        fail("HB011", "Git Provider cache must be outside the Harness Space", sources=(str(cache),))
    return resolved


def git_source_url(root: Path, configured: str) -> str:
    parsed = urlsplit(configured)
    is_scp_style = re.match(r"^[^/@:]+@[^:]+:.+$", configured) is not None
    if parsed.scheme or is_scp_style:
        return configured
    return str((root / configured).resolve())


def run_git(arguments: list[str], *, binary: bool = False) -> str | bytes:
    executable = shutil.which("git")
    if executable is None:
        fail("HB005", "Git Provider requires the git executable", action="Install Git or remove the Git Provider.")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail("HB005", f"Git Provider command failed: {exc}", action="Verify Git availability and the Provider URL.")
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace") if binary else completed.stderr
        detail = (stderr or "Git command failed").strip().splitlines()[-1]
        fail("HB005", f"Git Provider resolution failed: {detail}", action="Verify the URL, branch/tag, credentials, and cache state.")
    return completed.stdout


def locked_git_provider(
    previous: dict[str, Any] | None,
    provider_id: str,
    url: str,
    selector_kind: str,
    selector_value: str,
    subdir: str,
) -> dict[str, Any] | None:
    if previous is None:
        return None
    for item in previous.get("providers", []):
        if (
            not isinstance(item, dict)
            or item.get("id") != provider_id
            or item.get("type") != "git"
            or item.get("url") != url
            or item.get(selector_kind) != selector_value
            or item.get("subdir") != subdir
        ):
            continue
        commit = item.get("commit")
        if (
            isinstance(commit, str)
            and re.fullmatch(r"[0-9a-f]{40,64}", commit)
            and valid_digest(item.get("digest"))
        ):
            return item
    return None


def extract_git_snapshot(archive: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=str(destination.parent)))
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle:
                name = member.name.rstrip("/")
                if not name:
                    continue
                parts = Path(name).parts
                if member.name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                    fail("HB011", f"Unsafe path in Git Provider archive: {member.name}")
                collision_key = unicodedata.normalize("NFC", name).casefold()
                if collision_key in seen:
                    fail("HB011", f"Portable path collision in Git Provider archive: {member.name}")
                seen.add(collision_key)
                target = temporary.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    fail("HB011", f"Git Provider archives may contain only files and directories: {member.name}")
                source = bundle.extractfile(member)
                if source is None:
                    fail("HB011", f"Cannot read Git Provider archive member: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        try:
            temporary.rename(destination)
        except FileExistsError:
            shutil.rmtree(temporary)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def load_git_provider(
    root: Path,
    item: dict[str, Any],
    priority: int,
    previous: dict[str, Any] | None,
    offline: bool,
) -> Provider:
    url = item["url"]
    selector_kind = "branch" if "branch" in item else "tag"
    selector_value = item[selector_kind]
    subdir = item.get("subdir", ".")
    identity_value: dict[str, Any] = {
        "type": "git",
        "url": url,
        selector_kind: selector_value,
        "subdir": subdir,
    }
    if item.get("command") is not None:
        identity_value["command"] = item["command"]
    identity = canonical_json(identity_value)
    identity_hash = hashlib.sha256(identity.encode()).hexdigest()
    provider_id = "git:" + identity_hash[:16]
    cache = provider_cache_root(root) / "git" / hashlib.sha256(url.encode()).hexdigest()
    mirror = cache / "repository.git"
    transport_url = git_source_url(root, url)
    if not mirror.is_dir():
        if offline:
            fail(
                "HB005",
                f"Offline Git Provider cache is missing: {url}",
                sources=(url,),
                action="Run an online build once to populate the Git Provider cache.",
            )
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.parent / (cache.name + f".tmp-{os.getpid()}-{time.time_ns()}")
        temporary.mkdir(parents=True)
        try:
            run_git(["clone", "--mirror", "--", transport_url, str(temporary / "repository.git")])
            try:
                temporary.rename(cache)
            except FileExistsError:
                shutil.rmtree(temporary)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    elif not offline:
        run_git(["--git-dir", str(mirror), "remote", "set-url", "origin", transport_url])
        run_git(
            [
                "--git-dir",
                str(mirror),
                "fetch",
                "--prune",
                "--tags",
                "origin",
                "+refs/heads/*:refs/heads/*",
                "+refs/tags/*:refs/tags/*",
            ]
        )
    locked = locked_git_provider(previous, provider_id, url, selector_kind, selector_value, subdir)
    if offline and locked is None:
        fail(
            "HB005",
            f"Offline Git Provider has no matching locked commit: {url}",
            sources=(url,),
            action="Run an online build after configuring this Git Provider, then retry with --offline.",
        )
    commit = locked["commit"] if offline and locked is not None else None
    if commit is not None:
        run_git(["--git-dir", str(mirror), "cat-file", "-e", commit + "^{commit}"])
    else:
        git_ref = f"refs/heads/{selector_value}" if selector_kind == "branch" else f"refs/tags/{selector_value}"
        resolved = run_git(["--git-dir", str(mirror), "rev-parse", "--verify", git_ref + "^{commit}"])
        assert isinstance(resolved, str)
        commit = resolved.strip()
        if re.fullmatch(r"[0-9a-f]{40,64}", commit) is None:
            fail("HB005", f"Git Provider returned an invalid commit for {selector_kind} {selector_value}")
    command = item.get("command")
    subdir_hash = hashlib.sha256(subdir.encode()).hexdigest()[:16]
    source_snapshot = cache / "snapshots" / commit / ("full" if command is not None else subdir_hash)
    if not source_snapshot.is_dir():
        treeish = commit if command is not None or subdir == "." else f"{commit}:{subdir}"
        archive = run_git(["--git-dir", str(mirror), "archive", "--format=tar", treeish], binary=True)
        assert isinstance(archive, bytes)
        extract_git_snapshot(archive, source_snapshot)
    snapshot = source_snapshot / subdir if command is not None and subdir != "." else source_snapshot
    if not snapshot.is_dir():
        fail("HB005", f"Git Provider subdir is not a directory: {subdir}", sources=(url, subdir))
    snapshot_digest = tree_digest(snapshot)
    if offline and locked is not None and snapshot_digest != locked["digest"]:
        fail(
            "HB010",
            f"Locked Git Provider cache digest changed: {url}",
            sources=(url,),
            action="Delete the affected cache entry and run an online build to restore the immutable snapshot.",
        )
    configured_path = f"git:{url}#{selector_kind}={selector_value}:{subdir}"
    return Provider(
        provider_id,
        snapshot,
        source_snapshot,
        configured_path,
        priority,
        snapshot_digest,
        "git",
        url,
        selector_kind,
        selector_value,
        commit,
        subdir,
        command,
    )


def load_providers(
    root: Path,
    manifest: Manifest,
    previous: dict[str, Any] | None = None,
    offline: bool = False,
) -> list[Provider]:
    providers: list[Provider] = []
    seen_folder_roots: dict[str, str] = {}
    generated_roots = [root / name for name in (".codex", ".cursor", ".codebuddy", ".claude", ".agents")]
    specs = [{"type": "folder", "path": ".harness-builder/skills", "subdir": "."}, *manifest.providers]
    for priority, item in enumerate(specs):
        if item["type"] == "git":
            providers.append(load_git_provider(root, item, priority, previous, offline))
            continue
        configured = item["path"]
        provider_id = "space-local" if priority == 0 else f"folder:{configured}"
        subdir = item.get("subdir", ".")
        command = item.get("command")
        try:
            source_root = (root / configured).resolve()
            provider_root = (source_root / subdir).resolve()
        except (OSError, RuntimeError) as exc:
            fail("HB011", f"Unsafe Skill provider path: {configured}: {exc}", sources=(configured,))
        if provider_id == "space-local" and not provider_root.exists():
            providers.append(Provider(provider_id, provider_root, source_root, configured, priority, tree_digest(provider_root), subdir=subdir))
            continue
        if not provider_root.is_dir():
            fail("HB005", f"Skill provider directory not found: {configured}", sources=(configured,))
        resolved_key = os.path.normcase(str(provider_root))
        if resolved_key in seen_folder_roots:
            fail(
                "HB001",
                f"Folder Providers resolve to the same directory: {seen_folder_roots[resolved_key]} and {configured}",
                sources=(seen_folder_roots[resolved_key], configured),
            )
        seen_folder_roots[resolved_key] = configured
        for generated in generated_roots:
            generated_resolved = generated.resolve()
            if provider_root == generated_resolved or generated_resolved in provider_root.parents:
                fail("HB011", f"Provider cannot be inside generated target: {configured}", sources=(configured,))
        providers.append(
            Provider(
                provider_id,
                provider_root,
                source_root,
                configured,
                priority,
                tree_digest(provider_root),
                subdir=subdir,
                command=command,
            )
        )
    return providers


def read_skill(provider: Provider, directory: Path) -> Skill:
    skill_md = directory / "SKILL.md"
    meta = parse_frontmatter(skill_md)
    name = meta.get("name")
    description = meta.get("description")
    tags = meta.get("tags", [])
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        fail("HB008", "Skill name must match ^[a-z][a-z0-9-]*$", sources=(skill_md.as_posix(),))
    if name != directory.name:
        fail("HB008", f"Skill name must match directory name: expected {directory.name}, got {name}", sources=(skill_md.as_posix(),))
    if not isinstance(description, str) or not description.strip():
        fail("HB008", "Skill description must be non-empty", sources=(skill_md.as_posix(),))
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        fail("HB008", "Skill tags must be an array of non-empty strings", sources=(skill_md.as_posix(),))
    if len(set(tags)) != len(tags):
        fail("HB008", "Skill tags must not contain duplicates", sources=(skill_md.as_posix(),))
    validate_agent_namespace(directory / ".harness-agents", f"Skill {name}")
    return Skill(name, description, list(tags), directory, provider, tree_digest(directory))


def validate_agent_namespace(path: Path, label: str) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir():
        fail("HB009", f"{label} agent namespace must be a real directory", sources=(path.as_posix(),))
    for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
        if child.name not in AGENTS:
            fail(
                "HB009",
                f"Unknown Agent namespace {child.name} in {label}",
                sources=(child.as_posix(),),
                action="Use one of: " + ", ".join(AGENTS),
            )
        if child.is_symlink() or not child.is_dir():
            fail("HB009", f"Agent namespace must be a real directory: {child.name}", sources=(child.as_posix(),))


def resolve_skills(providers: list[Provider], manifest: Manifest, warnings: list[Diagnostic]) -> tuple[list[Skill], dict[str, Skill]]:
    candidates: dict[str, list[Skill]] = {}
    for provider in providers:
        if not provider.root.exists():
            continue
        for directory in sorted(provider.root.iterdir(), key=lambda p: p.name):
            if not directory.is_dir() or directory.is_symlink():
                continue
            if not (directory / "SKILL.md").is_file():
                fail("HB008", f"Skill provider child is missing SKILL.md: {directory.name}", sources=(directory.as_posix(),))
            skill = read_skill(provider, directory)
            candidates.setdefault(skill.name, []).append(skill)
    resolved: dict[str, Skill] = {}
    for name, choices in candidates.items():
        winner = choices[0]
        winner.shadowed = [
            {"provider": choice.provider.provider_id, "path": f"{choice.provider.configured_path}/{name}"}
            for choice in choices[1:]
        ]
        if winner.shadowed:
            warnings.append(
                Diagnostic(
                    "warn",
                    "HBW001",
                    f"Skill {name} shadows {len(winner.shadowed)} lower-priority candidate(s)",
                    tuple(item["path"] for item in winner.shadowed),
                )
            )
        resolved[name] = winner
    local_names = {
        name for name, skill in resolved.items() if skill.provider.provider_id == "space-local"
    }
    explicit: list[str] = []
    for name in manifest.skills:
        if name not in resolved:
            fail("HB007", f"Selected skill not found: {name}", sources=(manifest.path.as_posix(),))
        explicit.append(name)
    selected_names = set(local_names) | set(explicit)
    tag_names: set[str] = set()
    tag_set = set(manifest.tags)
    for name, skill in resolved.items():
        if name not in selected_names and tag_set.intersection(skill.tags):
            tag_names.add(name)
            selected_names.add(name)
    order = explicit + sorted(local_names - set(explicit)) + sorted(tag_names)
    result: list[Skill] = []
    for name in order:
        skill = resolved[name]
        if name in explicit:
            skill.selected_by = "skills"
        elif name in local_names:
            skill.selected_by = "space-local"
        else:
            skill.selected_by = "tags"
        skill.matched_tags = sorted(tag_set.intersection(skill.tags))
        result.append(skill)
    return result, resolved


def workspace_rule(manifest: Manifest, workspace: Workspace) -> str:
    lines = [
        "# HarnessBuilder Workspace",
        "",
        f"Harness Space: `{manifest.name}`",
        f"Workspace: `{workspace.path.name}`",
        "",
        "## Folders (declared order)",
        "",
    ]
    for folder in workspace.folders:
        topology = "same directory as Harness Space" if folder.path == "." else "directory-decoupled"
        lines.append(f"- `{folder.name}`: `{folder.path}` ({topology})")
    lines.extend(
        [
            "",
            "Folder order does not imply primary/reference, writable/read-only, validation, or commit boundaries.",
            "The .code-workspace file is the source of truth; this file is a generated projection.",
            "Do not edit platform targets or .harness-builder state directly.",
            "",
        ]
    )
    return "\n".join(lines)


class Planner:
    def __init__(self, root: Path, manifest: Manifest, workspace: Workspace, skills: list[Skill], warnings: list[Diagnostic]):
        self.root = root
        self.manifest = manifest
        self.workspace = workspace
        self.skills = skills
        self.warnings = warnings
        self.contributions: dict[str, list[Contribution]] = {}
        self.case_targets: dict[str, str] = {}
        self.semantic_targets: dict[str, str] = {}

    def add(self, contribution: Contribution) -> None:
        target = normalize_target(contribution.target)
        key = unicodedata.normalize("NFC", target).casefold()
        existing = self.case_targets.get(key)
        if existing is not None and existing != target:
            fail("HB010", f"Portable target path collision: {existing} vs {target}", target=target)
        self.case_targets[key] = target
        contribution.target = target
        self.contributions.setdefault(target, []).append(contribution)

    def build(self) -> list[Operation]:
        rule = workspace_rule(self.manifest, self.workspace).encode()
        self.add(Contribution(".harness-builder/generated/workspace-rule.md", rule, "core:workspace", "workspace-rule"))
        for agent in self.manifest.agents:
            self.install_common_skills(agent)
            self.add_workspace_projection(agent, rule)
            sources: list[tuple[Path, str]] = []
            space_source = self.root / ".harness-builder" / "agents" / agent
            if space_source.exists():
                sources.append((space_source, f"space:agents/{agent}"))
            for skill in self.skills:
                skill_source = skill.root / ".harness-agents" / agent
                if skill_source.exists():
                    sources.append((skill_source, f"skill:{skill.name}"))
            for source_root, source_id in sources:
                if not source_root.is_dir() or source_root.is_symlink():
                    fail("HB009", "Agent source root must be a real directory", sources=(source_root.as_posix(),))
                validate_agent_source_directories(agent, source_root)
                self.scan_agent_source(agent, source_root, source_id)
        return self.finalize()

    def install_common_skills(self, agent: str) -> None:
        destination = {
            "codex": ".agents/skills",
            "cursor": ".cursor/skills",
            "codebuddy": ".codebuddy/skills",
            "claude-code": ".claude/skills",
        }[agent]
        for skill in self.skills:
            for path in walk_tree(skill.root, exclude_agent_extensions=True):
                relative = path.relative_to(skill.root).as_posix()
                target = f"{destination}/{skill.name}/{relative}"
                executable = bool(path.stat().st_mode & stat.S_IXUSR)
                self.add(
                    Contribution(
                        target,
                        path.read_bytes(),
                        f"skill:{skill.name}:{relative}",
                        "common-skill",
                        executable=executable,
                    )
                )

    def add_workspace_projection(self, agent: str, rule: bytes) -> None:
        if agent == "codex":
            self.add(Contribution("AGENTS.md", rule, "core:workspace", "project-instructions", "concat"))
        elif agent == "cursor":
            prefix = b"---\ndescription: HarnessBuilder workspace folder inventory.\nalwaysApply: true\n---\n\n"
            self.add(Contribution(".cursor/rules/harnessbuilder-workspace.mdc", prefix + rule, "core:workspace", "workspace-rule"))
        elif agent == "codebuddy":
            self.add(Contribution(".codebuddy/rules/harnessbuilder-workspace.md", rule, "core:workspace", "workspace-rule"))
        else:
            self.add(Contribution(".claude/rules/harnessbuilder-workspace.md", rule, "core:workspace", "workspace-rule"))

    def scan_agent_source(self, agent: str, source_root: Path, source_id: str) -> None:
        for path in walk_tree(source_root):
            relative = path.relative_to(source_root).as_posix()
            content = path.read_bytes()
            executable = bool(path.stat().st_mode & stat.S_IXUSR)
            target, logical_type, merge = classify_agent_path(agent, relative, path)
            if logical_type == "claude-agent":
                agent_meta = validate_claude_agent(path)
                references = agent_meta.get("skills", [])
                if isinstance(references, str):
                    references = [item.strip() for item in references.split(",") if item.strip()]
                selected_names = {item.name for item in self.skills}
                missing = sorted(set(references) - selected_names) if isinstance(references, list) else []
                if missing:
                    fail(
                        "HB009",
                        "Claude agent references unselected or missing Skills: " + ", ".join(missing),
                        sources=(path.as_posix(),),
                        semantic_key="skills",
                    )
            semantic_key = agent_semantic_key(agent, relative, path)
            risks: list[dict[str, str]] = []
            if semantic_key is not None:
                previous_target = self.semantic_targets.get(semantic_key)
                if previous_target is not None and previous_target != target:
                    fail(
                        "HB010",
                        f"Conflicting agent semantic key {semantic_key}: {previous_target} vs {target}",
                        sources=(f"{source_id}:{relative}",),
                        target=target,
                        semantic_key=semantic_key,
                    )
                self.semantic_targets[semantic_key] = target
            if agent == "claude-code" and relative.startswith(".claude/commands/"):
                self.warnings.append(
                    Diagnostic(
                        "warn",
                        "HBW002",
                        f"Claude Code custom command is a compatibility surface; prefer a Skill: {relative}",
                        (f"{source_id}:{relative}",),
                        target,
                    )
                )
            if merge == "json":
                parsed_json = parse_json_document(content, path)
                lint_secrets(parsed_json, f"{source_id}:{relative}")
                lint_embedded_command_secrets(parsed_json, f"{source_id}:{relative}")
                validate_agent_json(logical_type, parsed_json, path)
                risks = command_risks(parsed_json, f"{source_id}:{relative}")
            elif merge == "toml":
                parse_toml_document(content, path)
            elif logical_type == "codex-rule":
                risks = codex_rule_risks(content, f"{source_id}:{relative}")
            for risk in risks:
                if risk["kind"] in {"allow-policy", "shell-wrapper", "network-command", "external-absolute-path"}:
                    self.warnings.append(
                        Diagnostic(
                            "warn",
                            "HBW003",
                            f"Review {risk['kind']} in {relative}",
                            (risk["source"],),
                            target,
                            risk.get("semanticKey"),
                            "Review and narrow this automatically generated security surface.",
                        )
                    )
            self.add(
                Contribution(
                    target,
                    content,
                    f"{source_id}:{relative}",
                    logical_type,
                    merge,
                    executable,
                    semantic_key,
                    risks,
                )
            )

    def finalize(self) -> list[Operation]:
        operations: list[Operation] = []
        for target, contributions in sorted(self.contributions.items()):
            merge_types = {item.merge for item in contributions}
            if len(merge_types) != 1:
                fail("HB010", f"Incompatible contributions for {target}", sources=(item.source for item in contributions), target=target)
            merge = contributions[0].merge
            if merge == "plain":
                digests = {sha256_bytes(item.content) for item in contributions}
                if len(digests) != 1:
                    fail("HB010", f"Conflicting generated target: {target}", sources=(item.source for item in contributions), target=target)
                content = contributions[0].content
                operation = "copy" if not contributions[0].source.startswith("core:") else "render"
            elif merge == "concat":
                content = render_instruction_document(target, contributions)
                operation = "merge-document"
            elif merge == "json":
                merged: Any = {}
                for item in contributions:
                    value = parse_json_document(item.content, Path(item.source))
                    lint_secrets(value, item.source)
                    merged = semantic_merge(merged, value, target, item.source)
                content = json_bytes(merged)
                operation = "merge-document"
            elif merge == "toml":
                merged = {}
                for item in contributions:
                    value = parse_toml_document(item.content, Path(item.source))
                    if target == ".codex/config.toml":
                        lint_codex_project_config(value, item.source)
                    lint_secrets(value, item.source)
                    merged = semantic_merge(merged, value, target, item.source)
                content = render_toml(merged).encode()
                operation = "merge-document"
            else:
                raise AssertionError(merge)
            operations.append(
                Operation(
                    target,
                    content,
                    [item.source for item in contributions],
                    contributions[0].logical_type,
                    operation,
                    any(item.executable for item in contributions),
                    next((item.semantic_key for item in contributions if item.semantic_key), f"target:{target.casefold()}"),
                    [risk for item in contributions for risk in item.risks],
                )
            )
        return operations


def validate_agent_source_directories(agent: str, source_root: Path) -> None:
    surfaces = {
        "codex": (".codex/rules", ".codex/hooks"),
        "cursor": (".cursor/rules", ".cursor/commands"),
        "codebuddy": (".codebuddy/commands", ".codebuddy/agents", ".codebuddy/hooks"),
        "claude-code": (".claude/rules", ".claude/commands", ".claude/agents", ".claude/hooks"),
    }[agent]
    platform_root = {
        "codex": ".codex",
        "cursor": ".cursor",
        "codebuddy": ".codebuddy",
        "claude-code": ".claude",
    }[agent]
    for current, dirs, _ in os.walk(source_root, followlinks=False):
        current_path = Path(current)
        for name in dirs:
            path = current_path / name
            relative = path.relative_to(source_root).as_posix()
            if path.is_symlink():
                fail("HB011", "Symlinks are not allowed in Agent source trees", sources=(path.as_posix(),))
            allowed = relative == platform_root or any(relative == surface or relative.startswith(surface + "/") for surface in surfaces)
            if not allowed:
                fail(
                    "HB009",
                    f"Unsupported {agent} native directory: {relative}",
                    sources=(path.as_posix(),),
                    action="Use a supported path from the agent adapter specification.",
                )


def normalize_target(target: str) -> str:
    path = Path(target)
    if path.is_absolute() or not target or any(part in ("", ".", "..") for part in path.parts):
        fail("HB011", f"Unsafe generated target: {target}", target=target)
    normalized = path.as_posix()
    reserved = {"con", "prn", "aux", "nul"} | {f"com{index}" for index in range(1, 10)} | {f"lpt{index}" for index in range(1, 10)}
    for part in path.parts:
        portable_name = part.rstrip(" .")
        stem = portable_name.split(".", 1)[0].casefold()
        if (
            portable_name != part
            or stem in reserved
            or any(character in part for character in '<>:"|?*\\')
            or any(ord(character) < 32 for character in part)
        ):
            fail("HB011", f"Generated target is not portable: {target}", target=target)
    forbidden = ("harness-space.json",)
    if normalized in forbidden or normalized.endswith(".code-workspace"):
        fail("HB011", f"Generated target points to Human-owned input: {normalized}", target=normalized)
    if normalized.startswith(".harness-builder/agents/") or normalized.startswith(".harness-builder/skills/"):
        fail("HB011", f"Generated target points to Builder source: {normalized}", target=normalized)
    return normalized


def classify_agent_path(agent: str, relative: str, source_path: Path) -> tuple[str, str, str]:
    if agent == "codex":
        if relative == "AGENTS.md":
            return "AGENTS.md", "project-instructions", "concat"
        if relative == ".codex/config.toml":
            return relative, "codex-config", "toml"
        if relative == ".codex/hooks.json":
            return relative, "codex-hooks", "json"
        if relative.startswith(".codex/rules/") and relative.endswith(".rules"):
            return relative, "codex-rule", "plain"
        if relative.startswith(".codex/hooks/"):
            return relative, "codex-hook-file", "plain"
        if relative.startswith(".codex/commands/"):
            fail("HB009", "Codex commands are unsupported; use a Skill", sources=(source_path.as_posix(),))
    elif agent == "cursor":
        if relative.startswith(".cursor/rules/") and relative.endswith(".mdc"):
            validate_cursor_rule(source_path)
            return relative, "cursor-rule", "plain"
        if relative.startswith(".cursor/commands/") and relative.endswith(".md"):
            return relative, "cursor-command", "plain"
    elif agent == "codebuddy":
        if relative.startswith(".codebuddy/commands/") and relative.endswith(".md"):
            return relative, "codebuddy-command", "plain"
        if relative.startswith(".codebuddy/agents/") and relative.endswith(".md"):
            validate_codebuddy_agent(source_path)
            return relative, "codebuddy-agent", "plain"
        if relative == ".codebuddy/settings.json":
            return relative, "codebuddy-settings", "json"
        if relative == ".codebuddy/mcp.json":
            return relative, "codebuddy-mcp", "json"
        if relative.startswith(".codebuddy/hooks/"):
            return relative, "codebuddy-hook-file", "plain"
        if relative.startswith(".codebuddy/rules/"):
            fail("HB009", "CodeBuddy rules are gated until a client fixture locks the schema", sources=(source_path.as_posix(),))
    elif agent == "claude-code":
        if relative == "CLAUDE.md":
            return relative, "project-instructions", "concat"
        if relative.startswith(".claude/rules/") and relative.endswith(".md"):
            validate_claude_rule(source_path)
            return relative, "claude-rule", "plain"
        if relative.startswith(".claude/commands/") and relative.endswith(".md"):
            return relative, "claude-command", "plain"
        if relative.startswith(".claude/agents/") and relative.endswith(".md"):
            validate_claude_agent(source_path)
            return relative, "claude-agent", "plain"
        if relative == ".claude/settings.json":
            return relative, "claude-settings", "json"
        if relative == ".mcp.json":
            return relative, "claude-mcp", "json"
        if relative.startswith(".claude/hooks/"):
            return relative, "claude-hook-file", "plain"
    fail(
        "HB009",
        f"Unsupported {agent} native artifact: {relative}",
        sources=(source_path.as_posix(),),
        action="Use a supported path from the agent adapter specification.",
    )


def agent_semantic_key(agent: str, relative: str, source_path: Path) -> str | None:
    if agent == "cursor" and relative.startswith(".cursor/commands/") and relative.endswith(".md"):
        return f"cursor:command:{Path(relative).stem.casefold()}"
    if agent == "codebuddy" and relative.startswith(".codebuddy/commands/") and relative.endswith(".md"):
        command = Path(relative).relative_to(".codebuddy/commands").with_suffix("").as_posix().casefold()
        return f"codebuddy:command:{command}"
    if agent == "claude-code" and relative.startswith(".claude/commands/") and relative.endswith(".md"):
        command = Path(relative).relative_to(".claude/commands").with_suffix("").as_posix().casefold()
        return f"claude-code:command:{command}"
    if agent == "codebuddy" and relative.startswith(".codebuddy/agents/") and relative.endswith(".md"):
        return f"codebuddy:agent:{parse_frontmatter_generic(source_path).get('name', '').casefold()}"
    if agent == "claude-code" and relative.startswith(".claude/agents/") and relative.endswith(".md"):
        return f"claude-code:agent:{parse_frontmatter_generic(source_path).get('name', '').casefold()}"
    return None


def validate_cursor_rule(path: Path) -> None:
    data = parse_frontmatter_generic(path)
    if not any(key in data and str(data[key]).strip() for key in ("description", "alwaysApply", "globs")):
        fail("HB009", "Cursor rule must declare description, alwaysApply, or globs", sources=(path.as_posix(),))


def parse_json_document(content: bytes, source: Path) -> Any:
    try:
        value = json.loads(content.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("HB009", f"Invalid JSON agent source: {exc}", sources=(source.as_posix(),))
    if not isinstance(value, dict):
        fail("HB009", "Agent JSON document must contain an object", sources=(source.as_posix(),))
    return value


def require_hook_mapping(value: Any, source: Path, *, codex: bool = False) -> None:
    hooks = value.get("hooks") if isinstance(value, dict) else None
    if not isinstance(hooks, dict):
        fail("HB009", "Hook document must contain a hooks object", sources=(source.as_posix(),))
    for event, groups in hooks.items():
        if not isinstance(event, str) or not event or not isinstance(groups, list):
            fail("HB009", f"Hook event {event!r} must contain a list", sources=(source.as_posix(),))
        for group in groups:
            if not isinstance(group, dict):
                fail("HB009", f"Hook event {event} contains a non-object group", sources=(source.as_posix(),))
            if codex:
                matcher = group.get("matcher")
                handlers = group.get("hooks")
                if matcher is not None and not isinstance(matcher, str):
                    fail("HB009", f"Codex hook matcher for {event} must be a string", sources=(source.as_posix(),))
                if not isinstance(handlers, list) or not handlers:
                    fail("HB009", f"Codex hook group for {event} must contain hooks", sources=(source.as_posix(),))
            else:
                handlers = group.get("hooks") if "hooks" in group else [group]
            for handler in handlers:
                if not isinstance(handler, dict) or not isinstance(handler.get("command"), str) or not handler["command"].strip():
                    fail("HB009", f"Hook handler for {event} must contain a command", sources=(source.as_posix(),))
                if codex and handler.get("type") != "command":
                    fail("HB009", f"Codex hook handler for {event} must use type=command", sources=(source.as_posix(),))
                timeout = handler.get("timeout")
                if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0):
                    fail("HB009", f"Hook timeout for {event} must be positive", sources=(source.as_posix(),))


def contains_value(value: Any, expected: str) -> bool:
    if isinstance(value, dict):
        return any(contains_value(child, expected) for child in value.values())
    if isinstance(value, list):
        return any(contains_value(child, expected) for child in value)
    return value == expected


def validate_mcp_document(value: dict[str, Any], source: Path) -> None:
    servers = value.get("mcpServers")
    if not isinstance(servers, dict):
        fail("HB009", "MCP document must contain an mcpServers object", sources=(source.as_posix(),))
    for name, server in servers.items():
        if not isinstance(name, str) or not name or not isinstance(server, dict):
            fail("HB009", "MCP servers must be named objects", sources=(source.as_posix(),))
        if not any(isinstance(server.get(key), str) and server[key].strip() for key in ("command", "url", "type")):
            fail("HB009", f"MCP server {name} must declare command, url, or type", sources=(source.as_posix(),))


def validate_agent_json(logical_type: str, value: dict[str, Any], source: Path) -> None:
    if logical_type == "codex-hooks":
        require_hook_mapping(value, source, codex=True)
    elif logical_type in {"codebuddy-settings", "claude-settings"}:
        if logical_type == "claude-settings" and contains_value(value, "bypassPermissions"):
            fail(
                "HB011",
                "Claude project settings must not enable bypassPermissions",
                sources=(source.as_posix(),),
                semantic_key="permissions.defaultMode",
                action="Use a reviewed project permission mode instead.",
            )
        if "hooks" in value:
            require_hook_mapping(value, source)
    elif logical_type in {"codebuddy-mcp", "claude-mcp"}:
        validate_mcp_document(value, source)


def command_risks(value: Any, source: str, path: str = "", matcher: str = "") -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    if isinstance(value, dict):
        current_matcher = value.get("matcher") if isinstance(value.get("matcher"), str) else matcher
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "command" and isinstance(child, str):
                risk = "automatic-command"
                if re.search(r"(?:^|\s)(?:bash|sh)\s+-c(?:\s|$)|(?:^|\s)(?:cmd|powershell)(?:\.exe)?\s+/(?:c|C)", child):
                    risk = "shell-wrapper"
                elif re.search(r"https?://", child):
                    risk = "network-command"
                elif re.search(r"(?:^|\s)/(?:[^\s]+/)+[^\s]+", child):
                    risk = "external-absolute-path"
                item = {"kind": risk, "source": source, "semanticKey": child_path, "command": child}
                if current_matcher:
                    item["matcher"] = current_matcher
                risks.append(item)
            risks.extend(command_risks(child, source, child_path, current_matcher))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            risks.extend(command_risks(child, source, f"{path}[{index}]", matcher))
    return risks


def lint_embedded_command_secrets(value: Any, source: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "command" and isinstance(child, str):
                patterns = (
                    r"(?i)\bbearer\s+(?!\$\{|\$[A-Za-z_])[^\s'\"]+",
                    r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*(?!\$\{|\$[A-Za-z_])[^\s'\"]+",
                    r"(?i)\bauthorization\s*[:=]\s*(?!bearer\b)(?!\$\{|\$[A-Za-z_])[^\s'\"]+",
                )
                if any(re.search(pattern, child) for pattern in patterns):
                    fail("HB011", "Secret literal is forbidden in hook command", sources=(source,), semantic_key="command")
            lint_embedded_command_secrets(child, source)
    elif isinstance(value, list):
        for child in value:
            lint_embedded_command_secrets(child, source)


def codex_rule_risks(content: bytes, source: str) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        fail("HB009", "Codex rule must be UTF-8", sources=(source,))
    risks = [{"kind": "experimental-platform-surface", "source": source, "semanticKey": "codex.rules"}]
    if re.search(r"decision\s*=\s*[\"']allow[\"']", text):
        risks.append({"kind": "allow-policy", "source": source, "semanticKey": "codex.rules.decision"})
    if re.search(r"(?:bash|sh|cmd|powershell)(?:\.exe)?[\"']?\s*,?\s*[\"']?(?:-c|/c)", text, re.IGNORECASE):
        risks.append({"kind": "shell-wrapper", "source": source, "semanticKey": "codex.rules.pattern"})
    return risks


def _toml_strip_comments(text: str) -> str:
    output: list[str] = []
    quote: str | None = None
    triple = False
    escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if quote is not None:
            output.append(char)
            if quote == '"' and escaped:
                escaped = False
            elif quote == '"' and char == "\\":
                escaped = True
            elif triple and text.startswith(quote * 3, i):
                output.extend((quote, quote))
                quote = None
                triple = False
                i += 2
            elif not triple and char == quote:
                quote = None
        elif text.startswith('"""', i) or text.startswith("'''", i):
            output.extend((char, char, char))
            quote = char
            triple = True
            i += 2
        elif char in ('"', "'"):
            output.append(char)
            quote = char
        elif char == "#":
            newline = text.find("\n", i)
            if newline < 0:
                break
            output.append("\n")
            i = newline
        else:
            output.append(char)
        i += 1
    return "".join(output)


def _toml_scan(text: str, delimiter: str | None = None) -> tuple[list[str], bool]:
    """Split at a top-level delimiter and report whether the TOML expression is complete."""
    text = _toml_strip_comments(text)
    parts: list[str] = []
    start = 0
    square = curly = 0
    quote: str | None = None
    triple = False
    escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if quote is not None:
            if quote == '"' and escaped:
                escaped = False
            elif quote == '"' and char == "\\":
                escaped = True
            elif triple and text.startswith(quote * 3, i):
                quote = None
                triple = False
                i += 2
            elif not triple and char == quote:
                quote = None
        elif text.startswith('"""', i) or text.startswith("'''", i):
            quote = char
            triple = True
            i += 2
        elif char in ('"', "'"):
            quote = char
        elif char == "[":
            square += 1
        elif char == "]":
            square -= 1
        elif char == "{":
            curly += 1
        elif char == "}":
            curly -= 1
        elif delimiter is not None and char == delimiter and square == 0 and curly == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    if delimiter is not None:
        parts.append(text[start:].strip())
    complete = quote is None and square == 0 and curly == 0
    return parts, complete


def _toml_key_parts(text: str) -> list[str]:
    parts, complete = _toml_scan(text, ".")
    if not complete or not parts or any(not part for part in parts):
        raise ValueError("invalid dotted key")
    result: list[str] = []
    for part in parts:
        if part.startswith('"'):
            value = json.loads(part)
            if not isinstance(value, str):
                raise ValueError("invalid quoted key")
            result.append(value)
        elif part.startswith("'") and part.endswith("'") and len(part) >= 2:
            result.append(part[1:-1])
        elif BARE_TOML_KEY_RE.fullmatch(part):
            result.append(part)
        else:
            raise ValueError("invalid key")
    return result


def _toml_parse_value(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ValueError("missing value")
    if text.startswith(('"""', "'''")):
        marker = text[:3]
        if not text.endswith(marker) or len(text) < 6:
            raise ValueError("unterminated multiline string")
        body = text[3:-3]
        if body.startswith("\n"):
            body = body[1:]
        if marker == "'''":
            return body
        return json.loads('"' + body.replace("\n", "\\n") + '"')
    if text.startswith('"'):
        value = json.loads(text)
        if not isinstance(value, str):
            raise ValueError("invalid basic string")
        return value
    if text.startswith("'"):
        if not text.endswith("'") or len(text) < 2:
            raise ValueError("unterminated literal string")
        return text[1:-1]
    if text in {"true", "false"}:
        return text == "true"
    if text.startswith("["):
        if not text.endswith("]"):
            raise ValueError("unterminated array")
        body = text[1:-1].strip()
        if not body:
            return []
        items, complete = _toml_scan(body, ",")
        if not complete or (items and not items[-1] and any(items[:-1])):
            items = items[:-1]
        if any(not item for item in items):
            raise ValueError("invalid array")
        return [_toml_parse_value(item) for item in items]
    if text.startswith("{"):
        if not text.endswith("}"):
            raise ValueError("unterminated inline table")
        result: dict[str, Any] = {}
        body = text[1:-1].strip()
        if not body:
            return result
        items, complete = _toml_scan(body, ",")
        if not complete or any(not item for item in items):
            raise ValueError("invalid inline table")
        for item in items:
            key, raw_value = _toml_assignment(item)
            _toml_assign(result, _toml_key_parts(key), _toml_parse_value(raw_value))
        return result
    normalized = text.replace("_", "")
    if re.fullmatch(r"[+-]?0x[0-9A-Fa-f]+", normalized):
        return int(normalized, 16)
    if re.fullmatch(r"[+-]?0o[0-7]+", normalized):
        return int(normalized, 8)
    if re.fullmatch(r"[+-]?0b[01]+", normalized):
        return int(normalized, 2)
    if re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)", normalized):
        return int(normalized)
    if re.fullmatch(r"[+-]?(?:(?:[0-9]+\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+|inf|nan)", normalized):
        return float(normalized)
    raise ValueError("unsupported or invalid TOML value")


def _toml_assignment(statement: str) -> tuple[str, str]:
    parts, complete = _toml_scan(statement, "=")
    if not complete or len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("expected key = value")
    return parts[0], parts[1]


def _toml_assign(root: dict[str, Any], path: list[str], value: Any) -> None:
    current = root
    for part in path[:-1]:
        existing = current.get(part)
        if existing is None:
            existing = {}
            current[part] = existing
        if not isinstance(existing, dict):
            raise ValueError("key conflicts with an existing value")
        current = existing
    if path[-1] in current:
        raise ValueError("duplicate key")
    current[path[-1]] = value


def _compat_toml_loads(text: str) -> dict[str, Any]:
    """Parse the TOML value surface HarnessBuilder can deterministically render."""
    statements: list[str] = []
    pending = ""
    for line in text.splitlines():
        pending = pending + ("\n" if pending else "") + line
        stripped = pending.strip()
        if not stripped:
            pending = ""
            continue
        _, complete = _toml_scan(pending)
        if complete:
            statements.append(pending)
            pending = ""
    if pending.strip():
        raise ValueError("unterminated TOML expression")

    result: dict[str, Any] = {}
    table_path: list[str] = []
    declared_tables: set[tuple[str, ...]] = set()
    for raw_statement in statements:
        statement = _toml_strip_comments(raw_statement).strip()
        if not statement or statement.startswith("#"):
            continue
        if statement.startswith("[["):
            raise ValueError("array tables are unsupported")
        if statement.startswith("["):
            if not statement.endswith("]"):
                raise ValueError("invalid table header")
            table_path = _toml_key_parts(statement[1:-1].strip())
            table_key = tuple(table_path)
            if table_key in declared_tables:
                raise ValueError("duplicate table")
            declared_tables.add(table_key)
            current = result
            for part in table_path:
                existing = current.get(part)
                if existing is None:
                    existing = {}
                    current[part] = existing
                if not isinstance(existing, dict):
                    raise ValueError("table conflicts with an existing value")
                current = existing
            continue
        key, raw_value = _toml_assignment(raw_statement)
        _toml_assign(result, table_path + _toml_key_parts(key), _toml_parse_value(raw_value))
    return result


def parse_toml_document(content: bytes, source: Path) -> dict[str, Any]:
    try:
        text = content.decode()
        value = _tomllib.loads(text) if _tomllib is not None else _compat_toml_loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        fail("HB009", f"Invalid TOML agent source: {exc}", sources=(source.as_posix(),))
    return value


def semantic_merge(left: Any, right: Any, target: str, source: str, key: str = "") -> Any:
    if left == right:
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        result = dict(left)
        for child_key, child_value in right.items():
            child_path = f"{key}.{child_key}" if key else str(child_key)
            if child_key in result:
                result[child_key] = semantic_merge(result[child_key], child_value, target, source, child_path)
            else:
                result[child_key] = child_value
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = list(left)
        identities = {canonical_json(item) for item in result}
        for item in right:
            identity = canonical_json(item)
            if identity not in identities:
                result.append(item)
                identities.add(identity)
        return result
    fail(
        "HB010",
        f"Semantic conflict in {target} at {key or '<root>'}",
        sources=(source,),
        target=target,
        semantic_key=key or "<root>",
    )


def lint_secrets(value: Any, source: str, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            child_path = f"{key}.{child_key}" if key else str(child_key)
            if SECRET_KEY_RE.search(str(child_key)) and isinstance(child, str) and child.strip():
                stripped = child.strip()
                allowed = stripped.startswith(("${", "$", "env:", "keyring:", "credential-helper:"))
                if not allowed:
                    fail("HB011", f"Secret literal is forbidden at {child_path}", sources=(source,), semantic_key=child_path)
            lint_secrets(child, source, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            lint_secrets(child, source, f"{key}[{index}]")


def lint_codex_project_config(value: dict[str, Any], source: str) -> None:
    forbidden = sorted(CODEX_FORBIDDEN_PROJECT_KEYS.intersection(value))
    if forbidden:
        fail(
            "HB011",
            "Codex project config contains user/machine-level keys: " + ", ".join(forbidden),
            sources=(source,),
            semantic_key=forbidden[0],
            action="Keep provider, auth, notification, profile, and telemetry settings in user-level Codex config.",
        )


def render_instruction_document(target: str, contributions: list[Contribution]) -> bytes:
    chunks = ["<!-- Generated by HarnessBuilder. Edit .harness-builder/agents or Skill .harness-agents sources. -->", ""]
    seen: set[str] = set()
    for item in contributions:
        digest = sha256_bytes(item.content)
        if digest in seen:
            continue
        seen.add(digest)
        try:
            body = item.content.decode().strip()
        except UnicodeDecodeError:
            fail("HB009", f"{target} source must be UTF-8", sources=(item.source,), target=target)
        if not body:
            continue
        chunks.extend((f"<!-- source: {item.source} -->", body, ""))
    return ("\n".join(chunks).rstrip() + "\n").encode()


def toml_key(key: str) -> str:
    return key if BARE_TOML_KEY_RE.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            fail("HB009", "Non-finite TOML floats are unsupported")
        return repr(value)
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    fail("HB009", f"Unsupported TOML value type: {type(value).__name__}")


def render_toml(value: dict[str, Any]) -> str:
    lines: list[str] = []

    def emit_table(table: dict[str, Any], path: tuple[str, ...], header: bool) -> None:
        scalar_items = [(key, item) for key, item in sorted(table.items()) if not isinstance(item, dict)]
        dict_items = [(key, item) for key, item in sorted(table.items()) if isinstance(item, dict)]
        if header:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append("[" + ".".join(toml_key(part) for part in path) + "]")
        for key, item in scalar_items:
            lines.append(f"{toml_key(key)} = {toml_value(item)}")
        for key, item in dict_items:
            emit_table(item, path + (key,), True)

    emit_table(value, (), False)
    return "\n".join(lines).rstrip() + "\n"


def load_previous_lock(root: Path) -> dict[str, Any] | None:
    path = root / ".harness-builder" / "lock.json"
    if not path.exists():
        return None
    if path.is_symlink():
        fail("HB011", "Ownership lock must not be a symlink", sources=(path.as_posix(),))
    raw = read_json(path, "HB001", "lock")
    required = {"schema", "builder", "space", "agents", "providers", "skills", "artifacts"}
    if (
        not isinstance(raw, dict)
        or not required.issubset(raw)
        or set(raw) - required - {"generatedAt"}
        or raw.get("schema") != LOCK_SCHEMA
    ):
        fail("HB001", "Invalid .harness-builder/lock.json", sources=(path.as_posix(),))
    builder = raw.get("builder")
    if (
        not isinstance(builder, dict)
        or not isinstance(builder.get("version"), str)
        or not valid_digest(builder.get("digest"))
        or not isinstance(raw.get("space"), dict)
        or any(not isinstance(raw.get(key), list) for key in ("agents", "providers", "skills", "artifacts"))
    ):
        fail("HB001", "Invalid .harness-builder/lock.json structure", sources=(path.as_posix(),))
    for index, artifact in enumerate(raw["artifacts"]):
        validate_lock_artifact(artifact, index, path)
    return raw


def valid_digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def managed_target_matches(logical_type: str, target: str) -> bool:
    exact: dict[str, set[str]] = {
        "workspace-rule": {
            ".harness-builder/generated/workspace-rule.md",
            ".cursor/rules/harnessbuilder-workspace.mdc",
            ".codebuddy/rules/harnessbuilder-workspace.md",
            ".claude/rules/harnessbuilder-workspace.md",
        },
        "project-instructions": {"AGENTS.md", "CLAUDE.md"},
        "codex-config": {".codex/config.toml"},
        "codex-hooks": {".codex/hooks.json"},
        "codebuddy-settings": {".codebuddy/settings.json"},
        "codebuddy-mcp": {".codebuddy/mcp.json"},
        "claude-settings": {".claude/settings.json"},
        "claude-mcp": {".mcp.json"},
    }
    if logical_type in exact:
        return target in exact[logical_type]
    prefixes: dict[str, tuple[str, str]] = {
        "codex-rule": (".codex/rules/", ".rules"),
        "codex-hook-file": (".codex/hooks/", ""),
        "cursor-rule": (".cursor/rules/", ".mdc"),
        "cursor-command": (".cursor/commands/", ".md"),
        "codebuddy-command": (".codebuddy/commands/", ".md"),
        "codebuddy-agent": (".codebuddy/agents/", ".md"),
        "codebuddy-hook-file": (".codebuddy/hooks/", ""),
        "claude-rule": (".claude/rules/", ".md"),
        "claude-command": (".claude/commands/", ".md"),
        "claude-agent": (".claude/agents/", ".md"),
        "claude-hook-file": (".claude/hooks/", ""),
    }
    if logical_type in prefixes:
        prefix, suffix = prefixes[logical_type]
        return target.startswith(prefix) and len(target) > len(prefix) and (not suffix or target.endswith(suffix))
    if logical_type == "common-skill":
        return any(
            target.startswith(prefix) and len(Path(target).parts) >= len(Path(prefix).parts) + 2
            for prefix in (".agents/skills", ".cursor/skills", ".codebuddy/skills", ".claude/skills")
        )
    return False


def validate_lock_artifact(artifact: Any, index: int, path: Path) -> None:
    required = {"target", "sources", "logicalType", "operation", "digest", "executable"}
    optional = {"semanticKey", "risks"}
    if not isinstance(artifact, dict) or not required.issubset(artifact) or set(artifact) - required - optional:
        fail("HB001", f"Invalid lock artifact at index {index}", sources=(path.as_posix(),))
    target = artifact.get("target")
    logical_type = artifact.get("logicalType")
    sources = artifact.get("sources")
    if (
        not isinstance(target, str)
        or not isinstance(logical_type, str)
        or not isinstance(sources, list)
        or not sources
        or any(not isinstance(item, str) or not item for item in sources)
        or ("semanticKey" in artifact and (not isinstance(artifact["semanticKey"], str) or not artifact["semanticKey"]))
        or artifact.get("operation") not in {"copy", "render", "merge-document", "merge-json", "merge-toml"}
        or not valid_digest(artifact.get("digest"))
        or not isinstance(artifact.get("executable"), bool)
    ):
        fail("HB001", f"Invalid lock artifact fields at index {index}", sources=(path.as_posix(),))
    normalized = normalize_target(target)
    if not managed_target_matches(logical_type, normalized):
        fail("HB001", f"Lock artifact target is not valid for {logical_type}: {target}", sources=(path.as_posix(),))
    risks = artifact.get("risks", [])
    if not isinstance(risks, list) or any(not isinstance(item, dict) for item in risks):
        fail("HB001", f"Invalid lock artifact risks at index {index}", sources=(path.as_posix(),))


def owned_targets(previous: dict[str, Any] | None) -> set[str]:
    if not previous:
        return set()
    result: set[str] = set()
    for artifact in previous.get("artifacts", []):
        if isinstance(artifact, dict) and isinstance(artifact.get("target"), str):
            result.add(normalize_target(artifact["target"]))
    return result


def check_target_conflicts(root: Path, operations: list[Operation], previous: dict[str, Any] | None) -> None:
    owned = owned_targets(previous)
    for operation in operations:
        target = root / operation.target
        ensure_safe_parent(root, target)
        if target.is_symlink():
            fail("HB011", f"Generated target is a symlink: {operation.target}", target=operation.target)
        if target.exists() and not target.is_file():
            fail("HB010", f"Generated file target has incompatible kind: {operation.target}", target=operation.target)
        if operation.target in owned or not target.exists():
            continue
        if target.is_file() and not target.is_symlink() and target.read_bytes() == operation.content:
            continue
        fail(
            "HB010",
            f"Generated target already exists but is not owned: {operation.target}",
            target=operation.target,
            action="Move its content into .harness-builder/agents, then remove the target and rebuild.",
        )
    planned = {operation.target for operation in operations}
    for target_rel in sorted(owned - planned):
        target = root / target_rel
        ensure_safe_parent(root, target)
        if target.exists() and not target.is_file() and not target.is_symlink():
            fail("HB010", f"Owned file target changed type: {target_rel}", target=target_rel)


def ensure_safe_parent(root: Path, target: Path) -> None:
    try:
        target.relative_to(root)
    except ValueError:
        fail("HB011", f"Target escapes Harness Space: {target}", target=target.as_posix())
    current = root
    for part in target.relative_to(root).parts[:-1]:
        current = current / part
        if current.is_symlink():
            fail("HB011", f"Target parent is a symlink: {portable_rel(root, current)}", target=portable_rel(root, target))
        if current.exists() and not current.is_dir():
            fail("HB010", f"Target parent is not a directory: {portable_rel(root, current)}", target=portable_rel(root, target))


def make_lock(
    root: Path,
    manifest: Manifest,
    workspace: Workspace,
    providers: list[Provider],
    skills: list[Skill],
    operations: list[Operation],
) -> dict[str, Any]:
    script = Path(__file__).resolve()
    return {
        "schema": LOCK_SCHEMA,
        "builder": {"version": VERSION, "digest": sha256_file(script)},
        "space": {
            "name": manifest.name,
            "root": ".",
            "manifestDigest": sha256_file(manifest.path),
            "workspace": workspace.path.name,
            "workspaceDigest": sha256_file(workspace.path),
            "folders": [{"name": item.name, "path": item.path} for item in workspace.folders],
        },
        "agents": [
            {"id": agent, "adapterVersion": ADAPTER_VERSIONS[agent], "capabilityStatus": ADAPTER_STATUS[agent]}
            for agent in manifest.agents
        ],
        "providers": [provider_lock_record(root, provider) for provider in providers],
        "skills": [
            {
                "name": skill.name,
                "provider": skill.provider.provider_id,
                "source": f"{skill.provider.configured_path}/{skill.name}",
                "digest": skill.digest,
                "selectedBy": skill.selected_by,
                "matchedTags": skill.matched_tags,
                "shadowedCandidates": skill.shadowed,
            }
            for skill in skills
        ],
        "artifacts": [
            {
                "target": operation.target,
                "sources": operation.sources,
                "logicalType": operation.logical_type,
                "semanticKey": operation.semantic_key or f"target:{operation.target.casefold()}",
                "operation": operation.operation,
                "digest": operation.digest,
                "executable": operation.executable,
                "risks": operation.risks,
            }
            for operation in operations
        ],
    }


def provider_lock_record(root: Path, provider: Provider) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": provider.provider_id,
        "type": provider.provider_type,
        "digest": provider.digest,
        "snapshot": provider.digest,
        "priority": provider.priority,
    }
    if provider.provider_type == "git":
        assert provider.url is not None
        assert provider.selector_kind is not None
        assert provider.selector_value is not None
        assert provider.commit is not None
        assert provider.subdir is not None
        cache_id = hashlib.sha256(provider.url.encode()).hexdigest()
        subdir_id = "full/" + provider.subdir if provider.command is not None else hashlib.sha256(provider.subdir.encode()).hexdigest()[:16]
        record.update(
            {
                "url": provider.url,
                provider.selector_kind: provider.selector_value,
                "commit": provider.commit,
                "subdir": provider.subdir,
                "resolvedPath": f"cache://git/{cache_id}/snapshots/{provider.commit}/{subdir_id}",
            }
        )
    else:
        record.update(
            {
                "path": provider.configured_path,
                "subdir": provider.subdir or ".",
                "resolvedPath": Path(os.path.relpath(provider.root, root)).as_posix(),
            }
        )
    if provider.command is not None:
        record["command"] = provider.command
    return record


class BuildLock:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / ".harness-builder" / "build.lock"
        self.acquired = False

    def __enter__(self) -> "BuildLock":
        state_root = self.path.parent
        if state_root.is_symlink():
            fail(
                "HB011",
                ".harness-builder must not be a symlink",
                sources=(state_root.as_posix(),),
                action="Replace it with a real directory inside the Harness Space.",
            )
        if state_root.exists() and not state_root.is_dir():
            fail("HB011", ".harness-builder must be a directory", sources=(state_root.as_posix(),))
        if self.path.is_symlink():
            fail("HB011", "build.lock must not be a symlink", sources=(self.path.as_posix(),))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json_bytes({"pid": os.getpid(), "host": socket.gethostname(), "startedAt": process_started_marker()})
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            self.raise_existing()
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self.acquired = True
        hold_raw = os.environ.get("HARNESSBUILDER_TEST_HOLD_LOCK_MILLISECONDS")
        if hold_raw:
            try:
                hold_seconds = max(0, int(hold_raw)) / 1000
            except ValueError:
                hold_seconds = 0
            if hold_seconds:
                time.sleep(hold_seconds)
        return self

    def raise_existing(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        pid = raw.get("pid") if isinstance(raw, dict) else None
        host = raw.get("host") if isinstance(raw, dict) else None
        if host == socket.gethostname() and isinstance(pid, int) and not process_alive(pid):
            fail(
                "HB014",
                f"Stale build lock detected for pid {pid}",
                sources=(self.path.as_posix(),),
                action="Confirm the process is gone, then delete .harness-builder/build.lock.",
            )
        fail("HB013", "Another build or clean operation holds .harness-builder/build.lock", sources=(self.path.as_posix(),))

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            try:
                self.path.parent.rmdir()
            except OSError:
                pass


def process_started_marker() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def atomic_write(root: Path, operation: Operation) -> None:
    target = root / operation.target
    ensure_safe_parent(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        fail("HB010", f"Generated file target has incompatible kind: {operation.target}", target=operation.target)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(operation.content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o755 if operation.executable else 0o644)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def remove_owned_target(root: Path, target_rel: str) -> None:
    target_rel = normalize_target(target_rel)
    target = root / target_rel
    ensure_safe_parent(root, target)
    if target.is_symlink() or target.is_file():
        try:
            target.unlink()
        except FileNotFoundError:
            pass
    elif target.exists():
        fail("HB010", f"Owned file target changed type: {target_rel}", target=target_rel)
    prune_empty_parents(root, target.parent)


def prune_empty_parents(root: Path, start: Path) -> None:
    protected = {
        root,
        root / ".harness-builder",
        root / ".harness-builder" / "agents",
        root / ".harness-builder" / "skills",
    }
    current = start
    while current not in protected and current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


@dataclasses.dataclass
class BuildModel:
    root: Path
    manifest: Manifest
    workspace: Workspace
    providers: list[Provider]
    skills: list[Skill]
    resolved_skills: dict[str, Skill]
    operations: list[Operation]
    previous: dict[str, Any] | None
    warnings: list[Diagnostic]


def plan(root: Path, *, offline: bool = False) -> BuildModel:
    if not root.is_dir():
        fail("HB001", f"Harness Space root is not a directory: {root}")
    detect_legacy(root)
    manifest = load_manifest(root)
    workspace = load_workspace(root, manifest)
    validate_agent_namespace(root / ".harness-builder" / "agents", "Harness Space")
    previous = load_previous_lock(root)
    providers = load_providers(root, manifest, previous, offline)
    warnings: list[Diagnostic] = []
    skills, resolved = resolve_skills(providers, manifest, warnings)
    operations = Planner(root, manifest, workspace, skills, warnings).build()
    check_target_conflicts(root, operations, previous)
    return BuildModel(root, manifest, workspace, providers, skills, resolved, operations, previous, warnings)


def apply_build(model: BuildModel) -> tuple[int, int]:
    new_targets = {operation.target for operation in model.operations}
    old_targets = owned_targets(model.previous)
    fault_after_raw = os.environ.get("HARNESSBUILDER_TEST_FAIL_AFTER_WRITES")
    crash_after_raw = os.environ.get("HARNESSBUILDER_TEST_CRASH_AFTER_WRITES")
    try:
        fault_after = int(fault_after_raw) if fault_after_raw is not None else 0
    except ValueError:
        fault_after = 0
    try:
        crash_after = int(crash_after_raw) if crash_after_raw is not None else 0
    except ValueError:
        crash_after = 0
    writes = 0
    for operation in model.operations:
        atomic_write(model.root, operation)
        writes += 1
        if crash_after > 0 and writes >= crash_after:
            os._exit(97)
        if fault_after > 0 and writes >= fault_after:
            raise OSError("injected apply failure for E2E verification")
    removed = 0
    for target in sorted(old_targets - new_targets, reverse=True):
        remove_owned_target(model.root, target)
        removed += 1
    lock = make_lock(model.root, model.manifest, model.workspace, model.providers, model.skills, model.operations)
    lock_operation = Operation(".harness-builder/lock.json", json_bytes(lock), ["core:lock"], "ownership-lock", "render")
    atomic_write(model.root, lock_operation)
    return len(model.operations), removed


def run_post_commands(model: BuildModel) -> int:
    executed = 0
    for provider in model.providers:
        if provider.command is None:
            continue
        replacements = {
            "{spaceRoot}": str(model.root),
            "{sourceRoot}": str(provider.source_root),
            "{providerRoot}": str(provider.root),
        }
        arguments = []
        for argument in provider.command["args"]:
            for marker, value in replacements.items():
                argument = argument.replace(marker, value)
            arguments.append(argument)
        cwd = (provider.source_root / provider.command.get("cwd", ".")).resolve()
        if not cwd.is_dir():
            fail("HB016", f"Provider post command cwd not found: {cwd}", sources=(provider.provider_id,))
        env = os.environ.copy()
        env.update(
            {
                "HARNESS_SPACE_ROOT": str(model.root),
                "HARNESS_PROVIDER_SOURCE_ROOT": str(provider.source_root),
                "HARNESS_PROVIDER_ROOT": str(provider.root),
            }
        )
        try:
            completed = subprocess.run(
                arguments,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            fail("HB016", f"Provider post command failed to start: {exc}", sources=(provider.provider_id,))
        if completed.stdout:
            print(completed.stdout, file=sys.stderr, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
        if completed.returncode != 0:
            fail(
                "HB016",
                f"Provider post command exited with status {completed.returncode}: {arguments[0]}",
                sources=(provider.provider_id,),
            )
        executed += 1
    return executed


def clean(root: Path) -> tuple[int, list[Diagnostic]]:
    previous = load_previous_lock(root)
    if previous is None:
        return 0, []
    targets = sorted(owned_targets(previous), reverse=True)
    for target_rel in targets:
        target = root / target_rel
        ensure_safe_parent(root, target)
        if target.exists() and not target.is_file() and not target.is_symlink():
            fail("HB010", f"Owned file target changed type: {target_rel}", target=target_rel)
    for target in targets:
        remove_owned_target(root, target)
    lock_path = root / ".harness-builder" / "lock.json"
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    prune_empty_parents(root, lock_path.parent)
    return len(targets), []


def model_details(model: BuildModel) -> dict[str, Any]:
    return {
        "agents": [
            {"id": agent, "adapterVersion": ADAPTER_VERSIONS[agent], "capabilityStatus": ADAPTER_STATUS[agent]}
            for agent in model.manifest.agents
        ],
        "workspace": {
            "file": model.workspace.path.name,
            "folders": [{"name": item.name, "path": item.path} for item in model.workspace.folders],
        },
        "providers": [provider_lock_record(model.root, item) for item in model.providers],
        "postCommands": [
            {
                "provider": item.provider_id,
                "cwd": item.command["cwd"],
                "args": item.command["args"],
            }
            for item in model.providers
            if item.command is not None
        ],
        "skills": [
            {
                "name": item.name,
                "provider": item.provider.provider_id,
                "selectedBy": item.selected_by,
                "matchedTags": item.matched_tags,
                "shadowedCandidates": item.shadowed,
            }
            for item in model.skills
        ],
        "operations": [
            {
                "target": item.target,
                "sources": item.sources,
                "logicalType": item.logical_type,
                "semanticKey": item.semantic_key,
                "operation": item.operation,
                "digest": item.digest,
                "risks": item.risks,
            }
            for item in model.operations
        ],
    }


def report(
    command: str,
    status: str,
    root: Path,
    *,
    name: str | None = None,
    diagnostics: Iterable[Diagnostic] = (),
    summary: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "builderVersion": VERSION,
        "command": command,
        "status": status,
        "spaceRoot": str(root),
        "diagnostics": [item.as_dict() for item in diagnostics],
        "summary": summary or {},
    }
    if name is not None:
        value["space"] = name
    if details is not None:
        value["details"] = details
    return value


def print_report(value: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        return
    status = value["status"].upper()
    print(f"{status} {value['command']} {value.get('space', value['spaceRoot'])}")
    for diagnostic in value["diagnostics"]:
        print(f"{diagnostic['level'].upper()} {diagnostic['code']}: {diagnostic['message']}")
    for key, item in value["summary"].items():
        print(f"{key}: {item}")


def add_common_subcommand(
    parser: argparse.ArgumentParser,
    *,
    dry_run: bool = False,
    offline: bool = True,
) -> None:
    parser.add_argument("space", nargs="?", default=".", help="Harness Space root (default: cwd)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    if offline:
        parser.add_argument("--offline", action="store_true", help="Resolve Git Providers only from the locked local cache")
    if dry_run:
        parser.add_argument("--dry-run", action="store_true")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harnessbuilder.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"HarnessBuilder {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="Initialize the required Harness Space files")
    add_common_subcommand(init_parser, offline=False)
    init_parser.add_argument("--name", help="Space name for a new manifest (default: directory name)")
    add_common_subcommand(subparsers.add_parser("build", help="Build a Harness Space"), dry_run=True)
    add_common_subcommand(subparsers.add_parser("check", help="Validate and plan without writes"))
    add_common_subcommand(subparsers.add_parser("explain", help="Explain providers, skills, and targets"))
    add_common_subcommand(subparsers.add_parser("clean", help="Remove owned generated artifacts"), offline=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    root = Path(args.space).resolve()
    try:
        if args.command == "init":
            if root.exists() and not root.is_dir():
                fail("HB001", f"Harness Space root is not a directory: {root}")
            root.mkdir(parents=True, exist_ok=True)
            with BuildLock(root):
                manifest, created, validated = init_space(root, args.name)
            value = report(
                "init",
                "ok",
                root,
                name=manifest.name,
                summary={"created": len(created), "validated": len(validated)},
                details={"files": [{"path": item, "status": "created"} for item in created]
                + [{"path": item, "status": "validated"} for item in validated]},
            )
            print_report(value, args.format)
            return 0
        if not root.is_dir():
            fail("HB001", f"Harness Space root is not a directory: {root}")
        if args.command == "clean":
            with BuildLock(root):
                removed, warnings = clean(root)
            value = report("clean", "ok", root, diagnostics=warnings, summary={"removed": removed})
            print_report(value, args.format)
            return 0
        if args.command == "build" and not args.dry_run:
            with BuildLock(root):
                model = plan(root, offline=args.offline)
                generated, removed = apply_build(model)
                post_commands = run_post_commands(model)
            value = report(
                "build",
                "ok",
                root,
                name=model.manifest.name,
                diagnostics=model.warnings,
                summary={
                    **{"generated": generated, "removed": removed, "skills": len(model.skills)},
                    **({"postCommands": post_commands} if post_commands else {}),
                },
            )
            print_report(value, args.format)
            return 0
        model = plan(root, offline=args.offline)
        command = "build --dry-run" if args.command == "build" else args.command
        value = report(
            command,
            "ok",
            root,
            name=model.manifest.name,
            diagnostics=model.warnings,
            summary={
                "planned": len(model.operations),
                "skills": len(model.skills),
                "postCommands": sum(1 for provider in model.providers if provider.command is not None),
            },
            details=model_details(model) if args.command == "explain" or args.format == "json" else None,
        )
        print_report(value, args.format)
        return 0
    except HarnessError as exc:
        value = report(args.command, "error", root, diagnostics=(exc.diagnostic,), summary={})
        print_report(value, args.format)
        return 1
    except OSError as exc:
        diagnostic = Diagnostic("error", "HB011", f"Filesystem error: {exc}")
        value = report(args.command, "error", root, diagnostics=(diagnostic,), summary={})
        print_report(value, args.format)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
