# PipeBuilder

[English](README.md) | [Simplified Chinese](README.zh-CN.md)

[![E2E](https://github.com/aikenc/pipebuilder/actions/workflows/e2e.yml/badge.svg)](https://github.com/aikenc/pipebuilder/actions/workflows/e2e.yml)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Reuse team capabilities across AI coding agents and build task-specific pipeline spaces.

AI coding agents such as Codex, Cursor, and Claude Code use different conventions for Skills,
Rules, Hooks, MCP, and workspaces. Teams repeatedly adapt the same capabilities, and those
copies drift into inconsistent configuration and behavior over time.

A single `<project>` also needs different agent capabilities for feature development, bug
fixing, code review, and other tasks. Task-specific capabilities should not all load at once.
Putting every configuration in the project root expands context, creates conflicts, and can
run unrelated Hooks during the wrong task.

PipeBuilder addresses both problems:

- **Reuse one capability across agents**: a standard Skill is shared across platforms, while
  platform-native Rules, Hooks, Commands, Agents, and MCP configuration can ship in the same
  capability pack.
- **Give one project multiple agent pipelines**: each task pipeline composes only the agents
  and capabilities it needs while referencing the same project.
- **Reuse and version team capabilities through Skill Providers**: a Skill Provider can be a
  local folder or a Git repository, so teams can share capability packs locally or pin
  repository versions.
- **Generate platform-native configuration**: agents do not need to understand a PipeBuilder
  protocol. Build output remains native files such as `AGENTS.md`, `CLAUDE.md`, `.cursor/`,
  and `.claude/`.

A **PipeSpace** is a task-specific agent pipeline root/space decoupled from `<project>`. It
references one or more project folders through a workspace file and carries the configuration
generated for that pipeline. It is not a copy of the project.

## One Project, Multiple Agent Pipelines

`<project>` is the business-code entity. Feature development, bug fixing, and code review can
each use a separate task pipeline:

```text
team-workspace/
├── project/                         # the same project
├── shared-skills/                   # reusable team capability packs
└── pipespaces/
    ├── feature-development/         # implementation and testing capabilities
    ├── bugfix-review/               # diagnosis and review capabilities
    └── release-maintenance/         # build and release capabilities
```

Each PipeSpace can select a different combination of Skills, Rules, Hooks, MCP, and agents.
Its `.code-workspace` file references the PipeSpace itself and one or more project folders, so
pipeline configuration does not have to live in the project.

A local folder or Git repository that supplies capability packs is a **Skill Provider**.

> A PipeSpace separates agent configuration, context, and pipeline composition; it does not
> isolate code writes. When multiple agents modify the same project in parallel, continue to
> use Git branches, worktrees, or independent clones.

## Reuse One Capability Across Agents

A capability pack has two parts:

```text
shared-skills/bugfix-review/
├── SKILL.md                          # standard Skill shared by agents
├── scripts/
├── references/
└── .pipe-agents/                    # optional platform-native extensions
    ├── codex/AGENTS.md
    ├── cursor/.cursor/rules/
    ├── codebuddy/.codebuddy/settings.json
    └── claude-code/.claude/settings.json
```

- `SKILL.md`, scripts, and references are portable and install into each platform's standard
  Skill directory.
- `.pipe-agents/<agent>/` preserves the native directory and format for that platform. Its
  Adapter merges those files into the target PipeSpace.
- PipeBuilder does not claim to translate one Rule or Hook losslessly across every platform.
  It lets one capability pack carry both a standard Skill and the necessary native extensions.

Teams can therefore select and version complete capability packs instead of maintaining
separate platform configuration scattered across projects.

## Quick Start in 60 Seconds

Runtime requires only Python 3.7+ and the single `pipebuilder.py` file. Git is required only
when using a Git Skill Provider. No third-party Python packages are required.

```bash
curl -O https://raw.githubusercontent.com/aikenc/pipebuilder/main/pipebuilder.py
python3 pipebuilder.py --version

python3 pipebuilder.py init ./demo-space
python3 pipebuilder.py check ./demo-space
python3 pipebuilder.py build ./demo-space --dry-run
python3 pipebuilder.py build ./demo-space
```

`init` creates an empty scaffold with no external Skills:

```text
demo-space/
├── pipespace.json
└── demo-space.code-workspace
```

For a structured build plan, run
`python3 pipebuilder.py explain ./demo-space --format json`. To try capability selection and
cross-agent projection, continue with the multi-pipeline team example below.

## Run the One-Project, Multiple-Pipelines Example

The repository's
[examples/multi-pipeline-project](examples/multi-pipeline-project)
contains one example project, shared capability packs, and two PipeSpaces with different
capability selections:

```bash
git clone https://github.com/aikenc/pipebuilder.git
cd pipebuilder

python3 pipebuilder.py check examples/multi-pipeline-project/pipespaces/feature-development
python3 pipebuilder.py check examples/multi-pipeline-project/pipespaces/bugfix-review

python3 pipebuilder.py explain examples/multi-pipeline-project/pipespaces/feature-development
python3 pipebuilder.py build examples/multi-pipeline-project/pipespaces/feature-development
```

After the build, platform configuration is generated only in the selected PipeSpace. The
referenced `project/` is not modified:

```text
feature-development/
├── AGENTS.md
├── .agents/skills/feature-implementation/
├── .cursor/
│   ├── rules/
│   └── skills/feature-implementation/
└── .pipebuilder/lock.json
```

Open `feature-development.code-workspace` in Cursor. For Codex, start the client from
`feature-development/`. Both clients see the `pipeline` and `project` workspace folders and
load the configuration generated for the current pipeline.

For a compact four-agent input with independently reviewed expected output, see
[examples/all-agents-golden](examples/all-agents-golden). It is the public source of truth for
the static E2E example copied into temporary test sandboxes.

## How a PipeSpace Works

Every PipeSpace contains at least one declaration file and one VS Code/Cursor workspace file:

```text
feature-development/
├── pipespace.json
└── feature-development.code-workspace
```

`pipespace.json` selects target agents, Skills, tags, and Skill Providers:

```json
{
  "schema": "pipespace.v1",
  "name": "feature-development",
  "agents": ["codex", "cursor"],
  "skills": ["feature-implementation"],
  "tags": [],
  "skillProviders": [
    {"type": "folder", "path": "../../shared-skills"}
  ]
}
```

The workspace file includes the PipeSpace itself and one or more external project folders.
The `pipeline` folder lets clients discover native configuration generated at the PipeSpace
root, while the `project` folder points to the project:

```json
{
  "folders": [
    {"name": "pipeline", "path": "."},
    {"name": "project", "path": "../../project"}
  ]
}
```

Build flow:

```text
capability packs + PipeSpace declaration + workspace file
                            |
                            v
                     PipeBuilder plan
                            |
                            v
       native Skills / Rules / Hooks / configuration per agent
                            |
                            v
                  .pipebuilder/lock.json
```

`lock.json` records Skill Providers, Skills, sources, target files, and digests. `clean`
deletes only generated files that a valid lock proves belong to PipeBuilder; it does not guess
ownership of other files.

## Current Support

PipeBuilder 0.1.1 includes four platform Adapters. Keep their validation levels distinct:

| Agent | Current generation capabilities | Validation status |
| --- | --- | --- |
| Codex | Skills, `AGENTS.md`, config/agents/MCP, Hooks, Rules | Automated real-client E1; real-model E2 |
| Cursor | Skills, workspace Rule, Rules, Commands | Automated installed-client E1 smoke; manual discovery certification |
| CodeBuddy | Skills, fixed workspace Rule, Commands, Agents, Settings/Hooks, MCP | E0 generation and limited structural validation |
| Claude Code | Skills, `CLAUDE.md`, Rules, Commands, Agents, Settings/Hooks, MCP | Automated real-client E1 parsing and discovery |

`client-verified` means validation has run in a real client. `generated-only` means generated
output and supported structure have been validated, but real-client E1 has not been
established. The status is recorded in `explain` and `.pipebuilder/lock.json`.

## Skill Providers

PipeBuilder supports three Skill sources:

1. `.pipebuilder/skills/`: local capabilities in the current PipeSpace, with the highest
   precedence.
2. Folder Skill Provider: references a shared capability folder on the local machine or in a
   repository.
3. Git Skill Provider: fetches a capability repository by branch or tag and pins it to a
   commit in the lock.

Folder Skill Provider:

```json
{
  "type": "folder",
  "path": "../../shared-skills"
}
```

Git Skill Provider:

```json
{
  "type": "git",
  "url": "https://example.com/team/agent-skills.git",
  "tag": "v1.0.0",
  "subdir": "skills"
}
```

The Git cache is stored in `.pipebuilder/cache/git/` inside the current PipeSpace. `--offline`
uses only the existing lock and local immutable snapshot without remote access. Authentication
is delegated to a Git credential helper or SSH agent; never put credentials in
`pipespace.json`.

A Skill Provider may also declare post-build commands. `check`, `explain`, and
`build --dry-run` only display them; only a real `build` invokes them.

## Common Commands

Single PipeSpace:

```bash
python3 pipebuilder.py init [SPACE]
python3 pipebuilder.py check [SPACE]
python3 pipebuilder.py explain [SPACE] --format json
python3 pipebuilder.py build [SPACE] [--offline] [--dry-run]
python3 pipebuilder.py verify [SPACE]
python3 pipebuilder.py clean [SPACE]
```

Every command uses the same `pipespace.json`. By default, PipeBuilder automatically finds nested
PipeSpaces within three directory levels and operates on the complete hierarchy. Configure the
depth with `"children": {"scanDepth": N}` or set it to `0` for root-only operation. Hidden,
generated, and symlinked directories are skipped.

A Tree orchestrates only one explicitly declared level of children. It neither scans
directories nor recurses implicitly. Regular `build` and `clean` always process only the
specified PipeSpace.

Automation should use `--format json` and depend on stable diagnostic codes in
`pipebuilder-report.v1` instead of parsing human-readable messages.

## Ownership and Safety Boundaries

Human-maintained inputs:

- `pipespace.json` and `<name>.code-workspace`
- `.pipebuilder/skills/`
- `.pipebuilder/agents/<agent>/`
- standard Skills and `.pipe-agents/<agent>/` in Skill Providers

Builder-managed outputs:

- `AGENTS.md`, `CLAUDE.md`
- `.agents/skills/`
- `.codex/`, `.cursor/`, `.codebuddy/`, `.claude/`
- `.mcp.json`
- `.pipebuilder/generated/` and `.pipebuilder/lock.json`

Do not maintain generated files directly. Move content that must persist to the corresponding
source, then run `build` again. Files not registered by the current plan or an old lock are not
modified.

## Documentation

Start with the [documentation index](docs/README.md):

- [PipeSpace and Skill Provider specification](docs/pipebuilder-space-json-spec.md)
- [Four-agent Adapter specification](docs/pipebuilder-agent-adapters.md)
- [E2E guide](tests/e2e/README.md)
- [E2E coverage matrix](tests/e2e/COVERAGE.md)

## Development and Testing

All tests invoke the final release file through subprocesses; they do not import production:

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
```

GitHub Actions runs E0 on Python 3.11 for Linux, Windows, and macOS. Linux additionally covers
Python 3.7 and Python 3.13. The installed-client tier includes automated Codex, Cursor, and
Claude Code cases; CodeBuddy remains generated-only.

## License

[MIT License](LICENSE)
