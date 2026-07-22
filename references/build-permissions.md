# Low-interruption build permissions

Use this reference when an Agent must build a PipeSpace whose generated targets
are protected by its host sandbox or command approval system.

## Safety boundary

PipeBuilder planning reads Provider inputs and computes generated outputs. A
normal build may additionally execute each configured Provider post command.
The reusable low-interruption permission boundary is therefore:

```bash
pipebuilder build <space> --require-no-post-commands --format json
```

When using the packaged Skill without an installed launcher, replace
`pipebuilder` with the exact path to its `pipebuilder.py` and interpreter. The
flag fails with `PB018` before any build output, ownership lock, hierarchy
journal, or Provider command is written or executed. It does not disable or
skip a command.

## Approval SOP

1. Run `check`, `explain`, and fail-closed `build --dry-run` without elevated
   write permission.
2. Confirm the report has zero `postCommands` and no unexpected targets.
3. Run the fail-closed real build. If the sandbox blocks Builder-owned targets,
   request a persistent rule scoped to this executable, `build`, and the
   fail-closed flag.
4. Run `verify` without elevation when the host permits reads.
5. If `PB018` occurs, review each post command and request a separate,
   non-persistent approval when possible. Never broaden the safe-build rule.
6. Keep `clean` outside the build rule. It is intentionally a distinct,
   destructive lifecycle operation.

An `EROFS`, permission-denied, or approval prompt on `.agents`, `.cursor`,
`.codebuddy`, `.claude`, `AGENTS.md`, or `CLAUDE.md` is normally a host sandbox
decision, not evidence that PipeBuilder selected an invalid target.

## Agent-specific policy shape

- **Codex:** use its sandbox first. If escalation is necessary, persist only a
  narrow command prefix for the installed PipeBuilder safe-build invocation;
  do not approve a general Python or shell prefix.
- **Cursor:** command permissions are most useful when they identify a stable
  executable. Prefer an installed `pipebuilder` launcher over a broad
  interpreter permission, and keep post-command builds interactive.
- **Claude Code:** use an exact Bash allow rule together with the native
  sandbox. Never use `bypassPermissions`; approve ordinary builds with post
  commands separately.
- **CodeBuddy:** place the fail-closed build in the narrow allow layer, leave
  ordinary build in ask, and keep unsafe shell or destructive patterns in deny.
  Respect workspace trust and avoid global auto-approval.

Permission-file schemas evolve independently of PipeBuilder. Configure rules
through the Agent's supported settings surface; do not have PipeBuilder emit a
platform file it does not currently own.
