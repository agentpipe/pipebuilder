# PipeBuilder v0.2.0 Implementation and Iteration Record

Date: 2026-07-13
Validation interpreter: CPython 3.11.9 (isolated build used only for testing)
Result after round 20: 40/40 passed
First pre-delivery hardening: 43/43 passed
After the comprehensive E2E rewrite: E0 57/57, Codex E1 5/5, Codex E2 1/1
After v0.2.0 security and migration hardening: E0 71/71, Codex E1 5/5, Codex E2 1/1
After strengthening Git Provider and folder boundaries: E0 84/84, Codex E1 5/5, Codex E2 1/1

The host's default `python3` is 3.6.8, below PipeBuilder's explicit requirement of Python 3.11. To preserve the release constraint of depending only on the Python 3.11 standard-library `tomllib`, CPython 3.11.9 was built in isolation under `/tmp` for these tests. No dependencies were installed into the repository or the system Python.

| Round | Added validation or improvement | Result |
| --- | --- | --- |
| 1 | Completed the single-file CLI, four Adapters, lock/clean, and the initial 21 black-box E2E cases; identified that the default Python version did not meet requirements | 21/21 passed under isolated Python 3.11 |
| 2 | Duplicate agents in the manifest, absolute workspace paths, and duplicate real paths | 23/23 passed |
| 3 | Stable diagnostic codes for a missing Provider and a missing explicitly selected Skill | 24/24 passed |
| 4 | Binary files, hidden files, executable bits, `.DS_Store` exclusion, and source immutability in the common package | 25/25 passed |
| 5 | After removing an agent, clean only that Adapter's owned targets | 26/26 passed |
| 6 | After deselecting a Skill, clean its installation directory and agent artifacts | 27/27 passed |
| 7 | Additive merge in JSON handlers and deduplication of identical definitions | 28/28 passed |
| 8 | Deterministically render quoted keys and arrays in Codex TOML, then round-trip the result through `tomllib` | 29/29 passed |
| 9 | Every artifact digest/provenance entry in the lock corresponds to the actual target | 30/30 passed |
| 10 | Idempotent clean; a corrupt lock fails with zero side effects | 32/32 passed |
| 11 | Source-symlink and target-parent-symlink escapes; corrected an invalid test premise that did not actually reach the target | 33/33 passed |
| 12 | A semantic conflict must fail before any write and release the operation lock | 33/33 passed |
| 13 | Fault injection for an owned target drifting from a file to a directory | Found and fixed a build-preflight bug; 34/34 passed |
| 14 | If apply is interrupted, the old lock does not advance and the next build converges fully | 35/35 passed |
| 15 | A hard process crash leaves a stale `build.lock`; recovery succeeds after a Human removes it | 36/36 passed |
| 16 | Clean preflights every target kind before deleting anything | Found and fixed a partial-clean bug; 37/37 passed |
| 17 | Reject secret literals and permit environment-variable secret references | 38/38 passed |
| 18 | Portability collision between targets that differ only by case | 39/39 passed |
| 19 | A misspelled runner `--case` produced a false green result with 0 tests | Found and fixed the runner bug; no match returns 2, and a single case passed |
| 20 | Do not read Space/Skill sources for unselected agents; final `py_compile` and full regression | 40/40 passed |

All tests execute the final `pipebuilder.py` through `shell=False` subprocesses from `tests/e2e/support/`. Rounds 13, 14, and 15, along with subsequent real-concurrency cases, use E2E-only `PIPEBUILDER_TEST_*` fault/timing injection variables inside the script under test to validate apply failures, crashes, and lock contention. When these variables are unset in a normal environment, they do not affect the build path.

The subsequent comprehensive rewrite split tests into cases, public examples, golden expectations, and support code, then added structured reports, failure artifacts, concurrency-safety metadata, and `COVERAGE.md`. The local Codex CLI 0.144.1 completed E1 validation of real prompt assembly, configuration, execpolicy, and hook schemas. A single real-model request simultaneously passed the sentinels for generated `AGENTS.md`, the Skill, and the SessionStart hook. The other three platforms still claim only E0 projection coverage.

Pre-delivery hardening after the 20 rounds added three more cases: rejection of Codex machine/user-level keys, a semantic collision between Cursor slash commands in different directories, and a Claude Code legacy-command migration warning. These were not counted in the 20-round loop above; the final full result was 43/43.

The second audit-hardening pass fixed unauthorized clean through a forged lock, `.pipebuilder` symlink write-locking, YAML block scalars and unknown nested frontmatter, Unicode normalization, Windows reserved names, and related issues. It added Adapter schemas, hook-command secret checks, risk/semantic locks, standalone release-copy coverage, and runner redaction. Of the 45 real shared Skills from the original THarness, 43 passed the new parser; the remaining two require explicit canonical renaming. Final local validation was E0 71/71, Codex E1 5/5, and Codex E2 1/1.

The Provider follow-up implemented a `url + branch/tag` Git Provider, separate mirror/snapshot caches, commit locking, subdir support, and `--offline` digest validation. It also added coverage for a folder Provider whose root is a symlink, real-path aliases, paths with special characters, root kinds, and content changes. After adding 13 black-box cases, E0 reached 84/84. The Codex E2 sentinel Skill was also changed to be built from a real local Git branch Provider before being consumed by the model. The original security P0 remains guarded by regression cases for forged locks, Builder-state symlinks, THarness-compatible frontmatter, and unknown nested frontmatter.
