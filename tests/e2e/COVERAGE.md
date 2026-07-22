# PipeBuilder E2E Coverage Matrix

Status: implemented
Baseline date: 2026-07-16
Latest local validation: full E0 111/111, Cursor E1 4/4, and Claude Code E1 4/4.
The previously recorded Codex baselines are E1 5/5 and E2 1/1; Codex was not installed for
the current local run.

This document counts independent black-box test methods; a table or subtest within one method may cover multiple input variants. Every case executes the final `pipebuilder.py` and does not import production code.

## Execution Tiers

| Tier | Current coverage | External dependencies | Default gate |
| --- | --- | --- | --- |
| E0 offline | 111 cases covering 200+ positive and negative scenarios | Python 3.7+, Git, and a real filesystem; no network access | Required for PRs |
| E1 client | 5 Codex, 4 Cursor, and 4 Claude Code automated cases | The corresponding real client; no model request | main/release |
| E2 live | 1 combined Codex sentinel case | Codex CLI, authentication, network, and model | opt-in/release |

## E0 Requirement Mapping

| Requirement | Primary case/module | Acceptance coverage |
| --- | --- | --- |
| CLI/report | `test_contract.CliContractCases` | cwd/explicit space, text/JSON, version, zero-write check/explain/dry-run, compile, and the Python 3.7 syntax baseline |
| init | `test_contract.InitCases` | Directory and default required-file creation, directory name/explicit name, project-local self-hosted bootstrap, relative-path validation, existing-file validation, idempotency, and zero writes on failure |
| static golden | `test_contract.GoldenBuildCases` | Public `examples/all-agents-golden` input, complete managed target sets for all four Agents, full contents of key files, lock digest/provenance, and byte stability on the second build |
| public examples | `test_examples.PublicExampleCases` | A temporary copy of `examples/multi-pipeline-project` builds two PipeSpaces with distinct Skills and Rules, both workspace files resolve to the same project, and project bytes remain unchanged |
| manifest | `test_manifest_workspace.ManifestValidationCases`, `test_space_tree.PipeSpaceTreeCases` | malformed/non-object input, required/unknown fields, schema, name, agents, skills, tags, providers, description, and strict child scan-depth settings |
| workspace | `test_manifest_workspace.WorkspaceValidationCases` | Required file, malformed input, folder shape, colocated paths, directory decoupling, multiple folders, duplicate realpaths, Unicode/spaces/quotes/`#`/`$` |
| legacy namespace | `test_manifest_workspace.LegacyNamespaceCases`, `test_space_tree.PipeSpaceTreeCases` | `tagents`, `private`, root `.pipe-agents`, legacy YAML/lock/workspace sources, and removed `pipespace-tree.json`; zero writes |
| folder provider/selection | `test_providers_skills.ProviderResolutionCases` | Zero/missing/multiple providers, colocated/external/symlink roots, file roots, realpath aliases, Unicode/shell metacharacters, digest updates, local priority, explicit+tag+local union, shadow provenance, and provider order |
| Git provider | `test_providers_skills.GitProviderCases` | branch/tag, subdir, commit lock, online advancement, offline locked reuse, PipeSpace-local cache, missing cache/ref/subdir, digest tampering, archive symlinks, and mixed priority |
| common Skill | `test_providers_skills.SkillPackageCases` | Binary, hidden, executable, YAML block scalar, unknown nested frontmatter, BOM/CRLF, deep directories, `.DS_Store`, `.pipe-agents` exclusion, symlink, and invalid/missing Skill |
| Codex adapter | `test_adapters.CodexAdapterCases` | AGENTS, config TOML, native hooks schema, hook files, rules, stable merge, target drift, and machine-key rejection |
| Cursor adapter | `test_adapters.OtherAdapterCases` | skills, workspace rule, `.mdc` rules, commands, and frontmatter |
| CodeBuddy adapter | `test_adapters.OtherAdapterCases` | skills, workspace rule, commands, agents, settings, MCP, and hook files |
| Claude Code adapter | `test_adapters.OtherAdapterCases` | skills, CLAUDE, rules, command warnings, agents, settings, MCP, and hook files |
| adapter negatives | `test_adapters.AdapterRejectionCases` | Gated/unknown/empty surfaces, hook/MCP/settings/agent/rule schemas, TOML subset, semantic conflicts, portable collisions, and command/MCP secret linting |
| ownership/clean | `test_lifecycle_security.OwnershipLifecycleCases` | Clean removes only owned artifacts, idempotency, rebuild, Skill deselection, Agent removal, source updates, managed-file deletion, Builder version changes, and no ownership inference without a lock |
| lock/concurrency | `test_lifecycle_security.LockAndInterruptionCases` | Lock contention between two real processes, active/stale/malformed locks, hard crashes, apply failures, preservation of the old lock, and recovery convergence |
| filesystem security | `test_lifecycle_security.FilesystemBoundaryCases` | Forged locks, unowned targets, type drift, Builder state/target symlink escape, NFC/NFD/case collisions, Windows reserved names, invalid locks, and recursive providers |
| automatic child PipeSpaces | `test_space_tree.PipeSpaceTreeCases` | Unified check/explain/build/verify/clean; default and configured depth; recursive discovery; root-only depth zero; hidden/generated/symlink exclusions; reverse clean; independent ownership; membership drift and rebuild; cross-member stale plans; partial journals; and convergence on rerun |
| release/runner | `test_contract.CliContractCases` | Independent execution after copying the single file, SHA256 report, credential redaction in command records, and exclusion of auth/home from failure artifacts |
| Agent Skill release | `test_skill_release.SkillReleaseCases` | Root Skill metadata, project-local shared-Skill README flow, latest-Release links, deterministic three-file ZIP, extracted CLI execution, full-Skill updater replacement, dry run, and invalid-ZIP preservation |

## Stable diagnostics

| Code | E2E entry point | Status |
| --- | --- | --- |
| PB001 | malformed/shape/schema/unknown manifest, invalid lock | covered |
| PB002 | invalid space name table | covered |
| PB003 | exact workspace missing/name mismatch | covered |
| PB004 | malformed workspace, folder/path table | covered |
| PB005 | missing folder/Git cache/branch/tag/subdir | covered |
| PB006 | unsupported provider type | covered |
| PB007 | missing explicitly selected Skill | covered |
| PB008 | invalid Skill/frontmatter table | covered |
| PB009 | gated/unknown/malformed agent artifact table | covered |
| PB010 | semantic/path/ownership/type conflict | covered |
| PB011 | secret, symlink, machine config, injected filesystem failure | covered |
| PB012 | `adapter-not-implemented` | retired/reserved number; not part of the v1 stable contract, and unknown Agents are rejected with PB001 |
| PB013 | real concurrent active lock | covered |
| PB014 | stale dead-pid lock/crash recovery | covered |
| PB015 | every legacy marker | covered |
| PB016 | Provider post command start/cwd/exit failure, hierarchy partial journal | covered |
| PB017 | hierarchy discovery/receipt/stale-plan/member-state | covered |
| PB018 | fail-closed Provider post-command preflight before writes | covered |
| PBW001 | provider shadow | covered |
| PBW002 | Claude command migration | covered |

## E1: Real Codex Client

These tests use real commands from the installed Codex CLI rather than file-existence assertions:

- `codex --version` and a capability probe of the non-interactive command surface;
- `codex debug prompt-input` proves that the generated root `AGENTS.md` enters the model-visible project instructions;
- the same prompt assembly proves that `.agents/skills/<name>/SKILL.md` is scanned and its metadata is exposed;
- isolated `CODEX_HOME` project trust for a disposable project proves that the generated `.codex/config.toml` is loaded at the project layer;
- `codex execpolicy check` actually parses and matches the generated `.rules`;
- the real client accepts the current three-level `hooks.json` schema.

## E1: Real Cursor and Claude Code Clients

Cursor E1 records the installed CLI version, probes its headless command surface and `about`
command, validates the generated Rule/Skill/Command discovery paths, and uses the real client
to discover a workspace MCP configuration. The path checks automate the previously manual
baseline but do not claim model consumption.

Claude Code E1 records the installed CLI version, validates its supported command surface,
uses the real client to parse generated `.claude/settings.json`, discovers generated
`.mcp.json`, and validates the generated instruction, Rule, and Skill paths.

## E2: Real Model

A single model request validates three chains at once to reduce cost and variability:

1. The prompt explicitly mentions only `$hb-live-sentinel` and does not contain either expected value.
2. The Skill comes from a `branch + subdir` Provider backed by a real local Git repository. After the build locks to a commit, the Skill body supplies the Skill sentinel, while the generated `AGENTS.md` supplies the other sentinel.
3. `--output-schema` constrains the response to two-field JSON, and the final values must match exactly.
4. The generated `SessionStart` hook writes a receipt in the disposable workspace, and the test validates the event and cwd.
5. The case uses `--ephemeral`, `--ask-for-approval never`, a workspace sandbox, and a temporary `CODEX_HOME`; real authentication is mounted only through a symlink and is not copied into example inputs or reports.

## Explicitly Unclaimed Coverage

- The current machine has completed only native Linux filesystem runs. Windows/macOS case sensitivity, permissions, and symlink behavior still require CI on the corresponding OS; string-normalization tests cannot replace native runners.
- The repository includes a Linux/Windows/macOS GitHub Actions E0 matrix. Local conclusions still represent Linux only, and the first remote results require separate review.
- Cursor's automated E1 is a no-model CLI/path smoke layer; model-visible Rule and Skill consumption remains supported by its prior manual certification rather than an automated E2 sentinel. CodeBuddy still has E0 projection coverage only and remains `generated-only`.
- E2 currently runs on Codex only; model calls on other platforms are not a dependency for the initial release.
- Permission denial, a full disk, and a real power loss cannot be induced reliably inside an ordinary process. The current suite uses safe fault injection for apply failures/crashes and two real processes for lock contention.
- `--jobs` uses threads to run independent sandboxes in parallel; real-client, model, and lock-timing cases are marked serial.
- A local migration audit of the original THarness `shared-skills` found 43 of 45 directly compatible. The remaining `BotAI-Log-Analyzer` and `ts-local-launch` issues are canonical-name/directory-name data problems. Dynamic multiline/nested cases preserve the parser regression coverage without making an external THarness path an E0 dependency.
