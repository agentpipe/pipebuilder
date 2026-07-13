# HarnessBuilder：去中心化跨 Agent Harness Space Builder 架构提案

状态：proposal  
日期：2026-07-13  
适用范围：THarness Builder 的独立化、Harness Space 目录协议、跨 Agent 工作空间构建、现有 THarness workspace 迁移

相关文档：

- [HarnessBuilder Harness Space 与 Skill Provider 协议](harnessbuilder-space-json-spec.md)：`harness-space.json`、Skill Provider、选择和 workspace 规则协议。
- [HarnessBuilder 四 Agent Adapter 首版规范](harnessbuilder-agent-adapters.md)：Codex、Cursor、CodeBuddy、Claude Code 四个平台的首版投影规范。
- [HarnessBuilder Python E2E 集成测试架构](harnessbuilder-test-architecture.md)：黑盒 Harness Space sandbox、golden、ownership、跨平台、真实客户端和真实模型门禁。
- [HarnessBuilder Skill Fixture Catalog](harnessbuilder-skill-fixture-catalog.md)：五套 Skill fixture pack、四 Agent capability matrix、Harness Space overlay 和 Codex live probes。

本提案接受后，将取代 `tagent-builder-proposal.md` 中关于中心化 THarness Builder、固定 shared skills 和独立生成 workspace 的设计；`platform-capability-report.md` 继续作为前三个平台的历史调研快照，新增 Claude Code 结论以本文配套 adapter 规范为准。

---

## 1. 提案结论

从 THarness 中抽离一个独立工具 `harnessbuilder`。它是一个无中心仓库依赖、单文件分发、在 Harness Space 目录内原地工作的跨 Agent Harness Space Builder。

HarnessBuilder 的唯一职责是：

> 读取当前 Harness Space 目录、必需的 `harness-space.json`、人工维护的 `<name>.code-workspace`（`name` 来自 manifest）、多个 Skill Provider、Skill 级 `.harness-agents` 和 Harness Space 级 `.harness-agents`，在当前目录生成四个 Coding Agent 可直接发现的 skills、rules、commands、agents、hooks 和配置，并写入可追溯的构建 lock。

首版交付为：

```text
harnessbuilder.py
```

不再要求 npm package、pip install、TypeScript 编译产物、THarness repository root 或固定目录注册中心。

HarnessBuilder 首版内置四个 Agent adapter：

```text
codex
cursor
codebuddy
claude-code
```

### 1.1 Canonical namespace

首版只接受一套名称，不同时维护新旧 alias：

| 角色 | Canonical name | Ownership |
| --- | --- | --- |
| CLI/发布文件 | `harnessbuilder.py` | Tool release |
| Harness Space manifest | `harness-space.json` | Human-owned、必需 |
| Manifest schema | `harness-space.v1` | Protocol |
| 最终 workspace | `<harness-space.json.name>.code-workspace` | Human-owned、必需 |
| Space-level Agent 输入 | `.harness-agents/<agent>/` | Human-owned build input |
| Skill-level Agent 输入 | `<skill>/.harness-agents/<agent>/` | Skill source build input |
| Core generated state | `.harnessbuilder/` | HarnessBuilder-owned |
| Ownership lock | `.harnessbuilder-lock.json` | HarnessBuilder-owned |
| Lock schema | `harnessbuilder-lock.v1` | Protocol |
| CLI report schema | `harnessbuilder-report.v1` | Protocol |
| Diagnostics | `HB001` 起 | Protocol |
| Command environment | `HARNESSBUILDER_*` | Process-local build context |

`.harness-agents/` 使用复数，因为同一个 Harness Space 或 Skill 可以同时声明多个 Agent 的输入。文档中的根目录写法是 `<space-root>/.harness-agents/`；它不是文件系统绝对路径 `/.harness-agents/`。

`.harness-agents/` 和 `.harnessbuilder/` 必须分开：前者是 Human/Skill 提交的 source，后者是可清理、可恢复的 generated state。平台输出继续使用 `.codex/`、`.cursor/`、`.codebuddy/`、`.claude/` 等原生目录，不能为了统一命名再包一层 HarnessBuilder 目录。

未来可以引入 adapter plugin，但首版内置 adapter，确保复制一个 `harnessbuilder.py` 就能完成标准构建。

---

## 2. 已确认的设计决策

### 2.1 Harness Space 与工作空间是同一个目录

删除旧 THarness 中“中心 source 与生成 workspace 分离”的二阶段模型：

```text
旧模型：
central-sources/foo/ -> Builder -> generated-spaces/foo/

新模型：
foo/ -> harnessbuilder build -> foo/
```

Harness Space 目录同时承载：

- 人工维护的 workspace 定义；
- Harness Space 私有构建输入；
- Agent 实际 cwd；
- Agent 平台的生成配置；
- Harness Space runtime 和 state；
- HarnessBuilder build lock。

“Harness Space source”和“生成后的 workspace”不再是两个实体。

### 2.2 Workspace 文件完全归 Human 所有

删除：

```text
<name>.code-workspace.src
```

Harness Space 直接包含最终 workspace：

```text
<harness-space.json.name>.code-workspace
```

HarnessBuilder：

- 读取并校验它；
- 从 `folders` 生成项目路径 rule；
- 不复制、不重命名、不改写、不重排 workspace；
- 不把生成结果回写 workspace；
- 不从生成 rule 反向恢复程序状态。

Workspace 文件是项目名称、路径和顺序的唯一事实源；Harness Space 的逻辑名称和构建配置以 `harness-space.json` 为唯一事实源。

### 2.3 Harness Space name 由 `harness-space.json` 确定

`harness-space.json` 必需，`name` 是 Harness Space 的 canonical logical name：

```json
{
  "schema": "harness-space.v1",
  "name": "my-harness-space",
  "agents": ["codex", "cursor", "codebuddy", "claude-code"],
  "skills": [],
  "tags": [],
  "skillProviders": []
}
```

Harness Space 根目录 basename 只是物理容器名，不参与 identity 推导，也不要求与 `name` 一致。例如以下目录仍然表示 `my-harness-space`：

```text
/work/spaces/local-checkout-17/
```

Workspace 文件名由 manifest 中的 `name` 推导，因此必须为：

```text
my-harness-space.code-workspace
```

这样移动或重命名 Harness Space 目录不会改变逻辑身份；复制目录也不会自动创建新身份。要 fork/rename Harness Space，必须显式修改 `harness-space.json.name`，并同步重命名 workspace 文件及其第一项 folder name。

### 2.4 Harness Space 输入按作用域分层

Harness Space-local Skills 和构建脚本放在 `private/`：

```text
private/
├── skills/
└── scripts/
```

这里的 `private` 表示“HarnessBuilder 私有输入面”，不是 secret store。该目录可以进入 Git，但不得存储 token、密码和私钥。

Harness Space 级 Agent 专属输入直接放在 Harness Space 根目录：

```text
.harness-agents/<agent>/
├── rules/
├── commands/
├── hooks/
├── agents/
├── config/
├── mcp/
└── files/
```

不再保留 `tagents` 或 `resources` 这类平行概念。`.harness-agents` 是 Agent 专属输入的唯一扩展面：位于 Skill 根目录时属于该 Skill，位于 Harness Space 根目录时属于整个 Harness Space。

### 2.5 Skill 使用开放标准目录

Skill package 统一为：

```text
skills/foo/
├── SKILL.md
├── scripts/
├── references/
├── assets/
└── .harness-agents/
```

不再支持新建：

```text
skills/foo/skill/SKILL.md
```

Agent 专属文件放在 Skill 根目录的隐藏扩展面：

```text
skills/foo/.harness-agents/<agent>/...
```

`.harness-agents/` 不属于标准 Skill common package。复制到平台 Skill 目录时必须排除，只有对应 adapter 可以读取它。

### 2.6 Skill 来源统一称为 Provider

`skillFolders` 更名为：

```text
skillProviders
```

首版只实现 `folder` Provider；协议使用 provider type，给 Git、HTTP registry、package 和 artifact provider 留出扩展空间。

### 2.7 显式 Skill 名单优先，tag 匹配补充

保留：

- `skills` 显式名单；
- Harness Space `tags` 与 Skill frontmatter tags 匹配。

两者不再互斥。选择结果是并集：

```text
private skills
  UNION explicit skills
  UNION tag-matched skills
```

同一个 Skill 同时由名单和 tag 命中时，lock 记录 `selectedBy: skills`，因为显式名单优先。

### 2.8 Workspace context 只生成 rule，不写 `AGENTS.md`

Core 只生成一份 canonical workspace rule：

```text
.harnessbuilder/workspace-rule.md
```

Cursor、CodeBuddy 和 Claude Code adapter 将其投影到各自原生 rules 目录。Codex adapter 不创建、追加或修改 `AGENTS.md`，而是生成 project-local `SessionStart` 和 `SubagentStart` hooks，在会话启动、恢复、压缩恢复和子 Agent 启动时读取该 rule，并通过 stdout 注入额外 developer context。

仓库已有的 `AGENTS.md` 完全归 Human 所有，仍可由 Codex 自身发现，但不进入 HarnessBuilder ownership 或 lock。

---

## 3. 最终目录结构

```text
local-checkout-17/                         # Harness Space root；basename 无协议语义
├── harness-space.json                         # 必需；Harness Space identity/config
├── my-harness-space.code-workspace           # 必需；文件名由 manifest name 推导，Human-owned
├── .harness-agents/                            # Space-level Agent-specific inputs
│   ├── codex/
│   │   └── hooks/
│   ├── cursor/
│   │   ├── rules/
│   │   └── commands/
│   ├── codebuddy/
│   └── claude-code/
├── private/
│   ├── skills/                           # Harness Space-local skills
│   │   └── space-supervisor/
│   │       ├── SKILL.md
│   │       ├── scripts/
│   │       ├── references/
│   │       └── .harness-agents/
│   │           ├── codex/
│   │           ├── cursor/
│   │           ├── codebuddy/
│   │           └── claude-code/
│   └── scripts/                          # Harness Space build/runtime scripts
│
├── .harnessbuilder/
│   ├── workspace-rule.md                 # Generated canonical workspace rule
│   └── transactions/                     # Transient crash-recovery journals；成功后为空/不存在
├── .harnessbuilder-lock.json                # Generated ownership/provenance
├── .agents/skills/                       # Generated Codex skills
├── .codex/                               # Generated/merged Codex files
├── .cursor/                              # Generated/merged Cursor files
├── .codebuddy/                           # Generated/merged CodeBuddy files
├── .claude/                              # Generated/merged Claude Code files
├── runtime/                              # Optional, Harness Space command owns
└── saved/                                # Optional, runtime owns
```

HarnessBuilder 不创建没有语义的 `work/`、`artifacts/`、`logs/` 空目录。

---

## 4. Harness Space 最小协议

### 4.1 必需的最小 manifest

每个 Harness Space 都必须提交 `harness-space.json`。最小配置显式声明 identity、目标 Agent 和 Skill 选择输入：

```json
{
  "schema": "harness-space.v1",
  "name": "my-harness-space",
  "agents": ["codex", "cursor", "codebuddy", "claude-code"],
  "skills": [],
  "tags": [],
  "skillProviders": []
}
```

无论是否配置外部 Provider，都会隐式启用最高优先级 Provider：

```text
private/skills
```

其中所有合法 Skill 都被选中。

### 4.2 常见配置

```json
{
  "schema": "harness-space.v1",
  "name": "my-harness-space",
  "agents": [
    "codex",
    "cursor",
    "codebuddy",
    "claude-code"
  ],
  "skills": [
    "git",
    "integration-test"
  ],
  "tags": [
    "ue",
    "android"
  ],
  "skillProviders": [
    {
      "type": "folder",
      "path": "../../shared-skills"
    },
    {
      "type": "folder",
      "path": "../team-skills"
    }
  ],
  "command": [
    "python3",
    "private/scripts/build_runtime.py"
  ]
}
```

完整字段和选择算法见 `harnessbuilder-space-json-spec.md`。

---

## 5. Workspace contract

### 5.1 文件约束

`<name>.code-workspace` 至少包含两个 folder：

```json
{
  "folders": [
    {
      "name": "my-harness-space",
      "path": "."
    },
    {
      "name": "game-project",
      "path": "../../game-project"
    },
    {
      "name": "engine-reference",
      "path": "../../engine-reference"
    }
  ],
  "settings": {}
}
```

顺序继续作为稳定协议：

1. 第一项：当前 Harness Space workspace，name 必须等于 `harness-space.json.name`，path 必须为 `.`。
2. 第二项：默认主项目，Agent 默认在这里修改、验证和提交。
3. 第三项及之后：reference projects，默认只读。

HarnessBuilder 校验：

- `folders` 是非空数组且至少两项；
- name 非空且唯一；
- path 非空且为相对路径；
- 第一项满足 name/path 约束；
- 第二项及之后的目录在 build 时存在；
- 解析后的路径不重复；
- workspace JSON 合法。

HarnessBuilder 不校验外部项目是否是 Git repository；这是 Harness Space command 或 runtime Driver 的责任。

### 5.2 项目路径 rule

HarnessBuilder 根据 workspace 生成中立文件：

```text
.harnessbuilder/workspace-rule.md
```

内容包括：

- Harness Space name；
- Agent cwd；
- workspace 文件名；
- 主项目名称和相对路径；
- reference project 名称和相对路径；
- 项目角色由顺序确定；
- 默认写入、验证和提交边界；
- workspace 是程序事实源，rule 只是 Agent 投影；
- `private/` 是 Builder 输入，除非任务明确要求，不应修改。

各 adapter 将同一语义投影到平台原生规则面。不得把本机 absolute path 写入 rule，以保持 Harness Space 可移动性。

---

## 6. Skill Provider 与解析模型

### 6.1 Provider 优先级

有效 Provider 顺序为：

```text
1. implicit private provider: ./private/skills
2. harness-space.json skillProviders[0]
3. harness-space.json skillProviders[1]
4. ...
```

越靠前优先级越高。同名 Skill 只选择第一个合法候选；低优先级候选进入 lock 的 `shadowedCandidates`，不做目录树 merge。

### 6.2 首版 folder Provider

```json
{
  "type": "folder",
  "path": "../../shared-skills"
}
```

Provider root 的直接子目录是 Skill：

```text
../../shared-skills/
├── git/SKILL.md
├── ue-cli/SKILL.md
└── integration-test/SKILL.md
```

不递归猜测任意深度的 `SKILL.md`。

### 6.3 未来 Git Provider

协议预留：

```json
{
  "type": "git",
  "url": "https://example.com/team/skills.git",
  "ref": "v2.1.0",
  "subdir": "skills"
}
```

首版读到非 `folder` Provider 必须给出 `unsupported provider type`，不能忽略或猜测。

Git Provider 落地时必须：

- 使用独立 cache；
- 将 ref 解析到 immutable commit；
- lock 记录 URL、ref、commit、subdir 和 Skill digest；
- 不在 Harness Space 目录中维护可变 checkout；
- offline build 可以复用已锁定 cache；
- credential 不进入 manifest 或 lock。

---

## 7. Build phases

```text
1. 解析 CLI 和 Harness Space root
2. build/clean 检测并恢复未完成的 transaction journal；只读命令仅报告
3. 读取必需的 harness-space.json 并验证 schema
4. 由 harness-space.json.name 确定 canonical logical name
5. 读取由 name 推导的 <name>.code-workspace
6. 解析项目角色并生成 workspace rule IR
7. 索引 implicit/private 和 configured Skill Providers
8. 按 provider priority 解析同名 Skill
9. 选择 private、explicit 和 tag-matched Skills
10. 解析 Skill common package、Skill .harness-agents 和 Harness Space root .harness-agents
11. 为 configured agents 构建 platform operations
12. 做 schema、冲突、安全和人工内容保护检查
13. 输出 dry-run/build plan
14. 执行可选 command
15. 再次验证全部 build input digest，防止 command 改变已规划输入
16. 将新内容和旧 target backup 写入 transaction staging，并持久化 journal
17. 通过可恢复 commit 应用 operations，并清理旧 lock 中已失效的受管内容
18. 原子写入 .harnessbuilder-lock.json，标记 transaction 完成并删除 journal
```

任一校验失败时，不执行写入。

可选 command 非零退出时停止构建，并透传 stdout、stderr 和 exit code。

---

## 8. 原地构建与 ownership

原地构建比输出到独立生成目录更容易碰到人工配置，因此 HarnessBuilder 必须使用严格 ownership。

### 8.1 写入规则

```text
目标不存在
  -> 可以创建

目标存在，旧 lock 证明由 HarnessBuilder 管理，且当前 digest 未发生未授权修改
  -> 可以更新

目标存在，但不在旧 lock
  -> 默认冲突失败

目标存在于旧 lock，但本次不再生成
  -> 只删除该受管文件或受管字段

目标被 Human 在 build 后修改
  -> 默认冲突失败，要求 Human 决定保留、迁移或显式 adopt
```

### 8.2 不允许的行为

HarnessBuilder 不得：

- 递归删除整个 `.cursor/`、`.codex/`、`.claude/` 或 `.codebuddy/`；
- 覆盖未登记的人工文件；
- 通过目录名猜测一个文件属于 Builder；
- 把 generated JSON 整文件覆盖到包含人工字段的 settings；
- 在 source 与 target 是同一真实路径时复制；
- 将 `.harness-agents/` 复制进目标 Skill common package；
- 将 secret value 写入 lock。

### 8.3 Semantic merge

以下目标必须按平台语义 merge：

- `.codex/config.toml`；
- `.codex/hooks.json`；
- `.claude/settings.json`；
- `.mcp.json`；
- Cursor hooks/MCP/config；
- `.codebuddy/settings.json`；
- `.codebuddy/mcp.json`。

首版没有实现某种 semantic document 时，应针对该 artifact 报明确的 unsupported 错误。不得降级成 last-write-wins。

---

## 9. Lock contract

统一使用：

```text
.harnessbuilder-lock.json
```

它同时承担：

- 输入 provenance；
- provider 解析结果；
- Skill 选择原因；
- 平台 adapter 版本；
- workspace digest；
- generated artifact ownership；
- semantic field ownership；
- clean/rebuild 基础。

示例：

```json
{
  "schema": "harnessbuilder-lock.v1",
  "builder": {
    "version": "0.1.0",
    "digest": "sha256:..."
  },
  "space": {
    "name": "my-harness-space",
    "root": ".",
    "manifestDigest": "sha256:...",
    "workspace": "my-harness-space.code-workspace",
    "workspaceDigest": "sha256:..."
  },
  "agents": [
    "codex",
    "cursor",
    "codebuddy",
    "claude-code"
  ],
  "providers": [],
  "skills": [],
  "artifacts": [],
  "command": {
    "argv": ["python3", "private/scripts/build_runtime.py"],
    "exitCode": 0
  }
}
```

为了 deterministic build，`generatedAt` 可以记录，但不得参与可复现 digest。

---

## 10. CLI

```bash
# 默认构建 cwd
python3 harnessbuilder.py build

# 构建指定 Harness Space
python3 harnessbuilder.py build /path/to/my-harness-space

# 解析、校验并打印计划，不写文件、不执行 command
python3 harnessbuilder.py check

# 同一结果的稳定机器可读报告
python3 harnessbuilder.py check --format json

# 展示 Provider、Skill 选择、shadow 和平台目标
python3 harnessbuilder.py explain

# 构建计划，不写文件；默认不执行 command
python3 harnessbuilder.py build --dry-run

# 只移除 lock 证明由 HarnessBuilder 管理的内容
python3 harnessbuilder.py clean

# 版本
python3 harnessbuilder.py --version
```

`build` 只接受 Harness Space 目录和 HarnessBuilder 自己的通用参数；Harness Space command 参数必须写入 `harness-space.json`，避免不可追溯的临时构建变体。

`check`、`explain`、`build --dry-run` 以及 build/clean 的最终报告支持 `--format text|json`。JSON 使用版本化 `harnessbuilder-report.v1`，供测试和自动化消费；错误语义以 stable diagnostic code 为准，不要求调用方解析人类文案。

---

## 11. Python CLI 选型

### 11.1 结论

首版选择单个 `harnessbuilder.py`，允许重写现有 TypeScript Builder，不再把代码复用作为首要约束。

HarnessBuilder 的主要工作是解析 manifest、遍历文件、校验 schema、生成文本、执行子进程和维护 lock。这类配置编译型 CLI 与 Python 标准库契合，也便于复用同一 Python runtime 执行 Codex workspace context hook。

### 11.2 对比

| 维度 | 单 Python | 单 MJS |
| --- | --- | --- |
| CLI 标准库 | `argparse`、`pathlib`、`dataclasses`、`subprocess`、`hashlib`、`tempfile` 可直接覆盖 core | Node 标准库同样可实现，但整体更偏 package/runtime 生态 |
| JSON | 标准库完整读写 | 标准库完整读写 |
| TOML | Python 3.11 `tomllib` 可做可靠读取；受控写回仍需实现 | 无标准 TOML parser/renderer |
| YAML frontmatter | 实现协议所需的受控小解析器 | 同样需要受控小解析器 |
| 无 shell argv spawn | `subprocess.run(argv, shell=False)` | `spawnSync`/`spawn` |
| 单文件内置 adapter | class/registry 直接组织 | class/registry 直接组织 |
| 未来 adapter plugin | `importlib` | `import()` |
| 测试 | 标准库即可实现 subprocess-driven Python E2E runner | 通常需自建 runner 或引入 package tooling |
| Codex workspace hook | 可共用 Python runtime 和生成的 `.py` hook | 需要额外 Node runtime |
| 分发 | 一个 `.py` 文件，无 pip 依赖 | 一个 `.mjs` 文件，无 npm 依赖 |

Python 3.11 的 `tomllib` 只有读取能力，并不自动解决 TOML 的保注释写回。Codex config 仍需受控 semantic patcher、字段 ownership 和冲突检测；无法安全 round-trip 时必须失败，不能整文件覆盖。

### 11.3 Runtime baseline

建议首版要求：

```text
Python >= 3.11
```

实现只使用 Python 标准库，不依赖 pip package。文件顶部保留：

```python
#!/usr/bin/env python3
```

macOS/Linux 可直接分发：

```bash
chmod +x harnessbuilder.py
./harnessbuilder.py build
```

Windows 使用：

```powershell
py -3 harnessbuilder.py build
```

如果未来必须覆盖没有 Python 3.11 的主机，再评估 zipapp、standalone executable 或 Go/Rust 重写。

协议应独立于实现语言，因此 `harness-space.json`、Skill package、workspace 和 lock 不得包含 Python-specific 语义。

---

## 12. Adapter plugin 演进

首版内置四个 adapter，原因是：

- 单文件可独立运行；
- 平台行为可以通过同一套完整 Harness Space E2E 验收；
- schema 和 security policy 不受任意插件代码影响；
- 迁移阶段更容易稳定协议。

未来可以允许：

```json
{
  "agents": [
    "codex",
    {
      "id": "windsurf",
      "adapter": {
        "type": "module",
        "path": "private/scripts/adapters/windsurf.py"
      }
    }
  ]
}
```

但 plugin 是显式的第二阶段能力。启用外部 adapter 时，Harness Space 不再具备“只依赖一个可信 harnessbuilder 文件”的安全性质，因此必须：

- 显示 trust 提示；
- lock 记录 plugin realpath 和 digest；
- 禁止从网络 URL 直接执行 adapter；
- adapter API 只能生成 build operations，不能直接写文件；
- core 在应用 operations 前统一做 ownership 和冲突检查。

---

## 13. 保留与删除的 THarness Builder 能力

| THarness 能力 | HarnessBuilder 处理 |
| --- | --- |
| Skill 显式名单 | 保留为 `skills` |
| Harness Space/Skill tag 匹配 | 保留，与名单取并集，名单优先 |
| Shared Skill | 泛化成 `skillProviders` |
| Harness Space-local Skill | `private/skills`，隐式最高优先 |
| 同名 Harness Space Skill 覆盖 shared | 泛化成 Provider 优先级和 shadow |
| Flat `SKILL.md` package | 变成唯一标准结构 |
| Nested `skill/SKILL.md` | 仅迁移工具可识别，正式协议删除 |
| Skill-level Agent files（旧称 tagents） | 移至 `<skill>/.harness-agents/<agent>` |
| Space-level Agent files（旧称 tagents） | 移至 `<space-root>/.harness-agents/<agent>` |
| Target adapters | 保留，首版扩为四 Agent |
| Cursor rule 校验 | 保留 |
| Artifact/source lock | 保留并扩展 ownership |
| Command argv/no-shell | 保留为可选 `command` |
| stdout/stderr/exit code | 保留 |
| workspace source 发布 | 删除 |
| workspace 校验 | 改为直接读取最终 `.code-workspace` |
| workspace 项目路径 rule | 保留并成为 core build phase |
| Harness Space 注册中心 | 删除 |
| THarness repo root 推导 | 删除 |
| 固定 shared-skills 路径 | 删除 |
| 中心化生成 workspace | 删除 |
| built-in/command 双模式 | 合并成一个协议，command 是可选 build phase |
| `.harness-space.yaml` | 删除 |
| `.harness-lock.yaml` | 替换为 `.harnessbuilder-lock.json` |

---

## 14. 迁移计划

### Phase 1：协议与 Cursor parity

- 新增独立 `harnessbuilder.py`；
- 实现 Harness Space name/workspace contract；
- 实现 `harness-space.json`；
- 实现 folder Skill Provider；
- 实现 explicit + tags 选择；
- 实现标准 Skill package 和 `.harness-agents`；
- 搬迁当前 Cursor rules/commands/files；
- 实现原地 ownership lock；
- 将当前 built-in fixtures 迁为 Python 黑盒 E2E cases。

### Phase 2：四 Agent 首版

- Codex skills、workspace context hooks、config 最小支持；
- Cursor 完整首版 adapter；
- CodeBuddy skills、commands、agents、settings hooks；
- Claude Code skills、rules、agents、commands compatibility、settings hooks、MCP；
- 四个平台 full-capability Skill、完整 Harness Space E2E 和重复构建测试；
- Human-owned 内容保护 E2E。

### Phase 3：Rounditer workspace 迁移为 Harness Space

- 将 `rounditer-webgame` 目录本身作为 workspace；
- 删除 `.code-workspace.src`；
- 将最终 `.code-workspace` 纳入 Human ownership；
- 把原 workspace-local Skills 和 scripts 移到 `private/`；
- 把原 tagents 移到 Harness Space root `.harness-agents/<agent>/`；
- 将 `THARNESS_*` 环境变量改成 `HARNESSBUILDER_*`；
- runtime 直接发布到 Harness Space 根目录的稳定子目录；
- 删除对 THarness root 和中心化生成 workspace 的依赖。

### Phase 4：独立发布

- HarnessBuilder 独立 Git repository 或单文件 release；
- SHA256/checksum 和版本说明；
- 可选 self-update，但默认不自动联网；
- 评估 Git Skill Provider；
- 评估 adapter plugin API。

---

## 15. 验收标准

首版完成必须满足：

1. 将 `harnessbuilder.py` 复制到任意位置后，可以构建任意符合协议的 Harness Space。
2. 不依赖 THarness repository layout。
3. 不依赖 pip install 或 npm install。
4. `<harness-space.json.name>.code-workspace` 在构建前后 byte-for-byte 不变。
5. 同一输入连续 build 两次，除非 command 本身有变化，否则生成内容和 lock 的稳定部分相同。
6. 四个平台都能发现同一个标准 Skill。
7. Skill 的 `.harness-agents/` 不会泄漏进 common package。
8. 显式 `skills` 和 tags 同时工作，显式选择优先记录。
9. 多 Provider 同名 Skill 解析稳定且可解释。
10. 未被 lock 管理的人工 Agent 配置不会被覆盖或删除。
11. `clean` 只删除 HarnessBuilder-owned 内容。
12. command 使用 argv/no-shell，失败退出码正确透传。
13. workspace rule 在四个平台中表达相同的项目角色和路径。
14. lock 能追溯每个生成 artifact 的 Provider、Skill、源文件和 digest。
15. Harness Space root `.harness-agents/` 和 `private/` 在 build/clean 前后不被改写。
16. HarnessBuilder 不创建或修改任何 `AGENTS.md`。
17. Codex workspace hook 在 session、compact 恢复和 subagent 启动时注入同一份 workspace rule。
18. apply 中途异常可 rollback，进程中断后下一次 build 可通过 transaction journal 恢复。
19. HarnessBuilder 只识别 canonical namespace；检测到旧 THarness layout 时返回 `HB018`，不静默读取或合并。

---

## 16. 最终定位

```text
HarnessBuilder is a portable compiler that builds a Harness Space
in place into a deterministic workspace for multiple coding agents.
```

中文定义：

> HarnessBuilder 是一个以单个 Python 文件分发、无中心仓库依赖的跨 Agent Harness 工作空间编译器。Harness Space 目录同时是构建输入和 Agent 工作空间；Human 维护最终 workspace，HarnessBuilder 从多个 Skill Provider 解析标准 Skills，以 Skill/Space 两级 `.harness-agents` 承载 Agent 专属输入，通过四个平台 adapter 原地生成原生能力，并使用 lock 保护人工内容和记录完整来源。
