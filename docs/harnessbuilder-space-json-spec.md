# HarnessBuilder Harness Space 与 Skill Provider 协议

状态：proposal  
Schema：`harness-space.v1`  
日期：2026-07-13

本文定义 Harness Space identity、`harness-space.json`、workspace、Skill package、Skill Provider、Skill 选择和 lock 的规范行为。

---

## 1. Harness Space identity

给定 Harness Space root：

```text
/workspace/local-checkout-17/
```

其 `harness-space.json` 为：

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

canonical logical name 是：

```text
my-harness-space
```

`harness-space.json.name` 是 Harness Space identity 的唯一事实源，必须匹配：

```text
^[a-z][a-z0-9-]*$
```

必须存在：

```text
my-harness-space.code-workspace
```

目录 basename 不参与 identity 推导，也不与 `name` 比较。移动或重命名 Harness Space root 不改变逻辑身份；复制目录后若要创建新 Harness Space，必须显式修改 `name`，并同步重命名 workspace 文件及其第一项 folder name。

大小写敏感文件系统和不敏感文件系统使用相同逻辑名称比较；目标路径冲突比较在 Windows/macOS 默认大小写不敏感，在明确大小写敏感的文件系统上仍应额外诊断 portability collision。

---

## 2. `harness-space.json` 是否必需

`harness-space.json` 必需。缺失时构建立即失败，不从目录名、workspace 文件名或已有 lock 猜测配置。

以下字段必须显式存在：

- `schema`；
- `name`；
- `agents`；
- `skills`；
- `tags`；
- `skillProviders`。

显式空数组用于表达“当前没有该类配置”。这让 manifest 始终是 identity、schema 版本和构建选择的稳定入口。低摩擦创建由未来的 `harnessbuilder init` 提供，不通过省略 manifest 实现。

---

## 3. 完整示例

```json
{
  "schema": "harness-space.v1",
  "name": "ue-gameplay",
  "description": "UE gameplay development harness space",
  "agents": [
    "codex",
    "cursor",
    "codebuddy",
    "claude-code"
  ],
  "skills": [
    "git",
    "ue-cli",
    "integration-test-pie"
  ],
  "tags": [
    "ue",
    "gameplay"
  ],
  "skillProviders": [
    {
      "type": "folder",
      "path": "../../shared-skills"
    },
    {
      "type": "folder",
      "path": "../game-team-skills"
    }
  ],
  "command": [
    "python3",
    "private/scripts/build_runtime.py"
  ]
}
```

未知顶层字段首版默认报错，防止拼写错误静默失效。未来 schema 版本可以新增字段。

---

## 4. 顶层字段

| 字段 | 类型 | 必需 | 默认值 | 语义 |
| --- | --- | --- | --- | --- |
| `schema` | string | 是 | 无 | 必须为 `harness-space.v1` |
| `name` | string | 是 | 无 | Harness Space canonical logical name；不从目录名推导 |
| `description` | string | 否 | 无 | Human-facing 描述 |
| `agents` | string[] | 是 | 无 | 需要生成的平台，保持声明顺序 |
| `skills` | string[] | 是 | 无 | 显式 Skill 名单；没有时写 `[]` |
| `tags` | string[] | 是 | 无 | Harness Space tags；没有时写 `[]` |
| `skillProviders` | object[] | 是 | 无 | 外部 Skill 来源；没有时写 `[]`，按数组顺序降序优先 |
| `command` | string[] | 否 | 无 | 可选 build argv；不经过 shell |

数组必须去重。重复值报错，而不是静默去重，以暴露配置问题。

---

## 5. `agents`

首版合法值：

```json
[
  "codex",
  "cursor",
  "codebuddy",
  "claude-code"
]
```

约束：

- 至少一项；
- 不允许重复；
- 未知值报错；
- HarnessBuilder 只读取被选中 Agent 的 Skill `.harness-agents` 和 Harness Space root `.harness-agents`；
- 删除一个 Agent 后，rebuild 可以清理 lock 中该 adapter 的旧受管产物，但不删除人工文件。

Agent 声明顺序用于 diagnostics 和 lock 展示，不应影响跨 Agent 语义。

---

## 6. Skill Provider

### 6.1 Provider IR

逻辑接口：

```text
Provider.resolve() -> immutable provider snapshot
Provider.listSkills() -> skill descriptors
Provider.openSkill(name) -> skill package
```

Core 不关心来源是 folder、Git 或 registry。Provider 必须返回统一的：

- provider id；
- source description；
- immutable revision/digest；
- Skill name；
- Skill root；
- Skill digest。

### 6.2 Implicit private Provider

HarnessBuilder 永远在最高优先级检查：

```text
<space-root>/private/skills
```

如果目录不存在，视为空 Provider，不报错。

其逻辑 id 固定为：

```text
space-private
```

该 Provider 中所有合法 Skill 都会被选中，保持旧 Harness Space-local Skill 的语义。

### 6.3 Folder Provider

```json
{
  "type": "folder",
  "path": "../../shared-skills"
}
```

约束：

- `type` 必须为 `folder`；
- `path` 必须是非空字符串；
- manifest 中必须使用相对路径；
- 路径以 Harness Space root 为基准；
- build 时必须解析为已存在目录；
- provider root 不得位于 HarnessBuilder generated target 内；
- provider realpath 和目录内容 digest 写入 lock；
- provider root 的直接子目录才是 Skill candidate。

绝对路径不允许进入 manifest，以保证 Harness Space 可移动。确有本机路径需求时，应通过外部目录布局、symlink 或未来的 local override 机制解决。

### 6.4 Provider 优先级

从高到低：

```text
space-private
skillProviders[0]
skillProviders[1]
...
```

对一个逻辑 Skill name，选取第一个合法 candidate。其余同名候选不参与 merge：

```json
{
  "name": "git",
  "provider": "space-private",
  "shadowedCandidates": [
    {
      "provider": "folder:../../shared-skills",
      "path": "../../shared-skills/git"
    }
  ]
}
```

同名 shadow 默认 warning；`explain` 必须展示。

---

## 7. Skill package

### 7.1 标准结构

```text
<provider-root>/<skill-name>/
├── SKILL.md                   # required
├── scripts/                   # optional
├── references/                # optional
├── assets/                    # optional
├── agents/                    # Agent Skills 标准允许的其他内容
└── .harness-agents/                # HarnessBuilder extension, optional
    ├── codex/
    ├── cursor/
    ├── codebuddy/
    └── claude-code/
```

除 `.harness-agents/` 外，Skill 根目录全部属于 common package。复制时保留目录结构并排除：

```text
.harness-agents/
.DS_Store
```

禁止把任意隐藏目录都排除，因为标准 Skill 内容可能合法使用其他隐藏目录。

### 7.2 `SKILL.md`

必须包含 YAML frontmatter。HarnessBuilder v1 至少识别：

```yaml
---
name: ue-cli
description: Operate Unreal Engine command-line workflows.
tags:
  - ue
  - build
---
```

约束：

- `name` 必须存在；
- `description` 必须存在且非空；
- `name` 必须与 Skill 目录名一致；
- name 使用 `^[a-z][a-z0-9-]*$`；
- `tags` 可选，必须是唯一字符串列表；
- 未识别 frontmatter 字段原样保留；
- HarnessBuilder 不为不同平台重写 common frontmatter。

### 7.3 `.harness-agents`

结构：

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

不是每个 adapter 都支持所有逻辑目录。遇到 adapter 未支持的非空目录，默认失败并给出 agent、Skill 和路径，不允许忽略。

协议 fixture 不使用一个巨型 Skill 覆盖全部行为。Portable package、四平台 full-capability Skill、Provider resolution、invalid/security 和 live Codex fixture 的分组见 [HarnessBuilder Skill Fixture Catalog](harnessbuilder-skill-fixture-catalog.md)。

`files/` 是显式 escape hatch：其内容按 Harness Space root 相对路径投影。它仍受 ownership、source/target alias 和冲突检查约束。

`rules/`、`commands/`、`hooks/`、`agents/`、`config/`、`mcp/` 和 `files/` 只允许出现在两种位置：Skill 根目录的 `.harness-agents/<agent>/`，或 Harness Space 根目录的 `.harness-agents/<agent>/`。协议不定义顶层 `rules/`、`resources/` 或 `private/tagents/`。

---

## 8. Space-level `.harness-agents`

Harness Space 级 Agent 专属输入位于 Harness Space 根目录：

```text
.harness-agents/<agent>/...
```

内部结构与 Skill `.harness-agents/<agent>` 一致：

```text
.harness-agents/cursor/rules/
.harness-agents/codebuddy/agents/
.harness-agents/claude-code/hooks/
.harness-agents/codex/hooks/
```

Harness Space `.harness-agents` 与 Skill `.harness-agents` 是两个明确 scope；scope 本身不授予覆盖权。可 additive merge 的 artifact 按 adapter 语义合并，其余同 semantic key 冲突默认 fail。

它用于无法合理归属于某个 Skill 的 Harness Space 级能力，例如额外 hooks、workspace-specific commands 和全局 validation gate。正式协议不再定义 `tagents` 或 `resources` 目录。

---

## 9. Skill 选择算法

### 9.1 输入

```text
private Skill names
explicit harness-space.json.skills
harness-space.json.tags
resolved Provider index
```

### 9.2 算法

1. 按 Provider 优先级为每个 Skill name 解析唯一有效 candidate。
2. 将 `space-private` 中全部 Skill 加入结果，`selectedBy = private`。
3. 按 `skills` 声明顺序选择 resolved candidate：
   - 不存在：error；
   - 已由 private 选中：升级为 `selectedBy = skills`，同时记录 private；
   - 否则加入结果，`selectedBy = skills`。
4. 对尚未显式选择的 resolved candidates，计算 Skill tags 与 Harness Space tags 的交集：
   - 交集非空：加入结果，`selectedBy = tags`；
   - 交集为空：不选择。
5. 对同时由 explicit 和 tags 命中的 Skill：保留 `selectedBy = skills`，并记录 `matchedTags`。
6. 最终安装顺序：
   - explicit skills 按 manifest 顺序；
   - private-only skills 按 Skill name；
   - tags-only skills 按 Skill name。

安装顺序只影响稳定输出和 diagnostics，不授予静默覆盖权限。

### 9.3 示例

```json
{
  "skills": ["git"],
  "tags": ["ue"]
}
```

Provider 中：

```text
git tags=[workflow]
ue-cli tags=[ue,build]
trace-analyze tags=[performance]
```

结果：

```text
git       selectedBy=skills matchedTags=[]
ue-cli    selectedBy=tags   matchedTags=[ue]
```

`trace-analyze` 不选择。

---

## 10. Workspace

### 10.1 Human-owned source

Workspace 不设置独立路径字段；其路径固定由必需的 `harness-space.json.name` 推导：

```text
<space-root>/<harness-space.json.name>.code-workspace
```

因此 Harness Space identity 只有 manifest 一个事实源，同时避免搜索或猜测多个 `.code-workspace` 文件。workspace 自身仍是项目名称、路径和顺序的事实源。

Workspace 第一项 folder 必须满足：

```json
{
  "name": "<harness-space.json.name>",
  "path": "."
}
```

### 10.2 Folder role

| Index | Role | 默认权限 |
| --- | --- | --- |
| 0 | Harness Space workspace | Builder 输入和 Agent cwd；生成目录可由 Builder 管理 |
| 1 | Primary project | 默认允许修改、验证和提交 |
| 2+ | Reference project | 默认只读 |

Human 通过 workspace 顺序改变角色。HarnessBuilder 不支持另一份 role mapping。

### 10.3 Generated workspace rule model

中间表示：

```json
{
  "space": "my-harness-space",
  "cwd": ".",
  "workspace": "my-harness-space.code-workspace",
  "primaryProject": {
    "name": "game-project",
    "path": "../../game-project"
  },
  "referenceProjects": [
    {
      "name": "engine-reference",
      "path": "../../engine-reference"
    }
  ]
}
```

该 IR 由各 Agent adapter render，程序不得从 render 后的 Markdown/MDC 反向解析。

---

## 11. Command

```json
{
  "command": [
    "python3",
    "private/scripts/build_runtime.py"
  ]
}
```

约束：

- 必须是非空 argv 字符串数组；
- 不经过 shell；
- cwd 为 Harness Space root；
- stdin/stdout/stderr 继承；
- signal 和 exit code 透传；
- 在 Agent-specific 文件应用前执行；
- `check`、`explain` 和 `--dry-run` 不执行；
- command 不允许通过 CLI 注入额外参数；
- command 负责自己的 runtime ownership，不能修改 HarnessBuilder lock。

注入环境：

```text
HARNESSBUILDER_SPACE_ROOT=<absolute path>
HARNESSBUILDER_SPACE_NAME=<harness-space.json.name>
HARNESSBUILDER_MANIFEST=<harness-space.json absolute path>
HARNESSBUILDER_WORKSPACE=<code-workspace absolute path>
HARNESSBUILDER_AGENTS=<comma-separated ids>
```

环境变量是调用上下文，不是 secret 传输机制。

---

## 12. Diagnostics

每条诊断至少包含：

```text
level
code
message
source paths
target path or semantic key
suggested action
```

建议的稳定错误码：

```text
HB001 invalid-manifest
HB002 invalid-space-name
HB003 workspace-not-found
HB004 invalid-workspace
HB005 provider-not-found
HB006 unsupported-provider
HB007 skill-not-found
HB008 invalid-skill
HB009 unsupported-agent-artifact
HB010 target-conflict
HB011 human-content-conflict
HB012 generated-content-modified
HB013 unsafe-path
HB014 command-failed
HB015 adapter-not-implemented
HB016 incomplete-transaction
HB017 transaction-recovery-conflict
HB018 legacy-layout-detected
```

`HB018` 用于发现旧 THarness layout，例如 `tagents/`、`.harness-space.yaml`、`.harness-lock.yaml` 或 workspace source template。HarnessBuilder v1 不双读、不自动 merge，也不在 build 中就地改名；迁移由显式 migration command/script 完成。

CLI 使用 `--format json` 时，diagnostics 包装在版本化 `harnessbuilder-report.v1` 中；测试与自动化必须依赖 `code` 和结构化字段，不解析人类文案。Report 的 E2E fixture 和 golden 规则见 [HarnessBuilder Python E2E 集成测试架构](harnessbuilder-test-architecture.md)。

---

## 13. Lock requirements

Lock 至少记录：

- HarnessBuilder version 和自身 digest；
- manifest path 和 digest；
- workspace path 和 digest；
- Agent ids 和 adapter versions；
- Provider 配置、realpath、snapshot/digest；
- 每个 Skill 的 provider、source、digest、selectedBy、matchedTags、shadowed candidates；
- 每个 artifact 的 source、logical type、target、semantic key、operation、digest；
- 每个 semantic document 中由 HarnessBuilder 管理的字段；
- command argv 和最终状态；
- 可选 generated timestamp。

Lock 中的 source path 优先写 Harness Space-relative 或 Provider-relative 路径。不可移植 absolute realpath 可以用于本机诊断，但必须与 portable identity 分开，不参与可复现 digest。

---

## 14. 路径安全

所有写入目标必须：

- 相对于 Harness Space root；
- normalize 后仍位于 Harness Space root；
- 不通过 symlink/junction 逃逸 Harness Space root；
- 不指向 Provider source；
- 不指向 Harness Space build inputs：`private/` 或 Harness Space root `.harness-agents/`；
- 不指向 workspace 文件、`harness-space.json` 或 `.harnessbuilder-lock.json`，除非是对应 core operation；
- 在 Windows 做 drive/UNC 检查；
- 在应用前检查 real parent path。

读取 Provider 和 workspace 引用项目可以位于 Harness Space root 外；写入永远限制在 Harness Space root。
