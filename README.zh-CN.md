# PipeBuilder

[English](README.md) | [简体中文](README.zh-CN.md)

[![E2E](https://github.com/aikenc/pipebuilder/actions/workflows/e2e.yml/badge.svg)](https://github.com/aikenc/pipebuilder/actions/workflows/e2e.yml)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 面向团队的跨 AI 编程 Agent 能力复用与任务管线空间构建工具。

Codex、Cursor、Claude Code 等 AI 编程 Agent 使用不同的 Skills、Rules、Hooks、MCP
和 workspace 规范。同一套团队能力需要反复适配，时间久了还会出现配置漂移和行为不一致。

同一个 `<project>` 在需求开发、缺陷修复、代码审查等任务中，需要不同侧重点的 Agent
能力，部分任务专属能力不应同时加载。如果把所有配置都堆进 project 根目录，无关 Skills
与 Rules 会扩大上下文、产生冲突，无关 Hooks 也可能在错误任务中执行。

PipeBuilder 解决这两个问题：

- **一套能力，跨 Agent 复用**：标准 Skill 由各平台共享；平台原生的 Rules、Hooks、
  Commands、Agents 和 MCP 配置可以随同一个能力包分发。
- **一个 project，多条 Agent 管线**：每条任务管线只组合自己需要的 Agent 和能力，
  同时引用同一份 project。
- **通过 Skill Provider 复用并版本化团队能力**：Skill Provider 既可以来自本地
  folder，也可以来自 Git repository，团队可以在本机共享能力包，也可以固定仓库版本。
- **生成平台原生配置**：不要求 Agent 理解 PipeBuilder 协议，构建结果仍是
  `AGENTS.md`、`CLAUDE.md`、`.cursor/`、`.claude/` 等原生文件。

**PipeSpace** 是与 `<project>` 解耦、面向特定任务的 agent pipeline root/space。
它通过 workspace 文件引用一个或多个 project folder，并承载该管线生成的配置；
它不是 project 的副本。

## 一个 project，多条 Agent 开发管线

`<project>` 是业务代码实体。需求开发、缺陷修复和代码审查可以分别使用独立的任务管线：

```text
team-workspace/
├── project/                         # 同一份 project
├── shared-skills/                   # 团队复用的能力包
└── pipespaces/
    ├── feature-development/         # 实现、测试相关能力
    ├── bugfix-review/               # 诊断、审查相关能力
    └── release-maintenance/         # 构建、发布相关能力
```

每个 PipeSpace 可以选择不同的 Skills、Rules、Hooks、MCP 和 Agent 组合。它的
`.code-workspace` 文件引用 PipeSpace 自身和一个或多个 project folder，因此管线配置
不必全部进入 project。

负责提供能力包的本地 folder 或 Git repository 称为 **Skill Provider**。

> PipeSpace 隔离的是 Agent 配置、上下文和管线组合，不是代码写入。多个 Agent
> 并行修改同一个 project 时，仍应使用 Git 分支、worktree 或独立 clone。

## 一套能力，跨 Agent 复用

一个能力包由两部分组成：

```text
shared-skills/bugfix-review/
├── SKILL.md                          # 各 Agent 共用的标准 Skill
├── scripts/
├── references/
└── .pipe-agents/                    # 可选的平台原生扩展
    ├── codex/AGENTS.md
    ├── cursor/.cursor/rules/
    ├── codebuddy/.codebuddy/settings.json
    └── claude-code/.claude/settings.json
```

- `SKILL.md`、脚本和参考资料属于可移植部分，安装到各平台的标准 Skill 目录。
- `.pipe-agents/<agent>/` 保留该平台的原生目录和格式，由对应 Adapter 合并到目标
  PipeSpace。
- PipeBuilder 不声称把同一份 Rule 或 Hook 无损翻译到所有平台；它让一个能力包同时
  携带标准 Skill 和必要的平台原生扩展。

因此，团队选择和版本化的是完整能力包，而不是散落在每个 project 里的多份平台配置。

## 60 秒快速开始

运行时只需要 Python 3.7+ 和单个 `pipebuilder.py` 文件。只有使用 Git Skill Provider
时才需要系统安装 Git；不需要安装 Python 第三方包。

```bash
curl -O https://raw.githubusercontent.com/aikenc/pipebuilder/main/pipebuilder.py
python3 pipebuilder.py --version

python3 pipebuilder.py init ./demo-space
python3 pipebuilder.py check ./demo-space
python3 pipebuilder.py build ./demo-space --dry-run
python3 pipebuilder.py build ./demo-space
```

`init` 会创建一个不含外部 Skill 的空脚手架：

```text
demo-space/
├── pipespace.json
└── demo-space.code-workspace
```

需要查看结构化构建计划时，运行
`python3 pipebuilder.py explain ./demo-space --format json`。要体验能力包选择和跨 Agent
投影，请继续运行下面的团队多管线示例。

## 运行“一个 project、多条管线”示例

仓库中的
[examples/multi-pipeline-project](examples/multi-pipeline-project)
包含一份示例 project、共享能力包，以及两条使用不同能力组合的 PipeSpace：

```bash
git clone https://github.com/aikenc/pipebuilder.git
cd pipebuilder

python3 pipebuilder.py check examples/multi-pipeline-project/pipespaces/feature-development
python3 pipebuilder.py check examples/multi-pipeline-project/pipespaces/bugfix-review

python3 pipebuilder.py explain examples/multi-pipeline-project/pipespaces/feature-development
python3 pipebuilder.py build examples/multi-pipeline-project/pipespaces/feature-development
```

构建后，平台配置只会生成在所选 PipeSpace 中，不会写入它引用的 `project/`：

```text
feature-development/
├── AGENTS.md
├── .agents/skills/feature-implementation/
├── .cursor/
│   ├── rules/
│   └── skills/feature-implementation/
└── .pipebuilder/lock.json
```

在 Cursor 中打开 `feature-development.code-workspace`；使用 Codex 时，从
`feature-development/` 目录启动客户端。两者都会看到 `pipeline` 与 `project` 两个
workspace folder，并加载当前管线生成的配置。

如需查看精简的四 Agent 输入及独立审阅的预期输出，请访问
[examples/all-agents-golden](examples/all-agents-golden)。它是 E2E 测试复制到临时
Sandbox 的唯一静态示例真相源。

## PipeSpace 如何工作

每个 PipeSpace 至少包含一个声明文件和一个 VS Code/Cursor workspace 文件：

```text
feature-development/
├── pipespace.json
└── feature-development.code-workspace
```

`pipespace.json` 选择目标 Agent、Skills、tags 和 Skill Provider：

```json
{
  "schema": "pipespace.v1",
  "name": "feature-development",
  "agents": ["codex", "cursor"],
  "skills": ["feature-implementation"],
  "tags": [],
  "skillProviders": [
    {"type": "folder", "path": "../../shared-skills"}
  ]
}
```

workspace 文件同时包含 PipeSpace 自身和一个或多个外部 project folder。`pipeline`
folder 让客户端发现生成在 PipeSpace 根的原生配置，`project` folder 指向 project：

```json
{
  "folders": [
    {"name": "pipeline", "path": "."},
    {"name": "project", "path": "../../project"}
  ]
}
```

构建流程：

```text
能力包 + PipeSpace 声明 + workspace 文件
                    ↓
             PipeBuilder plan
                    ↓
      各 Agent 的原生 Skills / Rules / Hooks / 配置
                    ↓
          .pipebuilder/lock.json
```

`lock.json` 记录 Skill Provider、Skill、来源、目标文件和摘要。`clean` 只删除有效 lock
证明属于 PipeBuilder 的生成物，不猜测其他文件的所有权。

## 当前支持状态

PipeBuilder 0.5.0 内置四个平台 Adapter。不同验证等级必须分开理解：

| Agent | 当前生成能力 | 验证状态 |
| --- | --- | --- |
| Codex | Skills、`AGENTS.md`、config/agents/MCP、Hooks、Rules | 自动化真实客户端 E1；真实模型 E2 |
| Cursor | Skills、workspace Rule、Rules、Commands | 真实客户端人工 E1；自动化 E1 待补 |
| CodeBuddy | Skills、固定 workspace Rule、Commands、Agents、Settings/Hooks、MCP | E0 生成与有限结构校验 |
| Claude Code | Skills、`CLAUDE.md`、Rules、Commands、Agents、Settings/Hooks、MCP | E0 生成与有限结构校验 |

`client-verified` 表示已经在真实客户端验证；`generated-only` 表示已验证生成结果和
当前实现支持的结构，但尚未建立真实客户端 E1。状态会写入 `explain` 和
`.pipebuilder/lock.json`。

## Skill Provider

PipeBuilder 支持三类 Skill 来源：

1. `.pipebuilder/skills/`：当前 PipeSpace 的本地能力，优先级最高。
2. Folder Skill Provider：引用本机或仓库内的共享能力目录。
3. Git Skill Provider：按 branch 或 tag 获取能力仓库，并在 lock 中固定到 commit。

Folder Skill Provider：

```json
{
  "type": "folder",
  "path": "../../shared-skills"
}
```

Git Skill Provider：

```json
{
  "type": "git",
  "url": "https://example.com/team/agent-skills.git",
  "tag": "v1.0.0",
  "subdir": "skills"
}
```

Git cache 位于当前 PipeSpace 的 `.pipebuilder/cache/git/`。`--offline` 只使用已有 lock
和本地 immutable snapshot，不访问远程。认证交给 Git credential helper 或 SSH agent，
不得把凭据写入 `pipespace.json`。

Skill Provider 还可以声明构建后的命令。`check`、`explain` 和 `build --dry-run`
只展示命令，只有正式 `build` 才会调用。

## 常用命令

单个 PipeSpace：

```bash
python3 pipebuilder.py init [SPACE]
python3 pipebuilder.py check [SPACE]
python3 pipebuilder.py explain [SPACE] --format json
python3 pipebuilder.py build [SPACE] [--offline] [--dry-run]
python3 pipebuilder.py clean [SPACE]
```

一层 PipeSpace Tree：

```bash
python3 pipebuilder.py check-tree [ROOT]
python3 pipebuilder.py explain-tree [ROOT] --format json
python3 pipebuilder.py build-tree [ROOT]
python3 pipebuilder.py verify-tree [ROOT]
python3 pipebuilder.py clean-tree [ROOT]
```

Tree 只编排显式声明的一层 children，不扫描目录，也不隐式递归。普通 `build` 和 `clean`
始终只处理指定的单个 PipeSpace。

自动化应使用 `--format json`，并依赖 `pipebuilder-report.v1` 中稳定的 diagnostic code，
不要解析面向人的提示文本。

## 所有权与安全边界

人工维护的输入：

- `pipespace.json` 与 `<name>.code-workspace`
- `.pipebuilder/skills/`
- `.pipebuilder/agents/<agent>/`
- Skill Provider 中的标准 Skill 与 `.pipe-agents/<agent>/`

Builder 管理的输出：

- `AGENTS.md`、`CLAUDE.md`
- `.agents/skills/`
- `.codex/`、`.cursor/`、`.codebuddy/`、`.claude/`
- `.mcp.json`
- `.pipebuilder/generated/` 与 `.pipebuilder/lock.json`

不要直接维护生成文件。将需要保留的内容移动到对应 source 后重新 `build`。未被当前 plan
或旧 lock 登记的其他文件不会被修改。

## 文档

从 [文档索引](docs/README.md) 开始：

- [PipeSpace 与 Skill Provider 协议](docs/pipebuilder-space-json-spec.md)
- [四 Agent Adapter 规范](docs/pipebuilder-agent-adapters.md)
- [PipeSpace Tree 协议](docs/pipebuilder-space-tree-spec.md)
- [E2E 运行说明](tests/e2e/README.md)
- [E2E 覆盖矩阵](tests/e2e/COVERAGE.md)

## 开发与测试

所有测试都通过子进程调用最终发布文件，不 import production：

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
```

GitHub Actions 在 Linux、Windows、macOS 的 Python 3.11 上运行 E0；Linux 额外覆盖
Python 3.7 和 Python 3.13。Cursor 当前采用人工真实客户端 E1 验证，尚未加入自动化 case。

## 许可证

[MIT License](LICENSE)
