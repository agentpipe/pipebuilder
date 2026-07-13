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

目录 basename 不参与 identity 推导，也不与 `name` 比较。移动或重命名 Harness Space root 不改变逻辑身份；复制目录后若要创建新 Harness Space，必须显式修改 `name` 并同步重命名 workspace 文件。workspace folder name 不要求与 Harness Space name 相同。

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
- HarnessBuilder 只读取被选中 Agent 的 Skill `.harness-agents/<agent>` 和 Harness Space `.harness-builder/agents/<agent>`；
- 删除一个 Agent 后，rebuild 清理 lock 中该 adapter 的旧生成产物，不删除 Human-owned source。

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

### 6.2 Implicit space-local Provider

HarnessBuilder 永远在最高优先级检查：

```text
<space-root>/.harness-builder/skills
```

如果目录不存在，视为空 Provider，不报错。

其逻辑 id 固定为：

```text
space-local
```

该 Provider 中所有合法 Skill 都会被选中，保持旧 Harness Space-local Skill 的语义。

### 6.3 Folder Provider

```json
{
  "type": "folder",
  "path": "../../shared-skills",
  "subdir": "."
}
```

约束：

- `type` 必须为 `folder`；
- `path` 必须是非空字符串；
- `subdir` 可选，默认 `.`，是相对 Provider 源根的 Skill 根目录；
- manifest 中必须使用相对路径；
- 路径以 Harness Space root 为基准；
- build 时必须解析为已存在目录；
- provider root 不得位于 HarnessBuilder generated target 内；
- provider realpath 和目录内容 digest 写入 lock；
- provider root 的直接子目录才是 Skill candidate。

Folder 与 Git Provider 都可附加 post command：

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

`cwd` 相对 Provider 源根，默认 `.`；`args` 是不经 shell 的非空字符串数组。
正式 `build` 在 HarnessBuilder 自身产物落地后按 Provider 顺序调用；`check`、`explain` 和
`build --dry-run` 只展示，不执行。

绝对路径不允许进入 manifest，以保证 Harness Space 可移动。确有本机路径需求时，应通过外部目录布局、symlink 或未来的 local override 机制解决。

### 6.4 Git Provider

分支形式：

```json
{
  "type": "git",
  "url": "https://example.com/team/skills.git",
  "branch": "main",
  "subdir": "skills"
}
```

tag 形式：

```json
{
  "type": "git",
  "url": "git@example.com:team/skills.git",
  "tag": "v2.1.0"
}
```

约束：

- `url` 为非空 Git URL；开发和离线 fixture 也可使用相对于 Harness Space root 的本地 repository 路径；
- `branch` 与 `tag` 必须严格二选一，通用 `ref` 不属于 schema；
- `subdir` 可省略，默认 `.`，必须是安全的相对 POSIX 路径；
- URL 不得内嵌 HTTP(S) username、password、query credential 或 fragment；认证由 Git credential helper、SSH agent 或环境承担；
- 默认 cache 位于用户 cache 目录；`HARNESSBUILDER_CACHE_DIR` 可以覆盖，但 cache 必须位于 Harness Space 外；
- 在线 resolve 会更新 cache mirror，将 branch/tag 解析为 commit，并从该 commit 生成无 symlink 的 immutable snapshot；
- `--offline` 不访问 origin，且要求存在匹配 lock：复用其中 commit，并校验 cache snapshot digest；lock、cache、commit 或 subdir 不可用时返回 `HB005`，digest 漂移返回 `HB010`；
- lock 记录 portable URL、`branch`/`tag`、commit、subdir、Provider digest 和每个 Skill digest，不记录 credential 或本机 cache absolute path；
- Harness Space 内不得出现 Git Provider checkout。

### 6.5 Provider 优先级

从高到低：

```text
space-local
skillProviders[0]
skillProviders[1]
...
```

对一个逻辑 Skill name，选取第一个合法 candidate。其余同名候选不参与 merge：

```json
{
  "name": "git",
  "provider": "space-local",
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

`.harness-agents/<agent>/` 是对应 Agent 的虚拟项目根，内部保留平台原生的 target-relative path，不再定义一套跨平台通用子目录。例如：

```text
.harness-agents/
├── codex/
│   ├── AGENTS.md
│   └── .codex/
│       ├── config.toml
│       ├── hooks.json
│       └── rules/
├── cursor/
│   └── .cursor/
│       ├── rules/
│       └── commands/
├── codebuddy/
│   └── .codebuddy/
│       ├── settings.json
│       ├── mcp.json
│       └── agents/
└── claude-code/
    ├── CLAUDE.md
    ├── .mcp.json
    └── .claude/
        ├── settings.json
        ├── rules/
        └── agents/
```

示例只展示常见 surface；每个 adapter 的精确文件名、schema 和 target mapping 由 Adapter 规范定义。遇到该 adapter 未支持的原生文件或目录，默认失败并给出 agent、Skill 和路径，不允许忽略。

协议 fixture 不使用一个巨型 Skill 覆盖全部行为。Portable package、四平台 full-capability Skill、Provider resolution、invalid/security 和 live Codex fixture 的分组见 [HarnessBuilder Skill Fixture Catalog](harnessbuilder-skill-fixture-catalog.md)。

Skill-level Agent source 只允许出现在 Skill 根目录的 `.harness-agents/<agent>/`。协议不提供通用 `files/` escape hatch，也不定义顶层 `rules/`、`resources/` 或 `tagents/`。

---

## 8. Space-level `.harness-builder/agents`

Harness Space 级 Agent 专属输入位于：

```text
.harness-builder/agents/<agent>/...
```

它与 Skill `.harness-agents/<agent>` 一样是对应 Agent 的虚拟项目根：

```text
.harness-builder/agents/codex/AGENTS.md
.harness-builder/agents/codex/.codex/config.toml
.harness-builder/agents/cursor/.cursor/rules/
.harness-builder/agents/codebuddy/.codebuddy/agents/
.harness-builder/agents/claude-code/CLAUDE.md
.harness-builder/agents/claude-code/.claude/settings.json
```

Harness Space `.harness-builder/agents` 与 Skill `.harness-agents` 是两个明确 scope；scope 本身不授予覆盖权。可 additive merge 的 artifact 按 adapter 语义合并，其余同 semantic key 冲突默认 fail。

它用于无法合理归属于某个 Skill 的 Harness Space 级能力，例如项目 instructions、额外 hooks、workspace-specific commands 和全局 validation gate。这里的文件是 Human-owned source；对应根 `AGENTS.md`、`CLAUDE.md`、`.mcp.json` 以及 `.codex/`、`.cursor/`、`.codebuddy/`、`.claude/` 中列入 plan 的 target 都是 Builder-owned output。

---

## 9. Skill 选择算法

### 9.1 输入

```text
space-local Skill names
explicit harness-space.json.skills
harness-space.json.tags
resolved Provider index
```

### 9.2 算法

1. 按 Provider 优先级为每个 Skill name 解析唯一有效 candidate。
2. 将 `space-local` 中全部 Skill 加入结果，`selectedBy = space-local`。
3. 按 `skills` 声明顺序选择 resolved candidate：
   - 不存在：error；
   - 已由 space-local 选中：升级为 `selectedBy = skills`，同时记录 space-local；
   - 否则加入结果，`selectedBy = skills`。
4. 对尚未显式选择的 resolved candidates，计算 Skill tags 与 Harness Space tags 的交集：
   - 交集非空：加入结果，`selectedBy = tags`；
   - 交集为空：不选择。
5. 对同时由 explicit 和 tags 命中的 Skill：保留 `selectedBy = skills`，并记录 `matchedTags`。
6. 最终安装顺序：
   - explicit skills 按 manifest 顺序；
   - space-local-only skills 按 Skill name；
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

Workspace 支持三种常见 topology：

```json
{
  "folders": [
    {"name": "same-directory-project", "path": "."},
    {"name": "decoupled-project", "path": "../project"},
    {"name": "another-project", "path": "../another-project"}
  ]
}
```

`path: "."` 表示项目与 Harness Space root 同目录；其他相对路径表示目录解耦。两种形式可以同时出现。`folders` 必须是至少包含一项的数组；folder name 非空且唯一，path 非空、为相对路径、解析后唯一，并在 build 时指向已存在目录。

### 10.2 Folder 语义

HarnessBuilder 保留 `folders` 的声明顺序，但不从顺序推导 primary/reference、可写/只读、验证或提交边界。所有 folder 都是同等的 workspace project。特定 Skill 可以读取 workspace rule 并定义自己的项目选择约定，但该约定不属于 HarnessBuilder core。

### 10.3 Generated workspace rule model

中间表示：

```json
{
  "space": "my-harness-space",
  "workspace": "my-harness-space.code-workspace",
  "folders": [
    {
      "name": "game-project",
      "path": "."
    },
    {
      "name": "engine-project",
      "path": "../engine-project"
    }
  ]
}
```

该 IR 由各 Agent adapter render，程序不得从 render 后的 Markdown/MDC 反向解析。

---

## 11. Diagnostics

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
HB011 unsafe-path
HB013 build-busy
HB014 stale-build-lock
HB015 legacy-layout-detected
```

`HB012` 作为早期草案编号保留但不属于 `harness-space.v1` stable contract：manifest 只接受四个内置 Agent，未知 Agent 在 adapter dispatch 前由 `HB001` 拒绝，因此不能为 HB012 制造伪失败入口。

`HB015` 用于发现旧 THarness layout，例如 `tagents/`、Space root `.harness-agents/`、`private/`、`.harness-space.yaml`、`.harness-lock.yaml` 或 workspace source template。HarnessBuilder v1 不双读、不自动 merge，也不在 build 中就地改名；迁移由独立工具或 Human 显式完成。

CLI 使用 `--format json` 时，diagnostics 包装在版本化 `harnessbuilder-report.v1` 中；测试与自动化必须依赖 `code` 和结构化字段，不解析人类文案。Report 的 E2E fixture 和 golden 规则见 [HarnessBuilder Python E2E 集成测试架构](harnessbuilder-test-architecture.md)。

---

## 12. 简化 Lock 与并发要求

Lock 固定为：

```text
.harness-builder/lock.json
```

Lock 至少记录：

- HarnessBuilder version 和自身 digest；
- manifest path 和 digest；
- workspace path 和 digest；
- Agent ids 和 adapter versions；
- Provider 配置、realpath、snapshot/digest；
- 每个 Skill 的 provider、source、digest、selectedBy、matchedTags、shadowed candidates；
- 每个 artifact 的 source、logical type、target、semantic key、operation、digest；
- Adapter capability status，以及自动执行 hook、Codex rule 等 surface 的结构化 risks；
- 可选 generated timestamp。

Lock 中的 source path 优先写 Harness Space-relative 或 Provider-relative 路径。不可移植 absolute realpath 可以用于本机诊断，但必须与 portable identity 分开，不参与可复现 digest。

平台 target 配置整体由 Builder 管理，lock 不承担 target 内 Human 字段的 ownership merge。build 和 clean 开始时以 exclusive create 获取 `.harness-builder/build.lock`；文件已存在时返回 `HB013`，不等待并发操作。首版不提供 transaction journal 和跨文件 rollback。每个目标文件使用临时文件加 atomic replace，最终 `lock.json` 最后写入。

进程异常退出可能留下 stale `build.lock`。HarnessBuilder 报 `HB014` 并展示其中的 pid、host 和 startedAt；确认原进程已结束后由 Human 删除该文件。构建在多文件应用中断时，重新执行 build 即可按 source 重新生成全部计划目标。

---

## 13. 路径安全

所有写入目标必须：

- 相对于 Harness Space root；
- normalize 后仍位于 Harness Space root；
- 不通过 symlink/junction 逃逸 Harness Space root；
- 不指向 Provider source；
- 不指向 Human-owned Harness Space build inputs：`.harness-builder/agents/` 或 `.harness-builder/skills/`；
- 不指向 workspace 文件或 `harness-space.json`；
- 只有 core operation 可以写 `.harness-builder/generated/`、`lock.json` 和 `build.lock`；
- 在 Windows 做 drive/UNC 检查；
- 在应用前检查 real parent path。

读取 Provider 和 workspace 引用项目可以位于 Harness Space root 外；写入永远限制在 Harness Space root。
