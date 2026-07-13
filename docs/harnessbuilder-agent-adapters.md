# HarnessBuilder 四 Agent Adapter 首版规范

状态：proposal  
日期：2026-07-13  
目标平台：Codex、Cursor、CodeBuddy、Claude Code

本文定义首版 adapter 的输入结构、目标映射、workspace rule 投影、merge 边界和后续 plugin 演进。平台行为会随产品版本变化，实现时必须用真实客户端 fixture 校验；无法确认的 schema 默认失败，不猜测。

---

## 1. 通用输入

每个已选择 Skill 提供：

```text
<skill>/                         common package
<skill>/.harness-agents/<agent>/      agent-specific artifacts
```

Harness Space 提供：

```text
.harness-agents/<agent>/              Space-level Agent-specific inputs
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

Core 统一执行冲突、安全、ownership 和 staging。

---

## 2. 通用 `.harness-agents` 目录

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

逻辑名称不意味着四个平台语义相同。每个平台 adapter 独立定义：

- 支持哪些目录；
- 文件 schema；
- semantic key；
- target path；
- merge policy；
- trust/security diagnostics。

任何未知目录或未实现的已知目录都必须报错。

---

## 3. 跨平台总览

| 逻辑能力 | Codex | Cursor | CodeBuddy | Claude Code |
| --- | --- | --- | --- | --- |
| Common Skill | `.agents/skills/<name>` | `.cursor/skills/<name>` | `.codebuddy/skills/<name>` | `.claude/skills/<name>` |
| Workspace rule | `SessionStart` + `SubagentStart` hooks 注入 `.harnessbuilder/workspace-rule.md` | `.cursor/rules/harnessbuilder-workspace.mdc` | `.codebuddy/rules/harnessbuilder-workspace.md`，需 fixture | `.claude/rules/harnessbuilder-workspace.md` |
| Rules | `.codex/rules/**/*.rules`（command policy；不是 workspace guidance） | `.cursor/rules/**/*.mdc` | `.codebuddy/rules/**`，按版本 fixture | `.claude/rules/**/*.md` |
| Commands | 优先转换为 Skill；legacy 默认不生成 | `.cursor/commands/**/*.md` | `.codebuddy/commands/**/*.md` | `.claude/commands/**/*.md` compatibility |
| Agents | `.codex/config.toml` agent roles | Cursor agents/plugin，需版本 fixture | `.codebuddy/agents/**/*.md` | `.claude/agents/**/*.md` |
| Hooks | `.codex/hooks.json` | Cursor hooks，需版本 fixture | `.codebuddy/settings.json` | `.claude/settings.json` |
| MCP | `.codex/config.toml` | Cursor MCP target，需版本 fixture | `.codebuddy/mcp.json` | `.mcp.json` |
| Files escape hatch | Harness Space-relative | Harness Space-relative | Harness Space-relative | Harness Space-relative |

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

### 4.2 Workspace rule

HarnessBuilder 不创建、追加、修改或清理任何 `AGENTS.md`。Codex adapter 读取 core 已生成的：

```text
.harnessbuilder/workspace-rule.md
```

并生成：

```text
.codex/hooks/harnessbuilder_workspace_context.py
.codex/hooks.json
```

生成脚本只读取 `.harnessbuilder/workspace-rule.md` 并将正文输出到 stdout。Hook 配置包含：

- `SessionStart`，matcher 为 `startup|resume|clear|compact`；
- `SubagentStart`，无 matcher 或匹配全部 subagent；
- macOS/Linux command 使用 `python3`；
- Windows 通过 `commandWindows` 使用 `py -3`；
- timeout 取小值，例如 5 秒；
- hook source、command 和 digest 进入 lock 与 `explain`。

生成配置的核心形态：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .codex/hooks/harnessbuilder_workspace_context.py",
            "commandWindows": "py -3 .codex\\hooks\\harnessbuilder_workspace_context.py",
            "timeout": 5
          }
        ]
      }
    ],
    "SubagentStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 .codex/hooks/harnessbuilder_workspace_context.py",
            "commandWindows": "py -3 .codex\\hooks\\harnessbuilder_workspace_context.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

该相对命令依赖 Harness Space contract 中“Agent cwd 是 Harness Space root”的约束。Hook 脚本忽略 stdin，仅将 `.harnessbuilder/workspace-rule.md` 以 UTF-8 输出到 stdout；找不到文件时必须非零退出并给出短错误，不静默返回空 context。

Codex 会把这两个事件的 stdout 作为额外 developer context。这里不使用 `UserPromptSubmit`，避免每轮重复注入同一份 workspace rule。

项目本身已有的 `AGENTS.md` 仍由 Codex 原生加载，但完全属于 Human，不进入 HarnessBuilder ownership。项目级 hooks 需要 Codex 信任该 `.codex/` 配置和 hook 定义；未信任或 hooks 被策略禁用时，`check` 必须给出明确 warning。

### 4.3 Config/agents/MCP

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
- lock 记录 HarnessBuilder-owned table/key。

由于 TOML 人工内容和注释保护复杂，首版可以先支持严格子集。遇到无法 round-trip 的已有人工 TOML 时应失败并给出迁移建议。

### 4.4 Rules

```text
rules/**/*.rules
  -> .codex/rules/**/*.rules
```

Codex 原生 `.rules` 是 sandbox 外命令权限策略，不是 Markdown project guidance。Adapter 必须：

- 只接受 `.rules` 扩展名；
- 保持相对路径；
- 检查 target collision 和 ownership；
- 对宽泛 `allow`、外部脚本路径和可疑 shell wrapper 给出 security diagnostics；
- 使用当前 Codex fixture，并在可用时以 `codex execpolicy check` 验证规则加载；
- 在 lock 中标记该能力为 experimental platform surface。

Workspace 项目结构不写入 `.codex/rules/`，仍只由 4.2 的 context hook 注入。

### 4.5 Hooks

输入来源为：

```text
generated workspace context hook
<space-root>/.harness-agents/codex/hooks/
<skill>/.harness-agents/codex/hooks/
```

这些 hooks 是 additive 的；上面的列举顺序只用于稳定 diagnostics，不表示执行顺序或覆盖优先级。

目标：

```text
.codex/hooks.json
```

Hook 按事件 additive merge，并以规范化 matcher/type/command 作为 identity 去重。Hook command、网络 URL 和外部路径进入安全报告。

不得依赖多个 hooks 的执行顺序。

### 4.6 Commands

Codex 可复用流程优先建模成标准 Skill。`.harness-agents/codex/commands` 在首版视为 unsupported，防止继续生成已弱化或 deprecated 的 custom prompt 面。

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
description: HarnessBuilder workspace project roles and path boundaries.
alwaysApply: true
---
```

正文由 WorkspaceRule IR render。

### 5.3 Rules

```text
rules/**/*.mdc
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
commands/**/*.md
  -> .cursor/commands/**/*.md
```

冲突不仅按 target path，还要按最终 slash command name 检测。

### 5.5 Hooks、agents、config、MCP

Cursor 支持这些扩展面，但版本演进较快。首版策略：

- 只有加入真实客户端 fixture 的 semantic document 才启用；
- 未验证的目录报 unsupported；
- 不把 JSON/TOML/Markdown 当作普通文件覆盖；
- adapter version 在 lock 中记录。

### 5.6 Files

保留当前 escape hatch，但必须经过 core path/ownership 检查。

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
commands/**/*.md
  -> .codebuddy/commands/**/*.md
```

按最终 slash command 名检测冲突；子目录 namespace 必须纳入 semantic key。

### 6.4 Agents

```text
agents/**/*.md
  -> .codebuddy/agents/**/*.md
```

校验 frontmatter、agent name、mode 和 tool fields。相同 agent name 不同定义失败。

### 6.5 Hooks/settings

目标：

```text
.codebuddy/settings.json
```

Hooks 按 event additive merge；相同 event 的 handlers 可能并发执行，不能表达顺序依赖。Skill frontmatter-owned hook 保留在 Skill 内，Harness Space/session hooks 才进入 settings。

Hook 是自动执行代码，lock 和 `explain` 必须展示 command、matcher、来源和风险。

### 6.6 MCP

目标：

```text
.codebuddy/mcp.json
```

按 server name merge；manifest 只允许环境变量引用或外部 credential helper，不允许 secret literal。

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

HarnessBuilder 不生成或覆盖根 `CLAUDE.md`。如果 Human 已维护 `CLAUDE.md`，它与 generated rule 按 Claude Code 自身加载机制共同生效。

### 7.3 Rules

```text
rules/**/*.md
  -> .claude/rules/**/*.md
```

支持无 frontmatter的 always-loaded rule，以及带 `paths` 列表的 path-scoped rule。Builder 校验 frontmatter shape 和 glob 字符串，但不重写正文。

### 7.4 Commands

兼容映射：

```text
commands/**/*.md
  -> .claude/commands/**/*.md
```

Claude Code 仍兼容该目录，但新能力应写成 Skill。`explain` 对 commands 输出 migration warning。

### 7.5 Agents

```text
agents/**/*.md
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

Hooks 是 settings 中的 semantic section。HarnessBuilder：

- 保留非 HarnessBuilder-owned settings；
- 按事件 additive merge；
- 规范化去重；
- 冲突时失败；
- lock 记录 owned handlers；
- 不写 `.claude/settings.local.json`；
- 不写 managed/user settings；
- 不设置 `bypassPermissions` 等高风险默认值。

### 7.7 MCP

项目共享 MCP 目标：

```text
.mcp.json
```

按 server name semantic merge。local/user scope 不属于 Harness Space Builder。

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
Agent cwd: current Harness Space root
Workspace: <harness-space.json.name>.code-workspace
Primary project: <folder[1].name> (<folder[1].path>)
Reference projects: <folder[2+]>
```

并包含一致规则：

1. 路径和项目名称只能从 `.code-workspace` 获取。
2. Harness Space root 是 Agent cwd，不代表主项目源码根。
3. 默认只修改、验证和提交 primary project。
4. Reference projects 默认只读。
5. `private/` 是 Harness Space 构建源，不是业务源码目录。
6. Harness Space root `.harness-agents/` 是 Agent-specific 构建输入，不是生成目录。
7. Agent 不手写 `.harnessbuilder-lock.json`。
8. 平台 render 文件只是投影，不是程序事实源。

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
| File | normalized Harness Space-relative path | 不允许隐式覆盖 |

Harness Space root `.harness-agents` artifact 不因作用域更高而自动覆盖 Skill `.harness-agents` artifact。需要 override 时必须在未来协议中显式声明 semantic key 和被覆盖来源；首版默认 fail。

---

## 10. Adapter E2E requirements

完整测试目录、Harness Space sandbox、golden 和真实客户端协议见 [HarnessBuilder Python E2E 集成测试架构](harnessbuilder-test-architecture.md)；标准 Skill packs 和 capability matrix 见 [HarnessBuilder Skill Fixture Catalog](harnessbuilder-skill-fixture-catalog.md)。本节只定义每个 adapter 的最低 E2E 覆盖要求。

每个内置 adapter 至少有以下完整 Harness Space E2E case：

- portable common Skills 和一个该平台 full-capability Skill；
- 一个 workspace rule fixture；
- 每种已支持 `.harness-agents` 目录的成功 fixture；
- 每种 gated/unsupported `.harness-agents` 目录的失败 fixture；
- unknown directory 失败 fixture；
- 同 semantic key 冲突 fixture；
- 人工目标文件保护 fixture；
- 重复 build fixture；
- clean fixture；
- Windows path normalization fixture；
- 平台配置 merge fixture；
- hook/MCP secret lint fixture。

Codex 还必须包含 `SessionStart`、`SubagentStart`、`compact` 恢复、Windows `commandWindows`、hook 未信任提示和 `AGENTS.md` byte-for-byte 不变 fixture。

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
