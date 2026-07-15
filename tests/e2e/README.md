# PipeBuilder E2E

This directory contains black-box acceptance tests for the release artifact `pipebuilder.py`. Test helpers do not import production code; every case launches the same release artifact in an isolated temporary PipeSpace using an argv list and `shell=False`.

Run the suite with:

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --model <model-id> --require
python3 tests/e2e/run.py --tier all --agent codex --require
python3.8 tests/e2e/run.py --tier offline --case PipeSpaceTreeCases
```

`offline` is the network-free gate; `client` invokes a real client without requesting a model; `live` starts a real Codex model session. When `--model` is omitted, the live tier uses the installed Codex client's default model so that potentially obsolete model names are not hard-coded in the tests.

The current automated `client` and `live` cases cover Codex only. Cursor has completed manual real-client E1 certification and its product status is recorded as `client-verified`, but the repository does not yet provide a repeatable automated Cursor client case. CodeBuddy and Claude Code remain `generated-only`.

The runner generates `e2e-report.json`, which records the release SHA256, case metadata, actual argv, cwd, stdout/stderr, and duration. A failed sandbox is copied to `.artifacts/<case-id>/`. Both outputs are ignored by Git.

Static fixtures and human-reviewed goldens are stored in `fixtures/`. See [COVERAGE.md](COVERAGE.md) for the coverage mapping and the boundaries that still require validation on native runners.
