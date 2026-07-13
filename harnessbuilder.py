#!/usr/bin/env python3
"""HarnessBuilder v1: deterministic, dependency-free Harness Space compiler."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any, Iterable
from datetime import datetime, timezone


VERSION = "0.1.0"
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
ADAPTER_VERSIONS = {agent: "1" for agent in AGENTS}
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
        }
        if self.sources:
            result["sources"] = list(self.sources)
        if self.target is not None:
            result["target"] = self.target
        if self.semantic_key is not None:
            result["semanticKey"] = self.semantic_key
        if self.suggested_action is not None:
            result["suggestedAction"] = self.suggested_action
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


def parse_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        fail("HB008", "SKILL.md must be UTF-8", sources=(path.as_posix(),))
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail("HB008", "SKILL.md is missing YAML frontmatter", sources=(path.as_posix(),))
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        fail("HB008", "SKILL.md frontmatter is not closed", sources=(path.as_posix(),))
    data: dict[str, Any] = {}
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
        if value:
            if value.startswith("["):
                try:
                    parsed = json.loads(value.replace("'", '"'))
                except json.JSONDecodeError:
                    fail("HB008", f"Invalid inline list for {key}", sources=(path.as_posix(),))
                data[key] = parsed
            else:
                data[key] = strip_yaml_scalar(value)
            continue
        items: list[str] = []
        while i < end and (not lines[i].strip() or lines[i][:1].isspace()):
            nested = lines[i].strip()
            i += 1
            if not nested or nested.startswith("#"):
                continue
            if not nested.startswith("- "):
                fail("HB008", f"Unsupported nested frontmatter for {key}", sources=(path.as_posix(),))
            items.append(strip_yaml_scalar(nested[2:].strip()))
        data[key] = items
    return data


def strip_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def validate_markdown_frontmatter(path: Path, required: tuple[str, ...]) -> None:
    data = parse_frontmatter_generic(path)
    for key in required:
        if not isinstance(data.get(key), str) or not str(data[key]).strip():
            fail("HB009", f"{path.name} must declare non-empty {key} frontmatter", sources=(path.as_posix(),))


def parse_frontmatter_generic(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        fail("HB009", "Agent Markdown must be UTF-8", sources=(path.as_posix(),))
    if not lines or lines[0].strip() != "---":
        fail("HB009", "Agent Markdown is missing frontmatter", sources=(path.as_posix(),))
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        fail("HB009", "Agent Markdown frontmatter is not closed", sources=(path.as_posix(),))
    data: dict[str, Any] = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#") or raw[:1].isspace() or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        data[key.strip()] = strip_yaml_scalar(value.strip())
    return data


@dataclasses.dataclass
class Manifest:
    path: Path
    name: str
    description: str | None
    agents: list[str]
    skills: list[str]
    tags: list[str]
    providers: list[dict[str, str]]


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
    configured_path: str
    priority: int
    digest: str


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


@dataclasses.dataclass
class Operation:
    target: str
    content: bytes
    sources: list[str]
    logical_type: str
    operation: str
    executable: bool = False

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
    providers: list[dict[str, str]] = []
    seen_provider_specs: set[str] = set()
    for index, item in enumerate(providers_raw):
        if not isinstance(item, dict) or set(item) != {"type", "path"}:
            fail("HB001", f"skillProviders[{index}] must contain only type and path", sources=(path.as_posix(),))
        kind, configured = item.get("type"), item.get("path")
        if kind != "folder":
            fail("HB006", f"Unsupported provider type: {kind}", sources=(path.as_posix(),))
        if not isinstance(configured, str) or not configured.strip():
            fail("HB001", f"skillProviders[{index}].path must be a non-empty string", sources=(path.as_posix(),))
        if Path(configured).is_absolute():
            fail("HB001", f"skillProviders[{index}].path must be relative", sources=(path.as_posix(),))
        normalized_provider_path = Path(os.path.normpath(configured)).as_posix()
        spec = canonical_json({"type": kind, "path": os.path.normcase(normalized_provider_path)})
        if spec in seen_provider_specs:
            fail("HB001", f"Duplicate skill provider: {configured}", sources=(path.as_posix(),))
        seen_provider_specs.add(spec)
        providers.append({"type": kind, "path": configured})
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


def load_providers(root: Path, manifest: Manifest) -> list[Provider]:
    specs = [("space-local", ".harness-builder/skills")]
    specs.extend((f"folder:{item['path']}", item["path"]) for item in manifest.providers)
    providers: list[Provider] = []
    generated_roots = [root / name for name in (".codex", ".cursor", ".codebuddy", ".claude", ".agents")]
    for priority, (provider_id, configured) in enumerate(specs):
        provider_root = (root / configured).resolve()
        if provider_id == "space-local" and not provider_root.exists():
            providers.append(Provider(provider_id, provider_root, configured, priority, tree_digest(provider_root)))
            continue
        if not provider_root.is_dir():
            fail("HB005", f"Skill provider directory not found: {configured}", sources=(configured,))
        for generated in generated_roots:
            generated_resolved = generated.resolve()
            if provider_root == generated_resolved or generated_resolved in provider_root.parents:
                fail("HB011", f"Provider cannot be inside generated target: {configured}", sources=(configured,))
        providers.append(Provider(provider_id, provider_root, configured, priority, tree_digest(provider_root)))
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
    return Skill(name, description, list(tags), directory, provider, tree_digest(directory))


def resolve_skills(providers: list[Provider], manifest: Manifest, warnings: list[Diagnostic]) -> tuple[list[Skill], dict[str, Skill]]:
    candidates: dict[str, list[Skill]] = {}
    for provider in providers:
        if not provider.root.exists():
            continue
        for directory in sorted(provider.root.iterdir(), key=lambda p: p.name):
            if not directory.is_dir() or directory.is_symlink() or not (directory / "SKILL.md").is_file():
                continue
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
        key = target.casefold()
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
            semantic_key = agent_semantic_key(agent, relative, path)
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
                parse_json_document(content, path)
            elif merge == "toml":
                parse_toml_document(content, path)
            self.add(Contribution(target, content, f"{source_id}:{relative}", logical_type, merge, executable))

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
                )
            )
        return operations


def normalize_target(target: str) -> str:
    path = Path(target)
    if path.is_absolute() or not target or any(part in ("", ".", "..") for part in path.parts):
        fail("HB011", f"Unsafe generated target: {target}", target=target)
    normalized = path.as_posix()
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
            validate_markdown_frontmatter(source_path, ("name", "description"))
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
            return relative, "claude-rule", "plain"
        if relative.startswith(".claude/commands/") and relative.endswith(".md"):
            return relative, "claude-command", "plain"
        if relative.startswith(".claude/agents/") and relative.endswith(".md"):
            validate_markdown_frontmatter(source_path, ("name", "description"))
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


def parse_toml_document(content: bytes, source: Path) -> dict[str, Any]:
    try:
        value = tomllib.loads(content.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
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
    raw = read_json(path, "HB001", "lock")
    if not isinstance(raw, dict) or raw.get("schema") != LOCK_SCHEMA or not isinstance(raw.get("artifacts"), list):
        fail("HB001", "Invalid .harness-builder/lock.json", sources=(path.as_posix(),))
    return raw


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
        "agents": [{"id": agent, "adapterVersion": ADAPTER_VERSIONS[agent]} for agent in manifest.agents],
        "providers": [
            {
                "id": provider.provider_id,
                "path": provider.configured_path,
                "digest": provider.digest,
                "priority": provider.priority,
            }
            for provider in providers
        ],
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
                "operation": operation.operation,
                "digest": operation.digest,
                "executable": operation.executable,
            }
            for operation in operations
        ],
    }


class BuildLock:
    def __init__(self, root: Path):
        self.path = root / ".harness-builder" / "build.lock"
        self.acquired = False

    def __enter__(self) -> "BuildLock":
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
        target.unlink(missing_ok=True)
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


def plan(root: Path) -> BuildModel:
    if not root.is_dir():
        fail("HB001", f"Harness Space root is not a directory: {root}")
    detect_legacy(root)
    manifest = load_manifest(root)
    workspace = load_workspace(root, manifest)
    providers = load_providers(root, manifest)
    warnings: list[Diagnostic] = []
    skills, resolved = resolve_skills(providers, manifest, warnings)
    operations = Planner(root, manifest, workspace, skills, warnings).build()
    previous = load_previous_lock(root)
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
    lock_path.unlink(missing_ok=True)
    prune_empty_parents(root, lock_path.parent)
    return len(targets), []


def model_details(model: BuildModel) -> dict[str, Any]:
    return {
        "workspace": {
            "file": model.workspace.path.name,
            "folders": [{"name": item.name, "path": item.path} for item in model.workspace.folders],
        },
        "providers": [
            {"id": item.provider_id, "path": item.configured_path, "priority": item.priority, "digest": item.digest}
            for item in model.providers
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
                "operation": item.operation,
                "digest": item.digest,
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


def add_common_subcommand(parser: argparse.ArgumentParser, *, dry_run: bool = False) -> None:
    parser.add_argument("space", nargs="?", default=".", help="Harness Space root (default: cwd)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    if dry_run:
        parser.add_argument("--dry-run", action="store_true")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="harnessbuilder.py")
    parser.add_argument("--version", action="version", version=f"HarnessBuilder {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_common_subcommand(subparsers.add_parser("build", help="Build a Harness Space"), dry_run=True)
    add_common_subcommand(subparsers.add_parser("check", help="Validate and plan without writes"))
    add_common_subcommand(subparsers.add_parser("explain", help="Explain providers, skills, and targets"))
    add_common_subcommand(subparsers.add_parser("clean", help="Remove owned generated artifacts"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    root = Path(args.space).resolve()
    try:
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
                model = plan(root)
                generated, removed = apply_build(model)
            value = report(
                "build",
                "ok",
                root,
                name=model.manifest.name,
                diagnostics=model.warnings,
                summary={"generated": generated, "removed": removed, "skills": len(model.skills)},
            )
            print_report(value, args.format)
            return 0
        model = plan(root)
        command = "build --dry-run" if args.command == "build" else args.command
        value = report(
            command,
            "ok",
            root,
            name=model.manifest.name,
            diagnostics=model.warnings,
            summary={"planned": len(model.operations), "skills": len(model.skills)},
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
