# PipeBuilder PipeSpace and Skill Provider Specification

Status: implemented
Schema: `pipespace.v1`
Date: 2026-07-14

This document defines the normative behavior of PipeSpace identity, `pipespace.json`, the workspace file, Skill packages, Skill Providers, Skill selection, and the lock.

When a PipeSpace contains nested PipeSpaces, the same commands discover and orchestrate them automatically. Discovery is configured by the optional `children` field in this schema; there is no separate hierarchy manifest or command family.

---

## 1. PipeSpace identity

Given this PipeSpace root:

```text
/workspace/local-checkout-17/
```

Its `pipespace.json` is:

```json
{
  "schema": "pipespace.v1",
  "name": "my-pipe-space",
  "agents": ["codex", "cursor", "codebuddy", "claude-code"],
  "skills": [],
  "tags": [],
  "skillProviders": [],
  "children": {"scanDepth": 3}
}
```

The canonical logical name is:

```text
my-pipe-space
```

`pipespace.json.name` is the sole source of truth for PipeSpace identity and must match:

```text
^[a-z][a-z0-9-]*$
```

The following workspace file must exist:

```text
my-pipe-space.code-workspace
```

The directory basename neither contributes to identity derivation nor is compared with `name`. Moving or renaming the PipeSpace root does not change its logical identity. To create a new PipeSpace by copying the directory, explicitly change `name` and rename the workspace file accordingly. Workspace folder names do not have to match the PipeSpace name.

Case-sensitive and case-insensitive file systems use the same logical-name comparison. Target-path conflict comparison is case-insensitive by default on Windows and macOS; on an explicitly case-sensitive file system, portability collisions should still be diagnosed separately.

---

## 2. Is `pipespace.json` Required?

`pipespace.json` is required. If it is missing, the build fails immediately; configuration is never inferred from the directory name, workspace filename, or an existing lock.

The following fields must be explicitly present:

- `schema`;
- `name`;
- `agents`;
- `skills`;
- `tags`;
- `skillProviders`.

An explicit empty array means that there is currently no configuration of that kind. This keeps the manifest as the stable entry point for identity, schema version, and build selection. Low-friction creation is provided by `pipebuilder init`, not by omitting the manifest.

For the recommended project-local bootstrap, `init` accepts paths relative to the new
PipeSpace:

```bash
python3 pipebuilder.py init <project>/pipespaces/<project>-dev \
  --name <project>-dev \
  --project ../.. \
  --shared-skills ../shared/skills
```

`--project` generates `pipeline: .` and `project: <path>` workspace folders.
`--shared-skills` requires `<path>/pipebuilder/SKILL.md`, adds that folder as a Provider,
and selects `pipebuilder`. Both paths must be relative and resolve to existing directories.
When the required files already exist, `init` validates that they match the requested
bootstrap configuration and does not overwrite them. Omitting both options preserves the
minimal empty scaffold.

---

## 3. Complete Example

```json
{
  "schema": "pipespace.v1",
  "name": "ue-gameplay",
  "description": "UE gameplay development PipeSpace",
  "agents": [
    "codex",
    "cursor",
    "codebuddy",
    "claude-code"
  ],
  "skills": [
    "git",
    "ue-cli",
    "integration-test-pie"
  ],
  "tags": [
    "ue",
    "gameplay"
  ],
  "skillProviders": [
    {
      "type": "folder",
      "path": "../../shared-skills"
    },
    {
      "type": "folder",
      "path": "../game-team-skills"
    }
  ],
  "children": {
    "scanDepth": 3
  }
}
```

In v1, unknown top-level fields are errors by default so that spelling mistakes cannot fail silently. Future schema versions may add fields.

---

## 4. Top-Level Fields

| Field | Type | Required | Default | Semantics |
| --- | --- | --- | --- | --- |
| `schema` | string | yes | none | Must be `pipespace.v1` |
| `name` | string | yes | none | PipeSpace canonical logical name; not derived from the directory name |
| `description` | string | no | none | Human-facing description |
| `agents` | string[] | yes | none | Platforms to generate, preserving declaration order |
| `skills` | string[] | yes | none | Explicit Skill list; use `[]` when empty |
| `tags` | string[] | yes | none | PipeSpace tags; use `[]` when empty |
| `skillProviders` | object[] | yes | none | External Skill sources; use `[]` when empty, with priority descending in array order |
| `children` | object | no | `{"scanDepth": 3}` | Nested PipeSpace discovery settings |

Array values must be unique. Duplicate values are errors rather than being silently deduplicated, so configuration problems remain visible.

### 4.1 `children`

`children` accepts exactly one field:

```json
{
  "children": {
    "scanDepth": 3
  }
}
```

`scanDepth` must be an integer from `0` through `32`. It counts directory edges below the current PipeSpace root. The default is `3`; `0` disables child discovery and makes every command root-only.

PipeBuilder searches deterministically for nested `pipespace.json` files up to that depth. It skips hidden directories, Agent and Builder generated roots, `.git`, and symlinked directories. Each discovered directory remains an independent PipeSpace with its own manifest, workspace, ownership lock, and outputs. Nested children are supported as long as they fall within the root's configured scan depth.

The public commands do not have separate hierarchy variants:

```text
check
explain
build
verify
clean
```

When children are found, `check`, `explain`, and `build --dry-run` plan every member before writes. `build` applies members in root-to-child path order and verifies that an earlier Provider post command did not stale a later member's plan. `verify` checks the aggregate receipt and every member lock and artifact. `clean` preflights every member before deleting anything, then cleans in reverse child-to-root order. A failed or interrupted hierarchy operation records a journal under the root `.pipebuilder` directory so rerunning the same unified command can converge.

For root-only operation, successful JSON `verify` returns
`details.receiptDigest` as the digest of the exact verified `.pipebuilder/lock.json` bytes.
No one-member aggregate `tree-lock.json` is created. When discovered children exist, the same
field instead anchors the required aggregate `.pipebuilder/tree-lock.json`; consumers must bind
the mode declared by their input contract and must not treat the two receipt leaves as fallback
alternatives.

---

## 5. `agents`

Allowed v1 values:

```json
[
  "codex",
  "cursor",
  "codebuddy",
  "claude-code"
]
```

Constraints:

- at least one entry is required;
- duplicates are not allowed;
- unknown values are errors;
- PipeBuilder reads only the selected Agent's Skill `.pipe-agents/<agent>` and PipeSpace `.pipebuilder/agents/<agent>`;
- after an Agent is removed, rebuild cleans that adapter's stale generated artifacts recorded in the lock without deleting Human-owned sources.

Agent declaration order is used for diagnostics and lock presentation; it must not affect cross-Agent semantics.

---

## 6. Skill Provider

### 6.1 Provider IR

Logical interface:

```text
Provider.resolve() -> immutable provider snapshot
Provider.listSkills() -> skill descriptors
Provider.openSkill(name) -> skill package
```

Core is independent of whether the source is a folder, Git repository, or registry. Every Provider must return a consistent representation containing:

- provider id;
- source description;
- immutable revision/digest;
- Skill name;
- Skill root;
- Skill digest.

### 6.2 Implicit Space-Local Provider

At the highest priority, PipeBuilder always checks:

```text
<space-root>/.pipebuilder/skills
```

If the directory does not exist, there is no local Provider record. PipeBuilder does not
materialize an empty source or preserve an unused `space-local` placeholder in the lock.

Its logical id is fixed:

```text
space-local
```

All valid Skills in this Provider are selected, preserving the semantics of legacy PipeSpace-local Skills.

### 6.3 Folder Provider

```json
{
  "type": "folder",
  "path": "../../shared-skills",
  "subdir": "."
}
```

Constraints:

- `type` must be `folder`;
- `path` must be a non-empty string;
- `subdir` is optional and defaults to `.`; it identifies the Skill root relative to the Provider source root;
- the manifest must use a relative path;
- the path is resolved relative to the PipeSpace root;
- at build time, it must resolve to an existing directory;
- the Provider root must not be inside a PipeBuilder-generated target;
- the Provider realpath and directory-content digest are written to the lock;
- only direct subdirectories of the Provider root are Skill candidates.

Folder and Git Providers may instead build their Skill Provider root before projection:

```json
{
  "type": "folder",
  "path": "../rounditer",
  "build": {
    "args": ["node", "build.mjs"],
    "output": "dist/skills"
  }
}
```

`build` accepts exactly `args` and `output`. `args` is executed without a shell from the
Provider source root. `output` is a safe relative POSIX directory beneath that source root;
after a zero exit it becomes the Provider root, with optional `subdir` resolved beneath it.
PipeBuilder expands `{sourceRoot}` and `{buildOutput}` and also exposes them as
`PIPE_SKILL_SOURCE_ROOT` and `PIPE_SKILL_BUILD_OUTPUT`. A real `build` runs the Skill Builder
before Skill discovery. `check`, `explain`, and `build --dry-run` never execute it and inspect
the currently existing output. A fresh source without that output must run `build` first;
later `check` calls remain read-only. Builder success defines semantic build success; PipeBuilder
only requires exit status zero, validates the output as a Provider, and binds its exact Skill
and projected artifact digests in the normal ownership lock. `verify` does not rerun the Builder;
it compares the current declared output digest and installed projections with that lock. `build` and `command` are mutually
exclusive for one Provider.
Each selected Skill projection root is closed: its complete regular-file set must equal the locked
`common-skill` targets. Extra or unsafe entries fail `verify`; a real rebuild removes stale files
under that generated root before publishing the new lock.

Both Folder Providers and Git Providers may include a post command:

```json
{
  "type": "folder",
  "path": "../rounditer",
  "subdir": "skills",
  "command": {
    "cwd": ".",
    "args": ["node", "build.mjs", "--pipe-post", "--output", "{pipespaceRoot}", "--driver", "webgame"]
  }
}
```

`cwd` is relative to the Provider source root and defaults to `.`. `args` is a non-empty string array that is executed without a shell. PipeBuilder expands `{pipespaceRoot}`, `{sourceRoot}`, and `{providerRoot}` in every argument and exposes the same paths as `PIPE_SPACE_ROOT`, `PIPE_PROVIDER_SOURCE_ROOT`, and `PIPE_PROVIDER_ROOT`. A normal `build` invokes post commands in Provider order after PipeBuilder's own outputs have been written. `check`, `explain`, and `build --dry-run` only display them and do not execute them. `build --require-no-post-commands` fails with `PB018` before any build output, ownership lock, or hierarchy journal is written when any selected Provider in the planned PipeSpace tree declares a post command; it never silently skips a command.

Absolute paths are not allowed in the manifest, which keeps the PipeSpace movable. A genuine need for a machine-local path should be addressed through the external directory layout, a symlink, or a future local-override mechanism.

### 6.4 Git Provider

Branch form:

```json
{
  "type": "git",
  "url": "https://example.com/team/skills.git",
  "branch": "main",
  "subdir": "skills"
}
```

Tag form:

```json
{
  "type": "git",
  "url": "git@example.com:team/skills.git",
  "tag": "v2.1.0"
}
```

Constraints:

- `url` must be a non-empty Git URL; development and offline test inputs may also use a local repository path relative to the PipeSpace root;
- exactly one of `branch` and `tag` must be specified; a generic `ref` is not part of the schema;
- `subdir` may be omitted and defaults to `.`; it must be a safe relative POSIX path;
- the URL must not embed an HTTP(S) username, password, query credential, or fragment; authentication is handled by the Git credential helper, SSH agent, or environment;
- the cache is fixed at `.pipebuilder/cache/git/` within the current PipeSpace. Bare mirrors and immutable snapshots are isolated by URL and commit. This directory contains ignored, machine-local Builder state and is not recorded in the lock;
- online resolution updates the cache mirror, resolves the branch or tag to a commit, and creates a symlink-free immutable snapshot from that commit;
- `--offline` does not access the origin and requires a matching lock. It reuses the recorded commit and validates the cache snapshot digest. An unavailable lock, cache, commit, or subdirectory returns `PB005`; digest drift returns `PB010`;
- the lock records the portable URL, `branch` or `tag`, commit, subdirectory, Provider digest, and each Skill digest. It does not record credentials or the machine-local absolute cache path;
- a Git Provider worktree must not appear inside the PipeSpace. Bare mirrors and immutable snapshots without `.git` under `.pipebuilder/cache/git/` are the only exceptions.

### 6.5 Provider Priority

From highest to lowest:

```text
space-local
skillProviders[0]
skillProviders[1]
...
```

For each logical Skill name, the first valid candidate is selected. Other candidates with the same name do not participate in a merge:

```json
{
  "name": "git",
  "provider": "space-local",
  "shadowedCandidates": [
    {
      "provider": "folder:../../shared-skills",
      "path": "../../shared-skills/git"
    }
  ]
}
```

Shadowing by a same-named candidate produces a warning by default and must be shown by `explain`.

---

## 7. Skill Package

### 7.1 Standard Structure

```text
<provider-root>/<skill-name>/
├── SKILL.md                     # required
├── scripts/                     # optional
├── references/                  # optional
├── assets/                      # optional
├── agents/                      # other content allowed by the Agent Skills standard
└── .pipe-agents/                # PipeBuilder extension, optional
    ├── codex/
    ├── cursor/
    ├── codebuddy/
    └── claude-code/
```

Except for `.pipe-agents/`, the entire Skill root belongs to the common package. Copying preserves the directory structure and excludes:

```text
.pipe-agents/
.DS_Store
```

Do not exclude all hidden directories indiscriminately, because standard Skill content may legitimately use other hidden directories.

### 7.2 `SKILL.md`

YAML frontmatter is required. PipeBuilder v1 recognizes at least:

```yaml
---
name: ue-cli
description: Operate Unreal Engine command-line workflows.
tags:
  - ue
  - build
---
```

Constraints:

- `name` must be present;
- `description` must be present and non-empty;
- `name` must match the Skill directory name;
- `name` must match `^[a-z][a-z0-9-]*$`;
- `tags` is optional and must be a list of unique strings;
- unrecognized frontmatter fields are preserved verbatim;
- PipeBuilder does not rewrite common frontmatter for different platforms.

### 7.3 `.pipe-agents`

`.pipe-agents/<agent>/` is the virtual target root for the corresponding Agent. It preserves the platform-native target-relative paths inside and does not define another set of cross-platform generic subdirectories. For example:

```text
.pipe-agents/
├── codex/
│   ├── AGENTS.md
│   └── .codex/
│       ├── config.toml
│       ├── hooks.json
│       └── rules/
├── cursor/
│   └── .cursor/
│       ├── rules/
│       └── commands/
├── codebuddy/
│   └── .codebuddy/
│       ├── settings.json
│       ├── mcp.json
│       └── agents/
└── claude-code/
    ├── CLAUDE.md
    ├── .mcp.json
    └── .claude/
        ├── settings.json
        ├── rules/
        └── agents/
```

The example shows only common surfaces. Exact filenames, schemas, and target mappings for each adapter are defined by the Adapter specification. Encountering a native file or directory that the adapter does not support fails by default and reports the Agent, Skill, and path; it must not be ignored.

Specification examples and dynamic cases do not use one oversized Skill to cover every behavior. See the [PipeBuilder Skill Input Catalog](pipebuilder-skill-fixture-catalog.md) for the grouping of portable packages, four-platform full-capability Skills, Provider resolution, invalid and security cases, and live Codex scenarios.

Skill-level Agent sources may appear only under `.pipe-agents/<agent>/` at the Skill root. The specification provides no generic `files/` escape hatch and defines no top-level `rules/`, `resources/`, or `tagents/`.

---

## 8. Space-level `.pipebuilder/agents`

PipeSpace-level Agent-specific inputs are located at:

```text
.pipebuilder/agents/<agent>/...
```

Like Skill `.pipe-agents/<agent>`, it is a virtual target root for the corresponding Agent:

```text
.pipebuilder/agents/codex/AGENTS.md
.pipebuilder/agents/codex/.codex/config.toml
.pipebuilder/agents/cursor/.cursor/rules/
.pipebuilder/agents/codebuddy/.codebuddy/agents/
.pipebuilder/agents/claude-code/CLAUDE.md
.pipebuilder/agents/claude-code/.claude/settings.json
```

PipeSpace `.pipebuilder/agents` and Skill `.pipe-agents` are two distinct scopes; a scope does not itself grant overwrite rights. Artifacts that support additive merging are merged according to adapter semantics. Other conflicts on the same semantic key fail by default.

This scope is for PipeSpace-level capabilities that cannot reasonably belong to a particular Skill, such as project instructions, additional hooks, PipeSpace-specific commands, and global validation gates. Files here are Human-owned sources. The corresponding root-level `AGENTS.md`, `CLAUDE.md`, and `.mcp.json`, together with targets under `.codex/`, `.cursor/`, `.codebuddy/`, and `.claude/` that are included in the plan, are Builder-owned outputs.

---

## 9. Skill Selection Algorithm

### 9.1 Inputs

```text
space-local Skill names
explicit pipespace.json.skills
pipespace.json.tags
resolved Provider index
```

### 9.2 Algorithm

1. Resolve one valid candidate for each Skill name according to Provider priority.
2. Add every Skill from `space-local` to the result with `selectedBy = space-local`.
3. Select resolved candidates in `skills` declaration order:
   - if the candidate does not exist, report an error;
   - if it has already been selected from space-local, promote it to `selectedBy = skills` while also recording space-local;
   - otherwise, add it with `selectedBy = skills`.
4. For resolved candidates that have not been explicitly selected, compute the intersection of the Skill tags and PipeSpace tags:
   - if the intersection is non-empty, add the candidate with `selectedBy = tags`;
   - if the intersection is empty, do not select it.
5. For a Skill matched by both the explicit list and tags, retain `selectedBy = skills` and record `matchedTags`.
6. Final installation order:
   - explicit Skills in manifest order;
   - space-local-only Skills by Skill name;
   - tags-only Skills by Skill name.

Installation order affects only deterministic output and diagnostics; it does not grant silent overwrite rights.

### 9.3 Example

```json
{
  "skills": ["git"],
  "tags": ["ue"]
}
```

Provider contents:

```text
git tags=[workflow]
ue-cli tags=[ue,build]
trace-analyze tags=[performance]
```

Result:

```text
git       selectedBy=skills matchedTags=[]
ue-cli    selectedBy=tags   matchedTags=[ue]
```

`trace-analyze` is not selected.

---

## 10. Workspace File

### 10.1 Human-Owned Source

The workspace file has no independent path field. Its path is derived deterministically from the required `pipespace.json.name`:

```text
<space-root>/<pipespace.json.name>.code-workspace
```

This makes the manifest the sole source of truth for PipeSpace identity while avoiding searches for, or guesses among, multiple `.code-workspace` files. The workspace file remains the source of truth for project names, paths, and ordering.

The workspace file supports three common topologies:

```json
{
  "folders": [
    {"path": "."},
    {"path": "../project"},
    {"name": "custom-project-name", "path": "../another-project"}
  ]
}
```

`path: "."` means that the project is colocated with the PipeSpace root; other relative paths represent directory decoupling. Both forms may appear together. `name` is optional. When omitted, it uses the basename of the directory identified by `path` (`.` maps to the PipeSpace root's basename); when explicitly configured, it must be a non-empty string. `folders` must be an array containing at least one item. Final folder names must be unique, and each path must be non-empty, relative, unique after resolution, and point to an existing directory at build time.

### 10.2 Folder Semantics

PipeBuilder preserves the declaration order of `folders`, but does not infer primary/reference status, writable/read-only status, validation boundaries, or commit boundaries from that order. All folders are peers in the workspace file. A particular Skill may read the generated workspace rule and define its own project-selection convention, but that convention is not part of PipeBuilder core.

### 10.3 Generated Workspace Rule Model

Intermediate representation:

```json
{
  "space": "my-pipe-space",
  "workspace": "my-pipe-space.code-workspace",
  "folders": [
    {
      "name": "game-project",
      "path": "."
    },
    {
      "name": "engine-project",
      "path": "../engine-project"
    }
  ]
}
```

Each Agent adapter renders this IR. Programs must not reconstruct it by parsing the rendered Markdown or MDC.

---

## 11. Diagnostics

Every diagnostic contains at least:

```text
level
code
message
source paths
target path or semantic key
suggested action
```

Recommended stable error codes:

```text
PB001 invalid-manifest
PB002 invalid-space-name
PB003 workspace-not-found
PB004 invalid-workspace
PB005 provider-not-found
PB006 unsupported-provider
PB007 skill-not-found
PB008 invalid-skill
PB009 unsupported-agent-artifact
PB010 target-conflict
PB011 unsafe-path
PB013 build-busy
PB014 stale-build-lock
PB015 legacy-layout-detected
PB016 provider-post-command-failed
PB017 invalid-pipespace-hierarchy
PB018 provider-post-command-forbidden
```

`PB012` is reserved as an early draft number but is not part of the stable `pipespace.v1` contract. The manifest accepts only the four built-in Agents, and `PB001` rejects an unknown Agent before adapter dispatch, so an artificial failure path must not be created for `PB012`.

`PB015` identifies legacy THarness layouts such as `tagents/`, Space-root `.pipe-agents/`, `private/`, `.harness-space.yaml`, `.harness-lock.yaml`, or a workspace source template. PipeBuilder v1 does not read both layouts, merge them automatically, or rename them in place during build. Migration is performed by a separate tool or a maintenance Agent acting on Human direction.

`PB016` reports a Skill Builder or Provider post command that cannot start, omits its declared output, has an invalid working directory, or exits with a nonzero status. A nonzero Skill Builder diagnostic includes up to 1000 characters from stderr (or stdout when stderr is empty), so the user sees the actual Builder guidance instead of only an exit code. `PB017` reports nested PipeSpace discovery, aggregate-state, stale-plan, and member-state errors. `PB018` reports that fail-closed build mode found at least one configured Provider post command; its `sources` identify the PipeSpace and Provider offenders.

When the CLI uses `--format json`, diagnostics are wrapped in the versioned `pipebuilder-report.v1`. Tests and automation must depend on `code` and structured fields rather than parsing human-readable messages. See the [PipeBuilder Python E2E Test Architecture](pipebuilder-test-architecture.md) for E2E input and golden-expectation rules.

---

## 12. Simplified Lock and Concurrency Requirements

The lock path is fixed:

```text
.pipebuilder/lock.json
```

The lock records at least:

- the PipeBuilder version and its own digest;
- the manifest path and digest;
- the workspace-file path and digest;
- Agent ids and adapter versions;
- Provider configuration, realpath, and snapshot/digest;
- each Skill's Provider, source, digest, `selectedBy`, `matchedTags`, and shadowed candidates;
- each artifact's source, logical type, target, semantic key, operation, and digest;
- Adapter capability status and structured risks for surfaces such as automatically executed hooks and Codex rules;
- an optional generation timestamp.

Source paths in the lock should preferentially be PipeSpace-relative or Provider-relative. A non-portable absolute realpath may be used for machine-local diagnostics, but it must be separate from the portable identity and must not contribute to the reproducible digest.

Platform target configurations are managed in their entirety by the Builder; the lock does not perform ownership merging for Human-owned fields inside a target. At the start of build and clean, `.pipebuilder/build.lock` is acquired through exclusive creation. If the file already exists, the operation returns `PB013` instead of waiting for the concurrent operation. v1 provides neither a transaction journal nor cross-file rollback. Each target file is written through a temporary file and atomic replacement, and `lock.json` is written last.

An abnormal process exit may leave a stale `build.lock`. PipeBuilder reports `PB014` and displays its pid, host, and startedAt values. A human deletes the file only after confirming that the original process has ended. If a build is interrupted while applying multiple files, rerun build to regenerate every planned target from its source.

---

## 13. Path Safety

Every write target must:

- be relative to the PipeSpace root;
- remain within the PipeSpace root after normalization;
- not escape the PipeSpace root through a symlink or junction;
- not point to a Provider source;
- not point to Human-owned PipeSpace build inputs: `.pipebuilder/agents/` or `.pipebuilder/skills/`;
- not point to the workspace file or `pipespace.json`;
- allow only core operations to write `.pipebuilder/generated/`, `lock.json`, and `build.lock`;
- undergo drive and UNC checks on Windows;
- have its real parent path checked before application.

Provider sources and projects referenced by the workspace file may be read from outside the PipeSpace root; writes are always restricted to the PipeSpace root.
