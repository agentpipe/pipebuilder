# PipeBuilder

[English](README.md) | [简体中文](README.zh-CN.md)

[![E2E](https://github.com/agentpipe/pipebuilder/actions/workflows/e2e.yml/badge.svg)](https://github.com/agentpipe/pipebuilder/actions/workflows/e2e.yml)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 跨 AI 编程 Agent 复用同一套 Skill；让一个 project 拥有多条任务专属 Agent
> 管线，每条管线独立选择自己的能力集合。

PipeBuilder 是面向团队的**跨 Agent Skill 复用**与**任务专属 AI 编程 Agent 管线**
构建工具。团队只需维护一份能力来源，就能在 Cursor、Claude Code、Codex 和 CodeBuddy
之间共享标准 Agent Skill；每条任务管线则只加载自己真正需要的 Skills、Rules、Hooks、
Commands 和平台原生配置。

## PipeBuilder 解决的两个问题

![AI Agent 工程中的两个常见问题：同一 Skill 为不同 Agent 产生大量逐渐漂移的副本，而所有任务共用全部 Rules 又会带来噪声和冲突。](docs/assets/pipebuilder-pain-points.jpg)

1. **同一个 Skill 需要为不同编程 Agent 反复适配。** 多份副本逐渐漂移，修复无法同步，
   平台专属扩展也散落在不同仓库。
2. **一个 project 被迫承载所有任务的 Agent 能力。** 无关 Skills 扩大上下文，相互冲突的
   Rules 争夺注意力，无关 Hooks 还可能在错误任务中运行。

## 只构建每个任务真正需要的能力

![PipeBuilder 组合可复用 Skills 与任务专属管线声明，为开发、缺陷修复和代码审查生成聚焦且支持多 Agent 的 workspace。](docs/assets/pipebuilder-overview.jpg)

PipeBuilder 将可复用能力包与 PipeSpace 声明组合起来，只把当前任务选中的能力编译成各
目标 Agent 的原生格式。需求开发、缺陷修复、代码审查和发布可以分别拥有聚焦的配置，
无需复制 project，也无需让所有任务加载全部能力。

PipeBuilder 是构建期配置编译器，不是 CI/CD 流水线，也不是多 Agent 运行时编排器。
它生成各编程 Agent 能直接识别的原生文件。

## 跨 Agent 复用 Agent Skills

一个可复用能力包把可移植的 Agent Skill 和可选的平台原生扩展放在一起：

```text
shared-skills/bugfix-review/
├── SKILL.md                          # 跨 Agent 共享的可移植 Skill
├── scripts/
├── references/
└── .pipe-agents/                    # 可选的平台原生扩展
    ├── codex/AGENTS.md
    ├── cursor/.cursor/rules/
    ├── codebuddy/.codebuddy/settings.json
    └── claude-code/.claude/settings.json
```

- `SKILL.md`、scripts、references 和 assets 构成可移植 Skill，并安装到各 Agent 的标准
  Skill 目录。
- `.pipe-agents/<agent>/` 保留对应 Agent 的原生格式。PipeBuilder 通过匹配的 Adapter
  投影这些文件，不假装不同平台的 Rules 或 Hooks 可以无损互译。
- Folder 和 Git **Skill Provider** 用于共享完整能力包；Git Provider 会把 branch 或
  tag 解析并固定到 lock 中的 commit，保证构建可复现。

最终，团队只维护一份跨 Agent Skill 来源；平台差异与 Skill 放在一起，不再复制到每个
project 和 Agent 目录。

## 一个 project，多条任务专属 Agent 管线

**PipeSpace** 是与业务代码 `<project>` 解耦的任务专属 Agent 管线根。每个 PipeSpace
独立选择 Agents、Skills、tags、Skill Providers 和管线级原生覆盖，同时通过 workspace
文件引用同一份 project：

```text
project/
├── ...                              # 业务代码
└── pipespaces/
    ├── shared/skills/               # 可跨 Agent 复用的能力包
    ├── feature-development/         # 功能开发 Skills 与 Agent 配置
    ├── bugfix-review/               # 诊断与审查能力
    └── release/                     # 仅发布任务使用的能力
```

首推把 `pipespaces/` 放在 project 内。每条管线生成的 Agent 配置留在自己的 PipeSpace，
不会污染 project 根目录：

```text
Skill Providers + PipeSpace 本地 Skills + PipeSpace Agent 原生覆盖
                              ↓
                 pipespace.json 选择能力子集
                              ↓
                    PipeBuilder Adapter plan
                              ↓
        各 Agent 的原生 Skills / Rules / Hooks / 配置
```

需求开发、缺陷修复、代码审查和发布由此拥有独立的能力集合；既不复制 project，也不把
所有 Skill 同时加载进同一个 Agent workspace。

> PipeSpace 隔离的是 Agent 配置、上下文和能力组合，不是代码写入。多个 Agent 并行修改
> 同一个 project 时，仍应使用 Git 分支、worktree 或独立 clone。

## 自举 PipeBuilder 与首个 PipeSpace

先在项目内创建公共 Skill Provider，并把最新 Release 解压到这里：

```text
<project>/pipespaces/
├── shared/skills/pipebuilder/
└── <project>-dev/
```

macOS 或 Linux：

```bash
PROJECT_ROOT="/path/to/project"
SHARED_SKILLS="${PROJECT_ROOT}/pipespaces/shared/skills"
mkdir -p "${SHARED_SKILLS}"
curl -fsSL "https://github.com/agentpipe/pipebuilder/releases/latest/download/pipebuilder-skill.zip" -o /tmp/pipebuilder-skill.zip
unzip -qo /tmp/pipebuilder-skill.zip -d "${SHARED_SKILLS}"
```

PowerShell：

```powershell
$ProjectRoot = "C:\path\to\project"
$SharedSkills = Join-Path $ProjectRoot "pipespaces/shared/skills"
New-Item -ItemType Directory -Force $SharedSkills | Out-Null
Invoke-WebRequest "https://github.com/agentpipe/pipebuilder/releases/latest/download/pipebuilder-skill.zip" -OutFile "$env:TEMP/pipebuilder-skill.zip"
Expand-Archive "$env:TEMP/pipebuilder-skill.zip" -DestinationPath $SharedSkills -Force
```

创建第一个项目内 PipeSpace。两个相对路径都从新 PipeSpace 出发解析：

```bash
PROJECT_NAME="project"
SPACE="${PROJECT_ROOT}/pipespaces/${PROJECT_NAME}-dev"
BUILDER="${SHARED_SKILLS}/pipebuilder/pipebuilder.py"
python3 "${BUILDER}" init "${SPACE}" \
  --name "${PROJECT_NAME}-dev" \
  --project ../.. \
  --shared-skills ../shared/skills
python3 "${BUILDER}" check "${SPACE}"
python3 "${BUILDER}" explain "${SPACE}"
python3 "${BUILDER}" build "${SPACE}" --dry-run
python3 "${BUILDER}" build "${SPACE}"
python3 "${BUILDER}" verify "${SPACE}"
```

`init` 会写入 workspace folder、配置公共 folder Provider，并选择 `pipebuilder`。
第一次 build 后，PipeBuilder Skill 会投影到所有已配置 Agent。

PipeSpace 也可以放在项目外。让公共 Skills 与各 PipeSpace 保持在同一管线根下，再传入
相对新 PipeSpace 的 `--project` 和 `--shared-skills` 路径即可。

从最新 Release 更新公共 Skill：

```bash
python3 <project>/pipespaces/shared/skills/pipebuilder/scripts/update.py
```

## 单文件 CLI 快速开始

运行时只需要 Python 3.7+ 和单个 `pipebuilder.py` 文件。只有使用 Git Skill Provider
时才需要系统安装 Git；不需要安装 Python 第三方包。

```bash
curl -O https://raw.githubusercontent.com/agentpipe/pipebuilder/main/pipebuilder.py
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
git clone https://github.com/agentpipe/pipebuilder.git
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

PipeSpace 本地可复用 Skills 位于 `.pipebuilder/skills/`，来源优先级最高；管线专属的
Agent 原生配置位于 `.pipebuilder/agents/<agent>/`，用于补充从 Skill Provider 选择的
共享能力包。

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

PipeBuilder 0.1.3 需要 Python 3.7+，支持三大桌面平台：

| 平台 | 状态 | 已测试版本 |
| --- | --- | --- |
| Linux | 支持 | Python 3.7、3.14 |
| Windows | 支持 | Python 3.7、3.9、3.11、3.13、3.14 |
| macOS | 支持 | Python 3.7、3.14 |

项目内置四个 Agent Adapter：

| Agent | 状态 | 当前生成能力 |
| --- | --- | --- |
| Codex | 支持（`client-verified`） | Skills、`AGENTS.md`、config/agents/MCP、Hooks、Rules |
| Cursor | 支持（`client-verified`） | Skills、workspace Rule、Rules、Commands |
| Claude Code | 支持（`client-verified`） | Skills、`CLAUDE.md`、Rules、Commands、Agents、Settings/Hooks、MCP |
| CodeBuddy | 预览（`generated-only`） | Skills、固定 workspace Rule、Commands、Agents、Settings/Hooks、MCP |

`client-verified` 表示已经在真实客户端验证；`generated-only` 表示已验证生成结果和
当前实现支持的结构，但尚未建立真实客户端 E1。状态会写入 `explain` 和
`.pipebuilder/lock.json`。

## Skill 来源与 Skill Provider

PipeBuilder 从一个隐式本地来源和两类已配置 Provider 解析 Skills：

1. `.pipebuilder/skills/`：当前 PipeSpace 隐式的 `space-local` 来源，优先级最高；
   它不是 `skillProviders[]` 中的配置项；目录不存在时不写入空 Provider 记录。
2. Folder Skill Provider：已配置的 Provider，引用本机或仓库内的共享能力目录。
3. Git Skill Provider：已配置的 Provider，按 branch 或 tag 获取能力仓库，并在 lock
   中固定解析后的 commit。

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
python3 pipebuilder.py verify [SPACE]
python3 pipebuilder.py clean [SPACE]
```

所有命令统一读取 `pipespace.json`。默认情况下，PipeBuilder 自动发现三层目录内嵌套的
PipeSpace，并对完整层级执行操作。可通过 `"children": {"scanDepth": N}` 调整深度，
设为 `0` 时只处理根 Space。扫描会跳过隐藏目录、生成目录和符号链接目录。

不存在单独的 Tree manifest 或命令族。发现嵌套 PipeSpace 后，所有成员都会在写入前完成
只读规划；`build` 按根到子级顺序应用，`verify` 检查层级总收据及每个成员，`clean`
则先清理子级再清理根。

自动化应使用 `--format json`，并依赖 `pipebuilder-report.v1` 中稳定的 diagnostic code，
不要解析面向人的提示文本。
仅处理根 Space 时，成功的 JSON `verify` 通过 `details.receiptDigest` 返回已精确验证的
`.pipebuilder/lock.json` 摘要，不再创建只有一个成员的冗余总收据。

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
- [E2E 运行说明](tests/e2e/README.md)
- [E2E 覆盖矩阵](tests/e2e/COVERAGE.md)

## 开发与测试

所有测试都通过子进程调用最终发布文件，不 import production：

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
```

[GitHub Actions](https://github.com/agentpipe/pipebuilder/actions/workflows/e2e.yml) 运行上表所列
E0 平台矩阵。仓库还包含 Codex、Cursor 和 Claude Code 的已安装客户端 E1 用例，但这些
用例目前只在已安装对应客户端的环境中运行，尚未接入 GitHub 托管 Actions。CodeBuddy
仍为 `generated-only`。

## 发布版本

修改 `pipebuilder.py` 中的 `VERSION`，并同步文档版本和版本契约测试。主分支 E0
通过后，创建并推送匹配的 tag：

```bash
git tag -a v0.1.3 -m "PipeBuilder v0.1.3"
git push origin v0.1.3
```

发布工作流会重新运行完整 E0 平台矩阵，校验 tag 与 `VERSION` 一致，然后发布
`pipebuilder.py`、`pipebuilder.py.sha256`、`pipebuilder-skill.zip` 和
`pipebuilder-skill.zip.sha256`。Skill 更新器会先验证 ZIP 校验和，再替换已安装文件。
也可以通过工作流的手动输入发布或重试已有 tag。

## 许可证

[MIT License](LICENSE)
