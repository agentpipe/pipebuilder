# One Project, Multiple Agent Pipelines

This example contains two task-specific PipeSpaces decoupled from the same `project/`:

- `feature-development` selects `feature-implementation` for feature development.
- `bugfix-review` selects `bugfix-review` for defect diagnosis and fix review.

Each `.code-workspace` file references its PipeSpace as the `pipeline` folder and the same
`project/` as the `project` folder. The two pipelines install different Skills and
platform-native Rules. Their shared capability packs come from the local Folder Skill Provider
at `shared-skills/` and are not copied into the project. The `pipeline` folder lets clients such
as Cursor discover native configuration generated at the PipeSpace root.

Run from the PipeBuilder repository root:

```bash
python3 pipebuilder.py check examples/multi-pipeline-project/pipespaces/feature-development
python3 pipebuilder.py check examples/multi-pipeline-project/pipespaces/bugfix-review

python3 pipebuilder.py explain examples/multi-pipeline-project/pipespaces/feature-development
python3 pipebuilder.py build examples/multi-pipeline-project/pipespaces/feature-development
```

After the build:

```text
pipespaces/feature-development/
├── AGENTS.md
├── .agents/skills/feature-implementation/
├── .cursor/rules/
├── .cursor/skills/feature-implementation/
└── .pipebuilder/lock.json
```

Open `pipespaces/feature-development/feature-development.code-workspace` in Cursor. For
Codex, start the client from `pipespaces/feature-development/`. Build output is written only
to that PipeSpace; `project/` is not modified.

The offline E0 smoke test copies this example into a temporary Sandbox, builds both
PipeSpaces, verifies their distinct Skill and Rule selections, and confirms that both still
reference the unchanged `project/`.
