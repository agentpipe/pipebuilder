# Changelog

## 0.1.4 - 2026-07-22

- Add `build --require-no-post-commands`, which fails before writes when any
  selected Provider declares a post command.
- Document a low-interruption, cross-Agent permission SOP in the packaged
  PipeBuilder Skill.

## 0.1.3 - 2026-07-18

- Move all release, updater, documentation, and CI links to `agentpipe/pipebuilder`.
- Verify the Agent Skill release ZIP with its published SHA-256 checksum before updating.
- Correct stale build-lock detection for terminated Windows processes.
