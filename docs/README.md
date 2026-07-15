# PipeBuilder Documentation

Start with the repository-level [README](../README.md) for the problems PipeBuilder solves, the quick start, and the current platform support status.

## Using PipeBuilder

- [PipeSpace and Skill Provider Specification](pipebuilder-space-json-spec.md)
  `pipespace.json`, automatic child discovery, the workspace file, Providers, Skill selection, directory decoupling, ownership locks, and security boundaries.
- [THarness Migration Audit](pipebuilder-tharness-migration-audit.md)
  Items that must be removed or adapted when migrating from the legacy THarness/HarnessBuilder namespace.

## Maintaining Cross-Agent Capabilities

- [Four-Agent Adapter Specification](pipebuilder-agent-adapters.md)
  Native directories, merge strategies, supported capabilities, and verification requirements for Codex, Cursor, CodeBuddy, and Claude Code.
- [Skill Input Catalog](pipebuilder-skill-fixture-catalog.md)
  Coverage design for standard Skills, platform extensions, Providers, negative cases, security, and real-client scenarios.

## Maintaining the Implementation and Tests

- [Architecture Overview](pipebuilder-architecture-proposal.md)
  Background on the single-file builder, PipeSpace inputs, Adapter IR, ownership, and decoupling from THarness.
- [E2E Test Architecture](pipebuilder-test-architecture.md)
  Black-box test layers, public examples, sandboxes, golden expectations, real clients, and release gates.
- [Implementation Iteration Log](pipebuilder-implementation-iterations.md)
  Historical iteration designs and phase-specific decisions; this is not the sole authority for current product status.
- [Test Execution Guide](../tests/e2e/README.md)
- [Test Coverage Matrix](../tests/e2e/COVERAGE.md)

## Documentation Status Conventions

- `implemented`: The specification is implemented by the current code.
- `implemented · manual E1`: Manually verified in a real client, but not yet captured as an automated client case.
- `proposal`: Design reference; if it conflicts with the code, tests, or an implemented specification, the code and black-box tests take precedence.
- Historical iteration documents explain the evolution only; they do not replace the current README, specifications, or test coverage matrix.
