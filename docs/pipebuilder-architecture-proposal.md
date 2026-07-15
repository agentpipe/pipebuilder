# PipeBuilder: Decentralized Cross-Agent PipeSpace Builder Architecture Proposal

Status: proposal
Date: 2026-07-13
Scope: Decoupling THarness Builder, the PipeSpace directory protocol, and cross-agent PipeSpace construction

Related documents:

- [PipeBuilder PipeSpace and Skill Provider Protocol](pipebuilder-space-json-spec.md): Protocols for `pipespace.json`, Skill Providers, selection, and workspace rules.
- [PipeBuilder Initial Four-Agent Adapter Specification](pipebuilder-agent-adapters.md): Initial projection specifications for Codex, Cursor, CodeBuddy, and Claude Code.
- [PipeBuilder Python E2E Integration Test Architecture](pipebuilder-test-architecture.md): Black-box PipeSpace sandboxes, goldens, ownership, cross-platform coverage, real-client gates, and real-model gates.
- [PipeBuilder Skill Fixture Catalog](pipebuilder-skill-fixture-catalog.md): Five Skill fixture packs, a four-agent capability matrix, PipeSpace overlays, and Codex live probes.
- [THarness Builder Migration Audit](pipebuilder-tharness-migration-audit.md): Migration of legacy capabilities, deletion boundaries, and compatibility results for real shared skills.

Once accepted, this proposal supersedes the designs in `tagent-builder-proposal.md` for a centralized THarness Builder, fixed shared skills, and separately generated workspaces. `platform-capability-report.md` remains a historical research snapshot for the first three platforms; the added Claude Code conclusions are governed by the companion adapter specification for this document.

---

## 1. Proposal

Extract `pipebuilder` from THarness as a standalone tool. It is a cross-agent PipeSpace Builder that has no dependency on a central repository, is distributed as a single file, and operates in place within a PipeSpace directory.

PipeBuilder has one responsibility:

> Read the current PipeSpace directory, the required `pipespace.json`, the human-maintained `<name>.code-workspace` workspace file (where `name` comes from the manifest), multiple Skill Providers, Skill-level `.pipe-agents`, and PipeSpace-level `.pipebuilder/agents`; generate skills, rules, commands, agents, hooks, and configuration that four coding agents can discover directly in the current directory; and write a traceable build lock.

The initial release is:

```text
pipebuilder.py
```

It no longer requires an npm package, `pip install`, TypeScript build artifacts, a THarness repository root, or a fixed directory registry.

The initial PipeBuilder release includes four built-in agent adapters:

```text
codex
cursor
codebuddy
claude-code
```

### 1.1 Canonical namespace

The initial release accepts only one naming scheme and does not maintain legacy and current aliases in parallel:

| Role | Canonical name | Ownership |
| --- | --- | --- |
| CLI/release file | `pipebuilder.py` | Tool release |
| PipeSpace manifest | `pipespace.json` | Human-owned, required |
| Manifest schema | `pipespace.v1` | Protocol |
| Final workspace file | `<pipespace.json.name>.code-workspace` | Human-owned, required |
| Space-level agent input | `.pipebuilder/agents/<agent>/` | Human-owned build input |
| PipeSpace-local Skills | `.pipebuilder/skills/<skill>/` | Human-owned build input |
| Skill-level agent input | `<skill>/.pipe-agents/<agent>/` | Skill source build input |
| Core-generated state | `.pipebuilder/generated/` | PipeBuilder-owned |
| Ownership lock | `.pipebuilder/lock.json` | PipeBuilder-owned |
| Operation lock | `.pipebuilder/build.lock` | PipeBuilder process-local state |
| Lock schema | `pipebuilder-lock.v1` | Protocol |
| CLI report schema | `pipebuilder-report.v1` | Protocol |
| Diagnostics | `PB001` onward | Protocol |

All Space-level agent input resides in `.pipebuilder/agents/<agent>/`. Skill-level agent input continues to use `<skill>/.pipe-agents/<agent>/`, avoiding the embedding of PipeBuilder's space-management directory in a standard Skill package. Each `<agent>/` is a virtual platform-configuration root and preserves the platform's native target-relative paths. For example, Codex uses `AGENTS.md` and `.codex/`, while Cursor uses `.cursor/`. A generic abstract directory hierarchy such as `files/rules/commands/hooks/config` is no longer used.

`.pipebuilder/agents/` and `.pipebuilder/skills/` are Human-owned sources. `.pipebuilder/generated/`, `lock.json`, and the transient `build.lock` are Builder-owned state. Platform output continues to use native directories such as `.codex/`, `.cursor/`, `.codebuddy/`, and `.claude/`.

Adapter plugins may be introduced in the future, but the initial release uses built-in adapters to ensure that copying a single `pipebuilder.py` is sufficient for a standard build.

---

## 2. Confirmed Design Decisions

### 2.1 The PipeSpace and build target share one directory

Remove the legacy THarness two-stage model that separated central sources from the generated workspace:

```text
Legacy model:
central-sources/foo/ -> Builder -> generated-spaces/foo/

New model:
foo/ -> pipebuilder build -> foo/
```

The PipeSpace directory simultaneously contains:

- the human-maintained workspace definition;
- PipeSpace-private build input;
- the actual working directory used by agents;
- generated configuration for agent platforms;
- the PipeBuilder build lock.

The "PipeSpace source" and "generated workspace" are no longer separate entities.

### 2.2 The workspace file is entirely Human-owned

Remove:

```text
<name>.code-workspace.src
```

The PipeSpace directly contains the final workspace file:

```text
<pipespace.json.name>.code-workspace
```

PipeBuilder:

- reads and validates it;
- generates the project path rule from `folders`;
- does not copy, rename, rewrite, or reorder the workspace file;
- does not write generated results back to the workspace file;
- does not reconstruct program state from a generated rule.

The workspace file is the sole source of truth for project names, paths, and order. `pipespace.json` is the sole source of truth for the PipeSpace's logical name and build configuration.

### 2.3 The PipeSpace name is defined by `pipespace.json`

`pipespace.json` is required, and `name` is the canonical logical name of the PipeSpace:

```json
{
  "schema": "pipespace.v1",
  "name": "my-harness-space",
  "agents": ["codex", "cursor", "codebuddy", "claude-code"],
  "skills": [],
  "tags": [],
  "skillProviders": []
}
```

The basename of the PipeSpace root is only the name of the physical container. It does not participate in identity derivation and does not need to match `name`. For example, the following directory still represents `my-harness-space`:

```text
/work/spaces/local-checkout-17/
```

The workspace filename is derived from `name` in the manifest and must therefore be:

```text
my-harness-space.code-workspace
```

Consequently, moving or renaming the PipeSpace directory does not change its logical identity, and copying the directory does not automatically create a new identity. To fork or rename a PipeSpace, explicitly change `pipespace.json.name` and rename the workspace file accordingly. A folder name identifies a project within the workspace file and has no binding to the PipeSpace name.

### 2.4 PipeSpace inputs are layered by scope

PipeSpace-local Skills and Space-level agent inputs reside under:

```text
.pipebuilder/
├── skills/
└── agents/
    ├── codex/
    ├── cursor/
    ├── codebuddy/
    └── claude-code/
```

The internal structure of `.pipebuilder/agents/<agent>/` directly follows the corresponding agent's native root-level configuration layout and is treated as a virtual platform-configuration root. For example, a Codex source may contain `AGENTS.md`, `.codex/config.toml`, `.codex/hooks.json`, and `.codex/rules/`; a Cursor source uses `.cursor/rules/` and `.cursor/commands/`. Skill-level `.pipe-agents/<agent>/` uses the same convention. An adapter is responsible only for validating permitted native paths, combining Builder sources, and projecting them to the corresponding platform targets under the PipeSpace root.

`.pipebuilder/` may be committed to Git, but it must not store tokens, passwords, or private keys. The parallel concepts `private/`, a Space-root `.pipe-agents/`, `tagents`, and `resources` are no longer retained. `.pipe-agents/` exists only within a Skill package and represents that Skill's agent-specific extensions.

### 2.5 Skills use the open standard directory layout

Every Skill package uses:

```text
skills/foo/
├── SKILL.md
├── scripts/
├── references/
├── assets/
└── .pipe-agents/
```

Creating the following layout is no longer supported:

```text
skills/foo/skill/SKILL.md
```

Agent-specific files reside in the hidden extension area at the Skill root:

```text
skills/foo/.pipe-agents/<agent>/...
```

`.pipe-agents/` is not part of the standard Skill common package. It must be excluded when copying into a platform Skill directory, and only the corresponding adapter may read it.

### 2.6 Skill sources are uniformly called Providers

Rename `skillFolders` to:

```text
skillProviders
```

The current implementation supports `folder` and `git` Providers. The protocol continues to use provider types, leaving extension points for HTTP registry, package, and artifact providers.

### 2.7 The explicit Skill list takes precedence, supplemented by tag matching

Retain:

- the explicit `skills` list;
- matching between PipeSpace `tags` and Skill frontmatter tags.

The two mechanisms are no longer mutually exclusive. Their selection result is the union:

```text
space-local skills
  UNION explicit skills
  UNION tag-matched skills
```

When the same Skill is selected by both the list and a tag, the lock records `selectedBy: skills` because explicit selection takes precedence.

### 2.8 Workspace context expresses only the folder inventory

Core generates exactly one canonical workspace rule:

```text
.pipebuilder/generated/workspace-rule.md
```

This rule expresses only the PipeSpace identity, the workspace file, and the folder inventory. It does not derive primary/reference roles, writable/read-only status, or commit boundaries from folder order. Each adapter projects it onto the platform's native instruction or rule surface. The Codex adapter deterministically combines it with `AGENTS.md` fragments from Builder sources to produce the root `AGENTS.md`. At runtime, Codex reads only the generated native files; it does not need to parse `.code-workspace` or run a PipeBuilder runtime hook.

The root `AGENTS.md`, `CLAUDE.md`, and all planned platform files under `.codex/`, `.cursor/`, `.codebuddy/`, and `.claude/` are Builder-owned targets. Before the initial migration, any human-authored content that must be retained should be moved to the corresponding native relative path under `.pipebuilder/agents/<agent>/`.

---

## 3. Final Directory Structure

```text
local-checkout-17/                         # PipeSpace root; basename has no protocol semantics
├── pipespace.json                         # Required; PipeSpace identity/config
├── my-harness-space.code-workspace           # Required; filename derived from manifest name, Human-owned
├── .pipebuilder/
│   ├── agents/                           # Space-level agent-specific source, native layout
│   │   ├── codex/
│   │   │   ├── AGENTS.md
│   │   │   └── .codex/
│   │   │       ├── config.toml
│   │   │       ├── hooks.json
│   │   │       └── rules/
│   │   ├── cursor/
│   │   │   └── .cursor/
│   │   │       ├── rules/
│   │   │       └── commands/
│   │   ├── codebuddy/
│   │   └── claude-code/
│   ├── skills/                           # PipeSpace-local Skills
│   │   └── space-supervisor/
│   │       ├── SKILL.md
│   │       ├── scripts/
│   │       ├── references/
│   │       └── .pipe-agents/
│   │           ├── codex/
│   │           ├── cursor/
│   │           ├── codebuddy/
│   │           └── claude-code/
│   ├── generated/
│   │   └── workspace-rule.md             # Generated canonical folder inventory
│   └── lock.json                         # Generated ownership/provenance
├── .agents/skills/                       # Generated Codex Skills
├── AGENTS.md                              # Generated Codex guidance
├── .codex/                               # Generated/merged Codex files
├── .cursor/                              # Generated/merged Cursor files
├── .codebuddy/                           # Generated/merged CodeBuddy files
└── .claude/                              # Generated/merged Claude Code files
```

PipeBuilder does not create semantically empty `work/`, `artifacts/`, or `logs/` directories.

---

## 4. Minimal PipeSpace Protocol

### 4.1 Required minimal manifest

Every PipeSpace must commit `pipespace.json`. The minimal configuration explicitly declares its identity, target agents, and Skill-selection inputs:

```json
{
  "schema": "pipespace.v1",
  "name": "my-harness-space",
  "agents": ["codex", "cursor", "codebuddy", "claude-code"],
  "skills": [],
  "tags": [],
  "skillProviders": []
}
```

Regardless of whether external Providers are configured, the highest-priority Provider is always enabled implicitly:

```text
.pipebuilder/skills
```

All valid Skills in this Provider are selected.

### 4.2 Common configuration

```json
{
  "schema": "pipespace.v1",
  "name": "my-harness-space",
  "agents": [
    "codex",
    "cursor",
    "codebuddy",
    "claude-code"
  ],
  "skills": [
    "git",
    "integration-test"
  ],
  "tags": [
    "ue",
    "android"
  ],
  "skillProviders": [
    {
      "type": "folder",
      "path": "../../shared-skills"
    },
    {
      "type": "folder",
      "path": "../team-skills"
    }
  ]
}
```

See `pipebuilder-space-json-spec.md` for the complete fields and selection algorithm.

---

## 5. Workspace File Contract

### 5.1 File constraints

`<name>.code-workspace` must contain at least one folder. It supports a PipeSpace colocated with a project, a PipeSpace decoupled from project directories, and multi-project workspace files:

```json
{
  "folders": [
    {
      "path": "."
    },
    {
      "name": "engine-reference",
      "path": "../../engine-reference"
    }
  ],
  "settings": {}
}
```

`path: "."` means that the project is colocated with the PipeSpace root. Any other relative path means that the PipeSpace is decoupled from the project directory. Multiple folders are peer projects in the workspace file; PipeBuilder does not infer a primary project, reference status, writable/read-only status, or commit boundaries from array order. When such business constraints are required, a specific Skill or Space-level agent source must provide them.

PipeBuilder validates that:

- `folders` is a non-empty array with at least one item;
- `name` may be omitted; if omitted, it is derived from the directory basename of the folder path; if specified, it must be non-empty; all final names must be unique;
- `path` is non-empty and relative;
- every folder directory exists at build time;
- resolved paths are unique;
- the workspace JSON is valid.

PipeBuilder does not require the PipeSpace root itself to be a workspace folder, nor does it validate whether a folder is a Git repository.

### 5.2 Project path rule

PipeBuilder generates a neutral file from the workspace file:

```text
.pipebuilder/generated/workspace-rule.md
```

Its contents include:

- the PipeSpace name;
- the workspace filename;
- the declaration order, name, and relative path of every folder;
- the positional relationship between the `.` folder and external folders;
- the fact that the workspace file is the programmatic source of truth and the rule is only an agent-facing projection;
- the fact that `.pipebuilder/agents` and `.pipebuilder/skills` are Builder inputs and should not be modified unless the task explicitly requires it.

Each adapter projects the same semantics onto the platform's native rule surface. Local absolute paths must not be written into the rule, preserving PipeSpace portability. Agents such as Codex that do not directly consume `.code-workspace` receive the same folder inventory through native instruction files generated by the Builder.

---

## 6. Skill Providers and the Resolution Model

### 6.1 Provider priority

The effective Provider order is:

```text
1. implicit space-local provider: ./.pipebuilder/skills
2. pipespace.json skillProviders[0]
3. pipespace.json skillProviders[1]
4. ...
```

Earlier entries have higher priority. For Skills with the same name, only the first valid candidate is selected. Lower-priority candidates are recorded in the lock's `shadowedCandidates`; their directory trees are not merged.

### 6.2 Folder Provider

```json
{
  "type": "folder",
  "path": "../../shared-skills"
}
```

Each direct child directory of the Provider root is a Skill:

```text
../../shared-skills/
├── git/SKILL.md
├── ue-cli/SKILL.md
└── integration-test/SKILL.md
```

PipeBuilder does not recursively search arbitrary depths for `SKILL.md`.

### 6.3 Git Provider

The protocol reserves:

```json
{
  "type": "git",
  "url": "https://example.com/team/skills.git",
  "tag": "v2.1.0",
  "subdir": "skills"
}
```

`"branch": "main"` may be used instead of `tag`. Exactly one of `branch` and `tag` must be specified; the semantically ambiguous generic `ref` is not accepted. `subdir` may be omitted and defaults to `.`.

Git Provider behavior:

- use `.pipebuilder/cache/git/` in the current PipeSpace;
- resolve the branch or tag to an immutable commit;
- record the URL, selector type and value, commit, subdir, and Provider/Skill digests in the lock;
- maintain only a bare mirror and an immutable snapshot without `.git` in the cache, never a mutable working tree;
- with `--offline`, require and reuse the commit matching the lock and the corresponding immutable cache, and validate the snapshot digest;
- never write credentials into the manifest or lock.

The cache is ignored local Builder state. It is not recorded in the lock and is not removed by the default `clean`. Remote authentication is provided by a Git credential helper, an SSH agent, or the process environment. An unknown Provider type returns `PB006`; it must not be ignored or guessed.

---

## 7. Build phases

```text
1. Parse the CLI and PipeSpace root
2. For build/clean, acquire .pipebuilder/build.lock using exclusive creation; concurrent operations fail immediately
3. Read the required pipespace.json and validate its schema
4. Determine the canonical logical name from pipespace.json.name
5. Read <name>.code-workspace as derived from name
6. Resolve all folders and generate the workspace inventory IR
7. Index the implicit space-local and configured Skill Providers
8. Resolve same-name Skills by Provider priority
9. Select space-local, explicit, and tag-matched Skills
10. Parse the Skill common packages, Skill .pipe-agents, and .pipebuilder/agents
11. Build platform operations for configured agents
12. Check schemas, source-source conflicts, and path safety
13. Output the dry-run/build plan
14. Apply operations to each generated file using a same-directory temporary file and atomic replace
15. Delete Builder-owned artifacts present in the old lock but no longer generated by this build
16. Atomically write .pipebuilder/lock.json
17. Release build.lock
```

No writes are performed if any planning or validation step fails.

The initial release does not provide a transaction journal, an atomic cross-file commit, or automatic crash rollback. Each individual file write must be atomic. If the process is interrupted while applying multiple files, the last successful lock remains unchanged, and the next build regenerates every planned target from the current sources. When `build.lock` exists, PipeBuilder reports the PipeSpace as busy by default. A Human may delete a stale lock after confirming that the lock-owning process no longer exists.

---

## 8. In-Place Builds and Ownership

In-place builds use explicit source/target ownership. Humans edit only `.pipebuilder/agents`, `.pipebuilder/skills`, the manifest, the workspace file, and external Providers. Platform-target configuration and installed Skills are Builder-owned generated output.

### 8.1 Write rules

```text
Target in the current plan
  -> Created or fully replaced by PipeBuilder

Target present in the old lock but no longer generated
  -> Delete that Builder-owned artifact

Target absent from both the current plan and the old lock
  -> Do not read, modify, or delete it

Generated target modified by a Human
  -> Regenerate it from the source on the next build; the target is not a configuration source
```

For the initial migration, Humans must first move existing platform configuration into the corresponding native-layout source under `.pipebuilder/agents/<agent>/`. The Builder does not reverse-import configuration from targets.

Here, "corresponding native layout" includes the complete target-relative path. For example, an existing `.codex/config.toml` moves to `.pipebuilder/agents/codex/.codex/config.toml`, and an existing root `AGENTS.md` moves to `.pipebuilder/agents/codex/AGENTS.md`.

### 8.2 Prohibited behavior

PipeBuilder must not:

- recursively delete an entire `.cursor/`, `.codex/`, `.claude/`, or `.codebuddy/` directory;
- modify a target recorded in neither the plan nor the old lock;
- copy when the source and target resolve to the same real path;
- copy `.pipe-agents/` into a target Skill common package;
- write secret values into the lock.

### 8.3 Semantic merge

When multiple Builder sources contribute to any of the following targets, they must first be merged in memory according to platform semantics, after which the complete target file is generated:

- `AGENTS.md`;
- `.codex/config.toml`;
- `.codex/hooks.json`;
- `.claude/settings.json`;
- `.mcp.json`;
- Cursor hooks/MCP/config;
- `.codebuddy/settings.json`;
- `.codebuddy/mcp.json`.

These target files are managed in their entirety by the Builder; human-authored fields or comments in a target are not preserved. Identical definitions for the same semantic key may be deduplicated, while conflicting definitions fail. The behavior must not degrade to last-write-wins. If the initial release does not implement a particular semantic document, it must report an explicit unsupported error for that artifact.

---

## 9. Lock Contract

Use a single lock:

```text
.pipebuilder/lock.json
```

It records:

- input provenance;
- Provider resolution results;
- reasons for Skill selection;
- platform adapter versions;
- the workspace digest;
- generated-artifact ownership;
- the basis for clean/rebuild.

Example:

```json
{
  "schema": "pipebuilder-lock.v1",
  "builder": {
    "version": "0.1.0",
    "digest": "sha256:..."
  },
  "space": {
    "name": "my-harness-space",
    "root": ".",
    "manifestDigest": "sha256:...",
    "workspace": "my-harness-space.code-workspace",
    "workspaceDigest": "sha256:..."
  },
  "agents": [
    "codex",
    "cursor",
    "codebuddy",
    "claude-code"
  ],
  "providers": [],
  "skills": [],
  "artifacts": []
}
```

For deterministic builds, `generatedAt` may be recorded but must not participate in the reproducible digest.

---

## 10. CLI

```bash
# Build the current working directory by default
python3 pipebuilder.py build

# Build a specified PipeSpace
python3 pipebuilder.py build /path/to/my-harness-space

# Parse, validate, and print the plan without writing files
python3 pipebuilder.py check

# Emit a stable, machine-readable report for the same result
python3 pipebuilder.py check --format json

# Show Providers, Skill selections, shadowing, and platform targets
python3 pipebuilder.py explain

# Build the plan without writing files
python3 pipebuilder.py build --dry-run

# Remove only content proven by the lock to be PipeBuilder-managed
python3 pipebuilder.py clean

# Version
python3 pipebuilder.py --version
```

`check`, `explain`, `build --dry-run`, and the final reports from build/clean support `--format text|json`. JSON uses the versioned `pipebuilder-report.v1` schema for consumption by tests and automation. Error semantics are defined by stable diagnostic codes, so callers do not need to parse human-readable messages.

---

## 11. Python CLI Selection

### 11.1 Decision

The initial release uses a single `pipebuilder.py`. Rewriting the existing TypeScript Builder is permitted; code reuse is no longer the primary constraint.

PipeBuilder primarily parses manifests, traverses files, validates schemas, generates text, and maintains a lock. This type of configuration-compilation CLI aligns well with the Python standard library. All generated results are native static platform configuration and require no additional PipeBuilder runtime.

### 11.2 Comparison

| Dimension | Single Python file | Single MJS file |
| --- | --- | --- |
| CLI standard library | `argparse`, `pathlib`, `dataclasses`, `subprocess`, `hashlib`, and `tempfile` directly cover the core | The Node standard library can also implement it, but the overall environment is more oriented toward package/runtime ecosystems |
| JSON | Complete standard-library read/write support | Complete standard-library read/write support |
| TOML | Python 3.11+ uses `tomllib`; Python 3.7-3.10 uses an embedded single-file compatibility parser; controlled rendering remains a Builder responsibility | No dependency on a third-party TOML package |
| YAML frontmatter | A constrained small parser implements only what the protocol requires | Also requires a constrained small parser |
| Single-file built-in adapters | Organized directly with classes and a registry | Organized directly with classes and a registry |
| Future adapter plugins | `importlib` | `import()` |
| Testing | The standard library is sufficient for a subprocess-driven Python E2E runner | Typically requires a custom runner or package tooling |
| Platform configuration generation | Deterministic generation of Markdown, JSON, TOML, and directory trees | Can generate the same outputs, but TOML requires an additional implementation or dependency |
| Distribution | One `.py` file with no pip dependencies | One `.mjs` file with no npm dependencies |

Python 3.11+'s `tomllib`, or the embedded single-file compatibility parser for Python 3.7-3.10, reads Codex TOML sources. The target `.codex/config.toml` is managed in its entirety by the Builder, so the implementation must provide a deterministic TOML renderer and fail when multiple sources conflict on a semantic key.

### 11.3 Python baseline

Recommended initial requirement:

```text
Python >= 3.7
```

The implementation uses only the Python standard library and has no dependency on pip packages. Retain the following at the top of the file:

```python
#!/usr/bin/env python3
```

On macOS/Linux, it can be distributed directly:

```bash
chmod +x pipebuilder.py
./pipebuilder.py build
```

On Windows, use:

```powershell
py -3 pipebuilder.py build
```

The release script remains a single file that runs on the Python 3.7+ standard library. If older hosts must be supported in the future, evaluate a standalone executable or a rewrite in Go/Rust.

The protocol must remain independent of the implementation language. Therefore, `pipespace.json`, Skill packages, the workspace file, and the lock must not contain Python-specific semantics.

---

## 12. Adapter Plugin Evolution

The initial release includes four built-in adapters because:

- a single file can run independently;
- platform behavior can be validated through the same complete PipeSpace E2E suite;
- schemas and security policies are not affected by arbitrary plugin code;
- the protocol is easier to stabilize during migration.

The following may be permitted in the future:

```json
{
  "agents": [
    "codex",
    {
      "id": "windsurf",
      "adapter": {
        "type": "module",
        "path": ".pipebuilder/adapters/windsurf.py"
      }
    }
  ]
}
```

However, plugins are an explicit second-phase capability. When an external adapter is enabled, the PipeSpace no longer has the security property of depending on only one trusted PipeBuilder file. Therefore, PipeBuilder must:

- display a trust prompt;
- record the plugin's real path and digest in the lock;
- prohibit direct execution of adapters from network URLs;
- restrict the adapter API to generating build operations, without direct file writes;
- perform centralized ownership and conflict checks in core before applying operations.

---

## 13. Retained and Removed THarness Builder Capabilities

| THarness capability | PipeBuilder handling |
| --- | --- |
| Explicit Skill list | Retained as `skills` |
| PipeSpace/Skill tag matching | Retained; unioned with the explicit list, which takes precedence |
| Shared Skill | Generalized into `skillProviders` |
| PipeSpace-local Skill | `.pipebuilder/skills`, implicitly highest priority |
| Same-name PipeSpace Skill overrides shared Skill | Generalized into Provider priority and shadowing |
| Flat `SKILL.md` package | Becomes the only standard layout |
| Nested `skill/SKILL.md` | Recognized only by migration tooling; removed from the formal protocol |
| Skill-level agent files (formerly tagents) | Moved to `<skill>/.pipe-agents/<agent>` |
| Space-level agent files (formerly tagents) | Moved to `<space-root>/.pipebuilder/agents/<agent>` and converted to the platform-native layout |
| Target adapters | Retained; expanded to four agents in the initial release |
| Cursor rule validation | Retained |
| Artifact/source lock | Simplified to `.pipebuilder/lock.json` for provenance, rebuild, and clean |
| Command argv/no-shell | Removed; business execution belongs to Skills, not the Builder build phase |
| Workspace source publishing | Removed |
| Workspace validation | Changed to read the final `.code-workspace` directly |
| Workspace folder inventory rule | Retained as a core build phase; does not infer project roles |
| PipeSpace registry | Removed |
| THarness repository-root derivation | Removed |
| Fixed shared-skills path | Removed |
| Centralized workspace generation | Removed |
| Built-in/command dual mode | Removed; PipeBuilder has only configuration-compilation mode |
| `.harness-space.yaml` | Removed |
| `.harness-lock.yaml` | Replaced by `.pipebuilder/lock.json` |

---

## 14. Migration Plan

### Phase 1: Protocol and Cursor parity

- add a standalone `pipebuilder.py`;
- implement the PipeSpace name/workspace-file contract;
- implement `pipespace.json`;
- implement the folder Skill Provider;
- implement explicit plus tag-based selection;
- implement the standard Skill package and `.pipe-agents`;
- migrate the current Cursor rules/commands/files;
- implement the in-place ownership lock;
- migrate the current built-in fixtures into Python black-box E2E cases.

### Phase 2: Initial four-agent release

- minimal support for Codex Skills, generated `AGENTS.md`, configuration, hooks, and rules;
- the complete initial Cursor adapter;
- CodeBuddy Skills, commands, agents, and settings hooks;
- Claude Code Skills, rules, agents, command compatibility, settings hooks, and MCP;
- a full-capability Skill on all four platforms, complete PipeSpace E2E tests, and repeated-build tests;
- E2E coverage proving that Human-owned sources remain unchanged and Builder-owned targets are regenerated.

### Phase 3: Standalone release

- a standalone PipeBuilder Git repository or single-file release;
- SHA256/checksum and release notes;
- optional self-update, with no automatic network access by default;
- evaluation of the Git Skill Provider;
- evaluation of the adapter plugin API.

---

## 15. Acceptance Criteria

The initial release is complete only when all of the following are satisfied:

1. After `pipebuilder.py` is copied to any location, it can build any protocol-compliant PipeSpace.
2. It does not depend on the THarness repository layout.
3. It does not depend on `pip install` or `npm install`.
4. `<pipespace.json.name>.code-workspace` remains byte-for-byte unchanged before and after a build.
5. Two consecutive builds from the same inputs produce identical generated content and stable lock fields.
6. All four platforms can discover the same standard Skill.
7. A Skill's `.pipe-agents/` does not leak into the common package.
8. Explicit `skills` and tags work together, with explicit selection recorded as higher priority.
9. Resolution of same-name Skills across multiple Providers is stable and explainable.
10. Platform-native sources in `.pipebuilder/agents` fully generate the corresponding platform configuration; after a target is modified directly, rebuild restores the source-defined content.
11. `clean` deletes only PipeBuilder-owned content.
12. `.code-workspace` supports `path: "."`, external relative directories, and multiple folders.
13. The workspace rule expresses the same folder inventory on all four platforms without inferring project roles or permissions.
14. The lock traces every generated artifact to its Provider, Skill, source file, and digest.
15. `.pipebuilder/agents`, `.pipebuilder/skills`, and Skill-level `.pipe-agents/` remain unchanged across build/clean.
16. The root `AGENTS.md` is generated in full from Builder sources and the canonical workspace rule; Codex does not need to read `.code-workspace` or run a PipeBuilder runtime hook.
17. Concurrent build/clean operations on the same PipeSpace fail fast because of `build.lock`; each individual target file uses atomic replace.
18. PipeBuilder recognizes only the canonical namespace. When it detects a legacy THarness layout, it returns `PB015` rather than silently reading or merging it.

---

## 16. Final Positioning

```text
PipeBuilder is a portable compiler that builds a PipeSpace
in place as a deterministic task-specific pipeline root for multiple coding agents.
```

Definition:

> PipeBuilder is a cross-agent PipeSpace compiler distributed as a single Python file with no dependency on a central repository. A PipeSpace directory serves as both the build input and the task-specific agent pipeline execution root. Humans maintain the final workspace file; PipeBuilder resolves standard Skills from multiple Skill Providers, carries agent-specific sources in Space-level `.pipebuilder/agents` and Skill-level `.pipe-agents`, generates Builder-owned native capabilities in place through four platform adapters, and uses a lock to record complete provenance and generated results.
