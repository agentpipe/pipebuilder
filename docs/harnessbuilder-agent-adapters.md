# HarnessBuilder 四 Agent Adapter 首版规范

状态：proposal  
日期：2026-07-13  
目标平台：Codex、Cursor、CodeBuddy、Claude Code

本文定义首版 adapter 的输入结构、目标映射、workspace rule 投影、merge 边界和后续 plugin 演进。平台行为会随产品版本变化，实现时必须用真实客户端 fixture 校验；无法确认的 schema 默认失败，不猜测。

当前 compatibility status：Codex 已有真实客户端 E1，标记为 `client-verified`；Cursor、CodeBuddy、Claude Code 已有 E0 生成与 schema 边界，但在各自 E1 建立前统一标记为 `generated-only`。该状态写入 `explain` 和 `.harness-builder/lock.json`，不等同于删除 adapter。

---

## 1. 通用输入

每个已选择 Skill 提供：

```text
<skill>/                         common package
<skill>/.harness-agents/<agent>/      agent-specific artifacts
```

Harness Space 提供：

```text
.harness-builder/agents/<agent>/      Space-level Agent-specific inputs
```

Adapter 接收 core 解析后的 IR，不自行遍历 Provider：

```text
HarnessSpaceContext
WorkspaceRule
SelectedSkills[]
AgentArtifacts[]
PreviousOwnership
```

Adapter 输出 build operations，不直接写磁盘：

```text
copy
render
merge-document
```

Core 统一执行冲突、安全、ownership 和逐文件原子写入。

---

## 2. Agent 原生形态 source

Space-level `.harness-builder/agents/<agent>/` 和 Skill-level `.harness-agents/<agent>/` 都视为对应 Agent 的虚拟项目根，保留完整的原生 target-relative path。例如 Codex 使用 `AGENTS.md`、`.codex/config.toml`、`.codex/hooks.json`、`.codex/hooks/` 和 `.codex/rules/`，Claude Code 使用 `CLAUDE.md`、`.claude/settings.json`、`.claude/rules/`、`.claude/agents/`、`.claude/hooks/` 和 `.mcp.json`。不再设置通用的 `config/`、`mcp/`、`files/` 等中间目录。

每个平台 adapter 独立定义：

- 支持哪些目录；
- 文件 schema；
- semantic key；
- target path；
- merge policy；
- trust/security diagnostics。

任何未知原生文件、未知目录或未实现的已知 surface 都必须报错。多个 Space/Skill source 需要汇入同一个目标配置文件时，adapter 先按平台 semantic key merge，再由 core 完整生成 Builder-owned target。

---

## 3. 跨平台总览

| 逻辑能力 | Codex | Cursor | CodeBuddy | Claude Code |
| --- | --- | --- | --- | --- |
| Common Skill | `.agents/skills/<name>` | `.cursor/skills/<name>` | `.codebuddy/skills/<name>` | `.claude/skills/<name>` |
| Workspace rule | 根 `AGENTS.md` 中的 generated section | `.cursor/rules/harnessbuilder-workspace.mdc` | `.codebuddy/rules/harnessbuilder-workspace.md`，需 fixture | `.claude/rules/harnessbuilder-workspace.md` |
| Rules | `.codex/rules/**/*.rules`（command policy；不是 workspace guidance） | `.cursor/rules/**/*.mdc` | `.codebuddy/rules/**`，按版本 fixture | `.claude/rules/**/*.md` |
| Commands | 优先转换为 Skill；legacy 默认不生成 | `.cursor/commands/**/*.md` | `.codebuddy/commands/**/*.md` | `.claude/commands/**/*.md` compatibility |
| Agents | `.codex/config.toml` agent roles | Cursor agents/plugin，需版本 fixture | `.codebuddy/agents/**/*.md` | `.claude/agents/**/*.md` |
| Hooks | `.codex/hooks.json` | Cursor hooks，需版本 fixture | `.codebuddy/settings.json` | `.claude/settings.json` |
| MCP | `.codex/config.toml` | Cursor MCP target，需版本 fixture | `.codebuddy/mcp.json` | `.mcp.json` |

“需 fixture”表示平台支持该能力，但 HarnessBuilder 首版实现前必须针对团队实际客户端版本确认 target path/schema。不能用简单复制代替验证。

---

## 4. Codex adapter

Agent id：

```text
codex
```

### 4.1 Skill

```text
<skill common package>
  -> .agents/skills/<skill-name>/
```

复制排除 `.harness-agents/`。`SKILL.md` 的未知 frontmatter 保留。

不同时复制到 `.codex/skills`，避免双发现；如果真实部署仍需要 legacy 路径，应作为显式 adapter compatibility option，而非默认行为。

### 4.2 Workspace rule 与 `AGENTS.md`

Codex adapter 读取 core 生成的 `.harness-builder/generated/workspace-rule.md`，并与以下 Builder source 中的原生项目 instructions 合成：

```text
<space-root>/.harness-builder/agents/codex/AGENTS.md
<skill>/.harness-agents/codex/AGENTS.md
```

目标是 Harness Space 根 `AGENTS.md`，整体由 Builder 管理。合成顺序固定为 canonical workspace section、Space source、按最终 Skill 安装顺序排列的 Skill source；每段带稳定的 generated heading 和 source identity。相同正文 digest 可去重，不同来源不互相覆盖。

HarnessBuilder 不生成 workspace context hook，也不要求 Codex 运行时读取 `.code-workspace` 或 `.harness-builder/generated/`。Codex 按项目根到当前目录的原生规则发现生成后的 `AGENTS.md`。因此从 Harness Space root 启动时可直接获得 folder inventory；从某个解耦的外部 folder 单独启动不是同一个 Harness Space session，Builder 不尝试把 target 写到 Space root 之外。

### 4.3 Config/agents/MCP

输入：

```text
<space-root>/.harness-builder/agents/codex/.codex/config.toml
<skill>/.harness-agents/codex/.codex/config.toml
```

目标：

```text
.codex/config.toml
```

必须按 Codex config 语义 merge：

- `[agents.<name>]` 以 agent name 为 key；
- MCP 以 server name 为 key；
- 同 key 相同定义可去重；
- 同 key 不同定义失败；
- project-unsafe 或 credential 字段禁止生成；
- lock 记录 target、source 和最终 digest。

多个 source 按 Codex config semantic key merge。目标 `.codex/config.toml` 整体由 Builder 管理，不读取或保留 target 中的人工字段和注释；Human 配置必须写回 `.harness-builder/agents/codex/.codex/config.toml`。首版可以只支持经 E1 验证的 TOML 严格子集。

### 4.4 Rules

```text
<agent-source-root>/.codex/rules/**/*.rules
  -> .codex/rules/**/*.rules
```

Codex 原生 `.rules` 是 sandbox 外命令权限策略，不是 Markdown project guidance。Adapter 必须：

- 只接受 `.rules` 扩展名；
- 保持相对路径；
- 检查 target collision 和 ownership；
- 对宽泛 `allow`、外部脚本路径和可疑 shell wrapper 给出 security diagnostics；
- 使用当前 Codex fixture，并在可用时以 `codex execpolicy check` 验证规则加载；
- 在 lock 中标记该能力为 experimental platform surface。

Workspace 项目结构不写入 `.codex/rules/`，只由 4.2 生成的根 `AGENTS.md` 提供。

### 4.5 Hooks

输入来源为：

```text
<space-root>/.harness-builder/agents/codex/.codex/hooks.json
<skill>/.harness-agents/codex/.codex/hooks.json
```

这些 hooks 是 additive 的；上面的列举顺序只用于稳定 diagnostics，不表示执行顺序或覆盖优先级。

目标：

```text
.codex/hooks.json
```

Hook 使用 Codex 当前原生三层结构：event -> matcher group -> `hooks` handlers。按事件 additive merge；完全相同的 matcher group 去重，不把不同 group 的 handler 猜测性重排或折叠。Hook command、网络 URL 和外部路径进入安全报告。最终 schema 由 E1 的真实 Codex client parse case 验证。

不得依赖多个 hooks 的执行顺序。

### 4.6 Commands

Codex 可复用流程优先建模成标准 Skill。任一 Codex source 中出现 `commands/` 时，首版视为 unsupported，防止继续生成已弱化或 deprecated 的 custom prompt 面。

---

## 5. Cursor adapter

Agent id：

```text
cursor
```

### 5.1 Skill

```text
<skill common package>
  -> .cursor/skills/<skill-name>/
```

### 5.2 Workspace rule

目标：

```text
.cursor/rules/harnessbuilder-workspace.mdc
```

使用固定 frontmatter：

```yaml
---
description: HarnessBuilder workspace folder inventory.
alwaysApply: true
---
```

正文由 WorkspaceRule IR render。

### 5.3 Rules

```text
<agent-source-root>/.cursor/rules/**/*.mdc
  -> .cursor/rules/**/*.mdc
```

必须校验：

- 扩展名 `.mdc`；
- frontmatter 存在；
- 至少声明 `description`、`alwaysApply` 或 `globs` 中的一项；
- target path 唯一；
- 同路径不同内容失败。

保留当前 THarness Cursor adapter 的已验证行为。

### 5.4 Commands

```text
<agent-source-root>/.cursor/commands/**/*.md
  -> .cursor/commands/**/*.md
```

冲突不仅按 target path，还要按最终 slash command name 检测。

### 5.5 Hooks、agents、config、MCP

Cursor 支持这些扩展面，但版本演进较快。首版策略：

- 只有加入真实客户端 fixture 的 semantic document 才启用；
- 未验证的目录报 unsupported；
- 使用 Cursor 原生文件名和 schema，不引入通用 config/mcp wrapper；
- 对需要汇总的 Builder source 做 semantic merge，目标文件整体由 Builder 管理；
- adapter version 在 lock 中记录。

---

## 6. CodeBuddy adapter

Agent id：

```text
codebuddy
```

### 6.1 Skill

```text
<skill common package>
  -> .codebuddy/skills/<skill-name>/
```

CodeBuddy-specific Skill frontmatter 原样保留，HarnessBuilder 不尝试为其他 Agent 删除未知字段。

### 6.2 Workspace rule

优先目标：

```text
.codebuddy/rules/harnessbuilder-workspace.md
```

由于 CodeBuddy IDE/CLI 的规则发现面需要按团队实际版本验证，首版 fixture 若证明该路径不一致，应由 adapter 改变 target，WorkspaceRule IR 不变。

### 6.3 Commands

```text
<agent-source-root>/.codebuddy/commands/**/*.md
  -> .codebuddy/commands/**/*.md
```

按最终 slash command 名检测冲突；子目录 namespace 必须纳入 semantic key。

### 6.4 Agents

```text
<agent-source-root>/.codebuddy/agents/**/*.md
  -> .codebuddy/agents/**/*.md
```

校验 frontmatter、agent name、mode 和 tool fields。相同 agent name 不同定义失败。

### 6.5 Hooks/settings

目标：

```text
.codebuddy/settings.json
```

输入使用两个 scope 中的原生 `settings.json`：

```text
<space-root>/.harness-builder/agents/codebuddy/.codebuddy/settings.json
<skill>/.harness-agents/codebuddy/.codebuddy/settings.json
```

Hooks 按 event additive merge；相同 event 的 handlers 可能并发执行，不能表达顺序依赖。目标 settings 整体由 Builder 管理，不保留 target 中的人工字段。

Hook 是自动执行代码，lock 和 `explain` 必须展示 command、matcher、来源和风险。

### 6.6 MCP

目标：

```text
.codebuddy/mcp.json
```

输入为两个虚拟项目根中的 `.codebuddy/mcp.json`。按 server name merge；只允许环境变量引用或外部 credential helper，不允许 secret literal。

---

## 7. Claude Code adapter

Agent id：

```text
claude-code
```

### 7.1 Skill

Claude Code 当前使用标准 Agent Skills：

```text
<skill common package>
  -> .claude/skills/<skill-name>/
```

Skill 可以被模型按 description 自动选择，也可以通过 `/skill-name` 调用。Claude Code 的旧 custom commands 已并入 Skills 机制，因此新流程优先使用 Skill。

### 7.2 Workspace rule

目标：

```text
.claude/rules/harnessbuilder-workspace.md
```

不设置 `paths` frontmatter，使该 rule 对整个 Harness Space workspace 生效。

根 `CLAUDE.md` 也是 Builder-owned target。两个 source scope 中存在 `CLAUDE.md` 时按稳定来源顺序合成到根文件；需要保留的人工内容必须放在 `.harness-builder/agents/claude-code/CLAUDE.md`。canonical workspace rule 仍投影到 `.claude/rules/harnessbuilder-workspace.md`，避免在两个 target 中重复同一段 folder inventory。

### 7.3 Rules

```text
<agent-source-root>/.claude/rules/**/*.md
  -> .claude/rules/**/*.md
```

支持无 frontmatter的 always-loaded rule，以及带 `paths` 列表的 path-scoped rule。Builder 校验 frontmatter shape 和 glob 字符串，但不重写正文。

### 7.4 Commands

兼容映射：

```text
<agent-source-root>/.claude/commands/**/*.md
  -> .claude/commands/**/*.md
```

Claude Code 仍兼容该目录，但新能力应写成 Skill。`explain` 对 commands 输出 migration warning。

### 7.5 Agents

```text
<agent-source-root>/.claude/agents/**/*.md
  -> .claude/agents/**/*.md
```

至少校验：

- `name`；
- `description`；
- agent name 唯一；
- `tools`/`disallowedTools` shape；
- `skills` 引用存在；
- `mcpServers` 不含 secret literal；
- hooks shape；
- `isolation: worktree` 等枚举字段。

### 7.6 Hooks/settings

Harness Space project settings：

```text
.claude/settings.json
```

输入为两个虚拟项目根中的 `.claude/settings.json`。Hooks 是 settings 中的 semantic section。HarnessBuilder：

- 按事件 additive merge；
- 规范化去重；
- 冲突时失败；
- 完整生成 Builder-owned `.claude/settings.json`；
- 不写 `.claude/settings.local.json`；
- 不写 managed/user settings；
- 不设置 `bypassPermissions` 等高风险默认值。

### 7.7 MCP

项目共享 MCP 目标：

```text
.mcp.json
```

两个 scope 都使用原生项目路径 `.mcp.json` 作为 source，并生成项目共享 `.mcp.json`。按 server name semantic merge；目标整体由 Builder 管理，local/user scope 不属于 Harness Space Builder。

### 7.8 Plugin 关系

Claude Code plugin 可以分发 skills、agents、hooks 和 MCP servers，但 HarnessBuilder 首版不把 Harness Space 编译成 Claude plugin：

- Harness Space 是 workspace-local build；
- plugin 是可安装、namespaced、可版本发布的分发单元；
- Skill Provider 未来可以引用 plugin source，但不能混淆两种 ownership。

---

## 8. Workspace rule 的跨平台一致性

四个平台生成的文本必须表达同一组事实：

```text
Harness Space: <harness-space.json.name>
Workspace: <harness-space.json.name>.code-workspace
Folders, in declared order: <folders[] name/path>
```

并包含一致规则：

1. 路径和项目名称只能从 `.code-workspace` 获取。
2. `path: "."` 表示项目与 Harness Space root 同目录；其他相对路径表示目录解耦。
3. folder 顺序只用于稳定展示，不表达 primary/reference 或权限。
4. `.harness-builder/agents/` 和 `.harness-builder/skills/` 是 HarnessBuilder source，不是生成目录。
5. Skill `.harness-agents/` 是 Skill source extension，不复制进 common package。
6. Agent 不手写 `.harness-builder/lock.json` 或平台生成 target。
7. 平台 render 文件只是投影，不是程序事实源。

Adapter 可以调整 frontmatter 和平台术语，不得改变这些事实。

---

## 9. Artifact 冲突策略

| Artifact | Semantic key | 默认策略 |
| --- | --- | --- |
| Skill | Agent + Skill name | Provider resolution 后唯一 copy |
| Rule | Agent + logical rule id/target | 相同 digest 去重，否则 fail |
| Command | Agent + slash command name | 相同 digest 去重，否则 fail |
| Agent | Agent platform + subagent name | 相同定义去重，否则 fail |
| Hook | Agent + event + normalized handler | additive + dedupe |
| MCP | Agent + server name | 相同定义去重，否则 fail |
| Config | Agent + semantic key path | 显式 merge policy，否则 fail |

Harness Space `.harness-builder/agents` artifact 不因作用域更高而自动覆盖 Skill `.harness-agents` artifact。需要 override 时必须在未来协议中显式声明 semantic key 和被覆盖来源；首版默认 fail。

---

## 10. Adapter E2E requirements

完整测试目录、Harness Space sandbox、golden 和真实客户端协议见 [HarnessBuilder Python E2E 集成测试架构](harnessbuilder-test-architecture.md)；标准 Skill packs 和 capability matrix 见 [HarnessBuilder Skill Fixture Catalog](harnessbuilder-skill-fixture-catalog.md)。本节只定义每个 adapter 的最低 E2E 覆盖要求。

每个内置 adapter 至少有以下完整 Harness Space E2E case：

- portable common Skills 和一个该平台 full-capability Skill；
- 一个 workspace rule fixture；
- 每种已支持原生 source surface 的成功 fixture；
- 每种 gated/unsupported 原生 source surface 的失败 fixture；
- unknown directory 失败 fixture；
- 同 semantic key 冲突 fixture；
- Human-owned source 不变和 Builder-owned target 重生成 fixture；
- 重复 build fixture；
- clean fixture；
- Windows path normalization fixture；
- 平台配置 merge fixture；
- hook/MCP secret lint fixture。

Codex 还必须包含 generated `AGENTS.md` 的 source 合成、workspace inventory、target drift 恢复、项目 trust 对 `.codex/` surface 的影响，以及从 Harness Space root 启动的发现 fixture。

Full-capability Skill 必须覆盖该 adapter 当期所有 supported surface；不能把尚未冻结 source grammar 或未经真实客户端验证的目录放入其中。新增能力时必须同时增加 positive、conflict、invalid 和 E1 discovery case。

这些 case 必须通过 subprocess 执行最终 `harnessbuilder.py`，不得直接调用 adapter class 或 renderer。平台功能只有同时具备实现、离线 E2E、真实客户端 E2E 和 compatibility note，才能标记 supported。

---

## 11. 官方能力依据

Codex：

- https://developers.openai.com/codex/concepts/customization
- https://developers.openai.com/codex/guides/agents-md
- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/codex/config-advanced
- https://developers.openai.com/codex/rules
- https://developers.openai.com/codex/hooks

Cursor：

- https://cursor.com/docs/rules
- https://cursor.com/docs/skills
- https://cursor.com/docs/hooks
- https://cursor.com/docs/reference/plugins

CodeBuddy：

- https://www.codebuddy.ai/docs/cli/skills
- https://www.codebuddy.ai/docs/cli/sub-agents
- https://www.codebuddy.ai/docs/cli/hooks
- https://www.codebuddy.ai/docs/cli/plugins-reference

Claude Code：

- https://code.claude.com/docs/en/slash-commands
- https://code.claude.com/docs/en/memory
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/plugins-reference
