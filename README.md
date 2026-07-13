# HarnessBuilder

HarnessBuilder 是一个无第三方依赖的单文件 Harness Space 编译器。它读取必需的 `harness-space.json`、`<name>.code-workspace`、Skill Providers，以及 Space/Skill 两级 Agent 原生 source，在 Harness Space 根目录生成 Codex、Cursor、CodeBuddy 和 Claude Code 的项目配置。

要求 Python 3.11 或更高版本。

```bash
python3 harnessbuilder.py check /path/to/space
python3 harnessbuilder.py explain /path/to/space --format json
python3 harnessbuilder.py build /path/to/space
python3 harnessbuilder.py build /path/to/space --dry-run
python3 harnessbuilder.py clean /path/to/space
```

最小 Harness Space：

```text
space/
├── harness-space.json
└── <manifest-name>.code-workspace
```

Space-level Agent source 位于 `.harness-builder/agents/<agent>/`，Skill-level source 位于 `<skill>/.harness-agents/<agent>/`。每个 `<agent>` 目录都是虚拟项目根，例如：

```text
.harness-builder/agents/codex/
├── AGENTS.md
└── .codex/
    ├── config.toml
    ├── hooks.json
    ├── hooks/
    └── rules/
```

平台 target 均由 Builder 管理。已有 `AGENTS.md`、`CLAUDE.md`、`.mcp.json` 或平台目录配置需要先移动到对应 source 路径；未被当前 plan 或旧 lock 登记的其他文件不会被修改。

## 测试

测试只通过子进程调用发布文件，不 import 实现：

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
```

`client` 使用真实 Agent 客户端但不请求模型；`live` 发起真实模型会话。Codex 已有 E1/E2 实现，`--model` 可显式覆盖 live 模型，不传则使用已安装 Codex 的默认模型。未配置客户端/账号时默认 skip，传 `--require` 则失败。Runner 会生成被 `.gitignore` 排除的 `tests/e2e/e2e-report.json`，其中记录发布脚本 SHA256、平台、Python 版本、实际命令与逐 case 结果；失败 sandbox 保存在 `tests/e2e/.artifacts/`。

完整运行说明和覆盖缺口见 [tests/e2e/README.md](tests/e2e/README.md) 与 [tests/e2e/COVERAGE.md](tests/e2e/COVERAGE.md)。

协议与实现边界见 [docs/harnessbuilder-architecture-proposal.md](docs/harnessbuilder-architecture-proposal.md)，20 轮落地记录见 [docs/harnessbuilder-implementation-iterations.md](docs/harnessbuilder-implementation-iterations.md)。
