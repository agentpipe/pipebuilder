# HarnessBuilder

HarnessBuilder 是一个无第三方依赖的单文件 Harness Space 编译器。它读取必需的 `harness-space.json`、`<name>.code-workspace`、Skill Providers，以及 Space/Skill 两级 Agent 原生 source，在 Harness Space 根目录生成 Codex、Cursor、CodeBuddy 和 Claude Code 的项目配置。

对外发布物只有 `harnessbuilder.py`；README、`docs/` 和测试不会随产品分发。发布脚本顶部与 `python3 harnessbuilder.py --help` 必须自包含运行要求、CLI、输入布局、Provider 和 ownership 说明。

能力状态会写入 `explain` 和 lock：Codex 当前为 `client-verified`；Cursor、CodeBuddy、Claude Code 在各自真实客户端 E1 建立前标记为 `generated-only`，避免把离线投影误报为客户端兼容认证。

要求 Python 3.7 或更高版本；不需要 Python 第三方包。

```bash
python3 harnessbuilder.py init /path/to/space
python3 harnessbuilder.py init /path/to/space --name my-space
python3 harnessbuilder.py check /path/to/space
python3 harnessbuilder.py explain /path/to/space --format json
python3 harnessbuilder.py build /path/to/space
python3 harnessbuilder.py build /path/to/space --offline
python3 harnessbuilder.py build /path/to/space --dry-run
python3 harnessbuilder.py clean /path/to/space
```

`init` 类似 `git init`：目标目录不存在时会创建它，并补齐默认的 `harness-space.json` 与
`<name>.code-workspace`。已有的必需文件不会被覆盖，而会按正式构建使用的同一套规则校验；
重复执行是幂等的。未传 `--name` 时直接使用目标目录名；目录名不符合 lowercase kebab-case
约束时，可在首次初始化时用 `--name` 指定。

Git Skill Provider 使用 `url` 加 `branch` 或 `tag`（严格二选一），并可指定 `subdir`：

```json
{
  "type": "git",
  "url": "https://example.com/team/skills.git",
  "branch": "main",
  "subdir": "skills"
}
```

Folder/Git Provider 可声明默认在 HarnessBuilder 正常构建之后执行的 `command`。`subdir`
是 Skill 根目录，`command.cwd` 相对 Provider 源根目录；参数中的 `{spaceRoot}`、
`{sourceRoot}`、`{providerRoot}` 会在调用前展开：

```json
{
  "type": "folder",
  "path": "../rounditer",
  "subdir": "skills",
  "command": {
    "cwd": ".",
    "args": ["node", "build.mjs", "--harness-post", "--output", "{spaceRoot}", "--driver", "webgame"]
  }
}
```

`check`、`explain` 和 `build --dry-run` 只校验、展示 command；只有正式 `build` 调用。

在线构建将选择器锁定到 commit 并缓存 immutable snapshot；`--offline` 复用 lock 与本地 cache。认证由 Git credential helper 或 SSH agent 提供，credential 不得写入 manifest。

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

GitHub Actions 在 Linux、Windows、macOS 的 Python 3.11 上运行 E0，Linux 额外覆盖最低支持版本
Python 3.7 和 Python 3.13。真实客户端和模型测试仍由具备对应客户端/账号的固定 runner 或人工 release job 执行。

协议与实现边界见 [docs/harnessbuilder-architecture-proposal.md](docs/harnessbuilder-architecture-proposal.md)，20 轮落地记录见 [docs/harnessbuilder-implementation-iterations.md](docs/harnessbuilder-implementation-iterations.md)。
