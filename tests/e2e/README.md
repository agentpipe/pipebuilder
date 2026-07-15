# PipeBuilder E2E

This directory contains black-box acceptance tests for the release artifact `pipebuilder.py`. Test helpers do not import production code; every case launches the same release artifact in an isolated temporary PipeSpace using an argv list and `shell=False`.

Run the suite with:

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier client --agent cursor --require
python3 tests/e2e/run.py --tier client --agent claude-code --require
python3 tests/e2e/run.py --tier live --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --model <model-id> --require
python3 tests/e2e/run.py --tier all --agent codex --require
python3.8 tests/e2e/run.py --tier offline --case PipeSpaceTreeCases
```

`offline` is the network-free gate; `client` invokes a real client without requesting a model; `live` starts a real Codex model session. When `--model` is omitted, the live tier uses the installed Codex client's default model so that potentially obsolete model names are not hard-coded in the tests.

The automated `client` tier covers Codex, Cursor, and Claude Code without model requests.
Cursor combines its automated CLI/path smoke cases with prior manual discovery certification.
Claude Code uses its real CLI to parse generated settings and discover generated project MCP
configuration. CodeBuddy remains `generated-only`; the `live` tier currently covers Codex only.

The runner generates `e2e-report.json`, which records the release SHA256, case metadata, actual argv, cwd, stdout/stderr, and duration. A failed sandbox is copied to `.artifacts/<case-id>/`. Both outputs are ignored by Git.

The repository's only static test inputs live under `examples/`. The all-agent input and its
human-reviewed expectations are in
[`examples/all-agents-golden`](../../examples/all-agents-golden); E0 copies only the example
inputs into temporary sandboxes and reads the golden files from the public example. See
[COVERAGE.md](COVERAGE.md) for the coverage mapping and the boundaries that still require
validation on native runners.
