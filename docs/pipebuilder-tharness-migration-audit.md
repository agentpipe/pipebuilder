# THarness Builder Migration Audit

Status: current baseline
Date: 2026-07-13

This document records only the migration boundary from the legacy THarness Builder to PipeBuilder. Rounditer is not part of the Builder; it can be distributed as a Skill that conforms to the PipeBuilder specification.

## Migrated

- explicit Skills, tag-based selection, Space-local Skills, and Provider shadowing;
- flat `SKILL.md` common packages and copying of binary, hidden, and executable files;
- Agent sources at both the Skill and Space levels;
- Cursor rules and commands, plus basic frontmatter validation;
- workspace-folder inventory;
- provenance locks, repeat builds, clean operations, failure recovery, and basic concurrency locks.

## Explicitly Removed or Remodeled

- command pipeline/no-shell runner;
- `runtime/`, `saved/`, `work/`, `artifacts/`, `logs/`;
- THarness repository root, central registry, and fixed `shared-skills` path;
- `.code-workspace.src` publishing;
- generic `files/` escape hatch;
- nested `skill/SKILL.md` as a formal protocol.

These items must not be reintroduced into PipeBuilder core. Conversion of legacy nested Skills, `tagents`, and YAML manifests or locks must be performed by a separate migration tool or explicitly by a human.

## Results from the Real Skill Catalog

An audit of the 45 `SKILL.md` files under `/data/workspace/THarness/harness/shared-skills` with the current parser and validator found:

- 43 are directly compatible;
- the name and directory of `BotAI-Log-Analyzer` do not conform to the lowercase canonical-name requirement;
- the frontmatter name of `ts-local-launch` is `tikistar-local-launch`, which does not match the directory name.

PipeBuilder supports `description: >`, `|`, `>-`, unknown block scalars, unknown nested metadata, BOM, and CRLF, all of which are common in these legacy Skills, and copies the common package unchanged. The remaining two issues require explicit renaming; the Builder does not silently change Skill identity.

An external THarness checkout is not an E0 repository dependency. The corresponding parser behavior is captured by self-contained fixtures in this repository; during migration, a complete `check` may additionally be run against the target catalog.

## Outstanding External Certification

- an automated case for Cursor's manual E1 validation, plus real-client E1 validation for CodeBuddy and Claude Code;
- native Windows and macOS CI, which has been added but still requires observation of its first results;
- a standalone bulk-migration tool for nested Skills and `tagents`;
- Git/registry Providers and adapter plugins, both of which remain future work.
