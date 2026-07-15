# PipeBuilder: Skill Input Catalog and Agent Capability Coverage

Status: target catalog; see `tests/e2e/COVERAGE.md` for the current baseline
Date: 2026-07-13
Scope: standard Skills, four-Agent capabilities, Provider resolution, failure scenarios, and Codex live-model scenarios in PipeBuilder Python E2E

Related documents:

- [PipeBuilder Python E2E Integration Test Architecture](pipebuilder-test-architecture.md)
- [PipeSpace and Skill Provider Protocol](pipebuilder-space-json-spec.md)
- [Initial Four-Agent Adapter Specification](pipebuilder-agent-adapters.md)

---

## 1. Conclusion

Multiple input sets are required. A single minimal `SKILL.md` is insufficient, and all behavior should not be concentrated in one monolithic Skill.

The target directory is organized around five capability categories:

```text
5 Skill input capability categories
+ Space-level `.pipebuilder/agents` overlay
```

The five input capability categories cover:

1. portable common Skills;
2. full-capability projections for all four Agents;
3. Provider, explicit-list, and tag resolution;
4. invalid, conflict, and security scenarios;
5. Codex live consumption using either the client default or a model explicitly selected by the release job.

An additional PipeSpace overlay validates `.pipebuilder/agents/<agent>`. Because it is not a Skill, it must not be disguised as a Skill input.

Each Skill remains small, typically consisting of one `SKILL.md` plus one or two minimal resources. Comprehensive coverage comes from input composition and the capability matrix, not from complex application logic.

---

## 2. Input Design Principles

### 2.1 Model Real Skills, Not Test-Script Manuals

Every valid Skill input follows the standard structure:

```text
<skill-name>/
├── SKILL.md
├── scripts/          # optional
├── references/       # optional
├── assets/           # optional
├── agents/           # optional Skill metadata
└── .pipe-agents/        # optional PipeBuilder extension
```

`SKILL.md` requirements:

- `name` matches the directory name;
- `description` clearly states the trigger conditions;
- the body contains concise, executable instructions;
- the test setup process, expected output, and test explanations are omitted;
- the core body should remain under 50 lines where practical;
- details belong in `references/`, while deterministic actions belong in Python `scripts/`.

Do not add a README, installation guide, or changelog to a Skill directory. Test metadata belongs in the test-side Python cases so that the package delivered to the Agent remains clean.

All executable test inputs use Python. Skill scripts, hooks, local MCP servers, and receipt writers must not use MJS, TypeScript, or shell scripts. Markdown, JSON, TOML, YAML, and `.rules` files serve only as product inputs or expected data.

### 2.2 Prefer Orthogonality Over Duplication

Each input should have one primary purpose:

- common-package preservation;
- a complete capability projection for one Agent;
- Provider resolution;
- one explicit failure reason;
- one live-consumption capability.

The same fact is not maintained repeatedly across four nearly identical Skills. Platform differences belong only in the corresponding `.pipe-agents/<agent>` directory.

### 2.3 Three States: Supported, Gated, and Unsupported

Every Agent capability must be in exactly one of the following states:

| State | Input behavior |
| --- | --- |
| `supported` | Included in the full-capability Skill and required to have an E0 golden expectation plus E1 client verification |
| `gated` | Retained as a candidate input; it may enter the full-capability Skill only after real-client verification passes and the schema is frozen |
| `unsupported` | Included in a negative case and required to fail consistently with a diagnostic |

A directory that appears to exist is not necessarily supported. Version-sensitive capabilities, particularly Cursor hooks, agents, config, and MCP as well as arbitrary CodeBuddy Rules, must not be presented as supported through ordinary file copying.

### 2.4 Test Inputs Must Not Reuse the Production Oracle

Test-side Python may copy public examples and inject nonces, but it must not invoke PipeBuilder's resolver, adapter, or renderer. Expected targets, locks, and reports remain independent golden expectations.

---

## 3. Test Directory

Static inputs belong only under `examples/`; test metadata and dynamic construction remain under
`tests/e2e/cases/`. The target static catalog is:

```text
examples/
├── all-agents-golden/
└── capability-catalog/
    ├── skill-packs/
    │   ├── portable/
    │   │   ├── example-minimal/
    │   │   └── example-bundled/
    │   ├── agent-capabilities/
    │   │   ├── example-codex-capabilities/
    │   │   ├── example-cursor-capabilities/
    │   │   ├── example-codebuddy-capabilities/
    │   │   └── example-claude-code-capabilities/
    │   ├── resolution/
    │   │   ├── space-local-provider/
    │   │   ├── provider-high/
    │   │   └── provider-low/
    │   ├── invalid/
    │   │   ├── bad-frontmatter/
    │   │   ├── unsupported-surface/
    │   │   ├── semantic-conflict/
    │   │   └── security/
    │   └── live-codex/
    │       └── example-live-codex/
    └── space-overlays/
        ├── all-agents/
        ├── merge-with-skill/
        └── conflict-with-skill/
```

Test-side Python stores only metadata and copy locations, such as the example ID, pack, validity,
target Agent, and capability tags. It neither parses `SKILL.md` nor computes expected projections.

When a case creates a sandbox:

1. copy the selected public example into the temporary Sandbox;
2. copy the selected input pack byte-for-byte to the designated Provider;
3. inject a per-run nonce with test-side Python when necessary;
4. snapshot the fully assembled input;
5. execute the final `pipebuilder.py` through a subprocess.

Do not reuse static inputs through cross-directory symlinks, because Windows behavior and symlink policies could change test semantics.

---

## 4. Pack A: Portable Common Skills

This input set does not contain `.pipe-agents`. It proves that a standard Skill package is copied consistently to all four platforms and that `.pipe-agents` exclusion does not accidentally remove common resources.

### 4.1 `example-minimal`

```text
example-minimal/
└── SKILL.md
```

Coverage:

- minimal valid frontmatter;
- consistency between `name` and the directory;
- discovery metadata in `description`;
- byte-preservation of the Markdown body;
- Skill targets for all four platforms;
- explicit selection and absence when not selected.

### 4.2 `example-bundled`

```text
example-bundled/
├── SKILL.md
├── scripts/
│   └── write_receipt.py
├── references/
│   └── protocol.md
├── assets/
│   └── payload.txt
└── agents/
    └── openai.yaml
```

Coverage:

- nested-directory preservation;
- the Python executable bit;
- a progressive-disclosure reference;
- an asset as a non-context resource;
- Skill UI metadata;
- the common-package digest;
- byte-for-byte identical contents across all four target directories.

`write_receipt.py` uses only the Python standard library, accepts `argv`, and emits a versioned JSON receipt that an Agent can invoke in E2.

---

## 5. Pack B: Full-Capability Skills for Four Agents

There is one Skill per platform. It contains every `.pipe-agents` surface currently marked `supported` for that platform and deliberately excludes directories for other platforms.

```text
example-codex-capabilities/
├── SKILL.md
└── .pipe-agents/codex/...

example-cursor-capabilities/
├── SKILL.md
└── .pipe-agents/cursor/...

example-codebuddy-capabilities/
├── SKILL.md
└── .pipe-agents/codebuddy/...

example-claude-code-capabilities/
├── SKILL.md
└── .pipe-agents/claude-code/...
```

This separation serves three purposes:

- a single-Agent case can isolate adapter problems precisely;
- the all-agents catalog smoke test can prove that all four capability sets build together;
- a schema change on one platform does not alter the other three input sets.

### 5.1 Capability Matrix

Legend: `P` denotes a positive supported input, `G` a candidate gated on the client version, `R` a rejection case, and `—` a capability that is not modeled separately.

| Surface | Codex | Cursor | CodeBuddy | Claude Code |
| --- | --- | --- | --- | --- |
| Common Skill | P | P | P | P |
| Workspace rule | PipeSpace input | PipeSpace input | PipeSpace input | PipeSpace input |
| Rules | P: `.rules` command policy | P: `.mdc` | G: enable only after pinning and verifying the client | P: `.md`/path scope |
| Commands | R: unsupported in the initial version | P | P | P + migration warning |
| Agents | P: config agent roles | G | P | P |
| Hooks | P | G | P: settings merge | P: settings merge |
| Generic config | P: strict TOML subset | G | —: represented by the settings surface | —: represented by the settings surface |
| MCP | P: config TOML | G | P: `mcp.json` | P: `.mcp.json` |
| Builder-owned target regeneration | P | P | P | P |
| Human-owned source preservation | `.pipebuilder/agents/codex` | `.pipebuilder/agents/cursor` | `.pipebuilder/agents/codebuddy` | `.pipebuilder/agents/claude-code` |

Capability status is governed by the Adapter specification and the pinned client version. Promoting `G` to `P` requires all of the following in the same change:

1. exact source grammar;
2. target path and schema;
3. semantic key;
4. merge and conflict policy;
5. E0 golden;
6. E1 client parse or discovery case;
7. compatibility note.

### 5.2 Codex Capability Skill

At minimum, include:

- one minimal `.rules` allow/deny policy;
- one additive lifecycle hook;
- one named agent role;
- one safe config fragment;
- one local Python stdio MCP server definition.

Additional assertions:

- `.pipe-agents/codex/.codex/commands` is absent from the positive Skill;
- a separate negative case containing that directory consistently returns unsupported;
- the canonical workspace section, Space source, and Skill `AGENTS.md` source compose deterministically;
- rebuilding restores the generated root `AGENTS.md` after it is modified;
- `codex execpolicy check`, config discovery, and the hook probe are covered by E1.

### 5.3 Cursor Capability Skill

The baseline includes at least:

- an `.mdc` rule;
- a Markdown command.

This baseline has automated installed-client E1 smoke coverage for the CLI and generated native
discovery paths, backed by prior manual discovery certification. Hooks, agents, config, and MCP
remain `G` and stay in candidate cases rather than entering the baseline full-capability Skill
until their schemas are confirmed against the team's pinned Cursor client. Add them individually
after confirmation instead of claiming support for all of them at once.

### 5.4 CodeBuddy Capability Skill

The baseline includes at least:

- a command;
- a sub-agent;
- a settings hook fragment;
- an MCP server.

Arbitrary Rules are promoted from `G` only after successful discovery against the pinned real-client version. Each hook, agent, and MCP entry uses a unique semantic name so that the full smoke test does not create its own conflicts.

### 5.5 Claude Code Capability Skill

At minimum, include:

- an always-loaded rule;
- a path-scoped rule;
- a compatibility command;
- a sub-agent that references an installed example Skill;
- a settings hook;
- a local Python MCP server.

Additional assertions:

- the command generates a migration warning;
- the shapes of `tools`, `disallowedTools`, `skills`, `mcpServers`, and hooks are validated;
- the `.pipebuilder/agents/claude-code` source remains unchanged, while the root `CLAUDE.md` and target settings can be regenerated completely.

---

## 6. Pack C: Providers and Selection

This pack is not a single Skill; it consists of three Provider roots. Content with the same Skill name uses clearly distinct markers:

```text
resolution/
├── space-local-provider/
│   ├── example-space-local/SKILL.md
│   └── example-shadow/SKILL.md       # marker: space-local
├── provider-high/
│   ├── example-explicit/SKILL.md
│   ├── example-tagged/SKILL.md
│   ├── example-shadow/SKILL.md       # marker: high
│   └── example-unselected/SKILL.md
└── provider-low/
    ├── example-shadow/SKILL.md       # marker: low
    └── example-low-only/SKILL.md
```

Use one complete PipeSpace to cover:

- implicit selection of all Space-local Skills;
- precedence of the explicit `skills` selection;
- union inclusion through `tags` matches;
- a high-priority Provider shadowing a low-priority Provider;
- the Space-local Provider shadowing every external Provider;
- absence of unselected Skills from every Agent target;
- `selectedBy`, Provider, and `shadowedCandidates` in the lock and `explain`;
- protocol-defined changes to results and provenance after Provider order changes.

This pack excludes Agent surfaces such as rules and hooks so that resolution failures are not conflated with adapter failures.

`example-tagged` specifically covers one or more tags, tag union, negative variants with duplicate tags or invalid types, and verbatim preservation of unrecognized frontmatter fields. Portable example frontmatter uses only the standard `name` and `description`. A Skill with tags is explicitly a PipeBuilder resolution extension and does not claim to be the minimal cross-platform standard.

---

## 7. Pack D: Invalid, Conflict, and Security Scenarios

Each negative input must have one primary error per case. Do not create a directory that simultaneously lacks `SKILL.md`, has invalid frontmatter, escapes its path boundary, and leaks a secret; such an input would verify only fail-fast ordering.

At minimum, cover:

### Skill Package

- missing `SKILL.md`;
- malformed frontmatter;
- missing or invalid `name`, or a `name` that differs from the directory;
- empty `description`;
- `tags` that are not a list, contain duplicates, or contain non-string elements;
- prohibited encoding or an unreadable file;
- invalid symlinks or cycles.

### Agent Surface

- an unknown directory under `.pipe-agents/<agent>`;
- a gated or unsupported surface for the current adapter;
- an incorrect extension for a rule, command, or agent file;
- invalid frontmatter or schema;
- different definitions under the same semantic key;
- a conflict between Skill-level and Space-level sources;
- configuration that cannot be round-tripped safely.

### Security

- absolute paths, path traversal, or symlink escapes in a native source tree;
- external hook paths or high-risk wrappers;
- MCP secret literals;
- broad `allow` policies;
- rebuilding after manual modification of a generated target restores the source definition;
- sibling files unrelated to the plan or old lock remain unchanged;
- legacy `tagents/`, Space-root `.pipe-agents/`, and the new `.pipebuilder/agents/`, each alone or in combination.

Inputs requiring symlinks, junctions, case folding, or permissions are created by test-side Python inside the sandbox. Platform-specific inode behavior must not be disguised as an ordinary checked-in example.

---

## 8. Pack E: Codex Live Skill

The initial real-model coverage uses one reusable Skill package:

```text
example-live-codex/
├── SKILL.md
├── scripts/
│   ├── write_receipt.py
│   └── mcp_probe.py
├── references/
│   └── protocol.md
├── assets/
│   └── payload.txt
└── .pipe-agents/
    └── codex/
        ├── AGENTS.md
        └── .codex/
            ├── config.toml
            ├── hooks.json
            └── rules/
```

The model is not pinned in the example. Normal runs use the client default, while release jobs may pass `--model` explicitly. The following target cases may be separated according to compatibility risk:

| Live case | Validation | Machine oracle |
| --- | --- | --- |
| `explicit-skill` | The Skill is discoverable and can be loaded explicitly | Returns the nonce and Skill ID for the current run |
| `auto-discovery` | Automatic matching by `description` | Receipt indicates that the Skill body was loaded; not a hard release gate |
| `progressive-resources` | Reference, asset, and Python script | Reference nonce, asset digest, and script JSON receipt |
| `workspace-context` | Native discovery of the generated `AGENTS.md` | Returns the folder identity from `.code-workspace` |
| `skill-hook` | The Skill hook executes in a real session | Hook receipt file |
| `subagent` | The configured agent role is discoverable and can launch | Subagent receipt or structured result |
| `mcp-tool` | The local MCP server loads and is called | MCP tool receipt and nonce |

Rules syntax and allow/deny behavior are validated deterministically in E1 primarily through `codex execpolicy check`. E2 may add a harmless command-policy case, but the model must not attempt destructive commands.

### 8.1 Per-Run Nonce

Each live case generates a random nonce and injects it before the build into a reference, asset, hook, or MCP response unique to that case. The prompt does not contain the expected nonce.

```text
HARNESSBUILDER_LIVE_<random>
```

The nonce can be obtained only by actually loading the corresponding surface. Tests compare nonces and receipts, not complete natural-language responses.

### 8.2 Receipt Schema

Every Python probe emits:

```json
{
  "schema": "pipebuilder-fixture-receipt.v1",
  "fixture": "fixture-live-codex",
  "capability": "mcp-tool",
  "nonce": "$FIXTURE_NONCE",
  "argv": [],
  "status": "ok"
}
```

Receipts may be written only to the sandbox capture directory. They must not read the real home directory or record tokens or credentials.

### 8.3 Live-Case Isolation

- one independent Codex session per capability;
- `--ephemeral`;
- independent PipeSpace sandbox and capture directory;
- model, client version, prompt digest, nonce digest, and every retry recorded in the report;
- a failed session must not reuse a receipt generated by a previous attempt;
- automatic-trigger tests and explicit-Skill tests are reported separately.

---

## 9. Space-Level Overlay Input

PipeSpace `.pipebuilder/agents/<agent>` is maintained separately and preserves each platform's native configuration tree:

```text
space-overlays/
├── all-agents/
├── merge-with-skill/
└── conflict-with-skill/
```

Coverage:

- a PipeSpace-only command, hook, or rule specific to the platform project;
- additive merging with Skill artifacts;
- deduplication of identical digests;
- failure for different definitions under the same semantic key;
- no implicit override based on scope;
- provenance that distinguishes `space` from `skill:<name>`.

This input set does not contain `SKILL.md` and must not be discovered by the Provider index.

---

## 10. Five Complete PipeSpace Topologies

Input packs are ultimately consumed through the following E2E topologies:

### T1: Portable Smoke

Use all four Agents with Pack A to verify that the common package is identical across all four platforms.

### T2: Adapter Full Smoke

Run Pack A plus the corresponding capability Skill separately for each platform. A separate all-agents build selects all four capability Skills simultaneously to validate merging and ownership.

### T3: Resolution Matrix

Use all four Agents with Pack C to validate final results and provenance for Space-local, explicit, tag, shadow, and unselected cases.

### T4: Negative Matrix

Each case installs exactly one erroneous Pack D input and asserts a stable diagnostic, zero unintended writes, and recoverability.

### T5: Codex Live

Build Pack E and then use the Codex live profile. The current baseline is one combined sentinel request that validates AGENTS, an explicit Skill, and the SessionStart hook together. It should be split into multiple model requests only when needed to isolate instability or establish an independent release gate.

PipeSpace overlay inputs are added to the T2 merge and conflict cases; they are not represented by a separate, artificial Skill.

---

## 11. Input Change Gate

Adding any Agent capability requires simultaneous updates to:

1. the Adapter capability matrix;
2. the corresponding full-capability Skill;
3. an isolated E0 case;
4. the all-capabilities smoke golden;
5. a conflict or invalid case;
6. E1 client verification;
7. the requirement mapping in `COVERAGE.md`;
8. a short E2 case if the capability is part of the core Codex live path.

Deleting or renaming an input requires proof that no requirement loses its only coverage. Updating golden expectations is not a substitute for capability review.

---

## 12. Current Baseline and Extension Checklist

The repository currently uses `examples/all-agents-golden` as the sole static all-agent input and
golden source, while dynamic sandbox cases construct the following equivalent capabilities:

```text
portable common package
explicit/tag/local/shadow resolution
codex/cursor/codebuddy/claude-code full native surfaces
invalid/conflict/security variants
live Codex AGENTS + Skill + hook sentinel
```

The current baseline also includes:

- dynamic inputs for multiple Providers, Space-local selection, explicit lists, tags, and shadowing;
- a real failure path for every v1 stable diagnostic; PB012 retains only its historical number and is not part of the v1 stable contract;
- same-directory, decoupled-directory, multi-folder, and special-character `.code-workspace` topologies;
- E0 projections for all four Agents and the Codex E1 client report;
- one combined Codex live case relevant to releases.

Before adding a physical example pack, demonstrate that it is easier to review than a dynamic case or that it freezes a new binary or client contract. Existing inputs must not be duplicated merely to increase the number of directories.
