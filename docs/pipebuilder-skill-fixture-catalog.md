# PipeBuilder：Skill Fixture Catalog 与 Agent 能力覆盖

状态：target catalog；当前 baseline 见 `tests/e2e/COVERAGE.md`
日期：2026-07-13  
适用范围：PipeBuilder Python E2E 中的标准 Skill、四 Agent capability、Provider resolution、失败场景和 Codex live model fixture

相关文档：

- [PipeBuilder Python E2E 集成测试架构](pipebuilder-test-architecture.md)
- [PipeSpace 与 Skill Provider 协议](pipebuilder-space-json-spec.md)
- [四 Agent Adapter 首版规范](pipebuilder-agent-adapters.md)

---

## 1. 结论

需要多套 fixture，不能只用一个最小 `SKILL.md`，也不应把所有行为塞进一个巨型 Skill。

目标目录按五类能力组织：

```text
5 类 Skill fixture capability
+ Space-level `.pipebuilder/agents` overlay
```

五类 fixture capability 分别负责：

1. portable common Skill；
2. 四 Agent full-capability projection；
3. Provider、显式名单和 tag resolution；
4. invalid/conflict/security；
5. Codex live consumption（client default 或 release job 显式模型）。

额外的 PipeSpace overlay 用来验证 `.pipebuilder/agents/<agent>`，因为它不是 Skill，不能伪装成 Skill fixture。

每个 Skill 本身保持很小，通常一个 `SKILL.md` 加一两个最小资源；“全面”由 fixture 组合和 capability matrix 实现，而不是靠复杂业务逻辑。

---

## 2. Fixture 设计原则

### 2.1 像真实 Skill，不像测试脚本说明书

所有合法 fixture 都遵循标准结构：

```text
<skill-name>/
├── SKILL.md
├── scripts/          # optional
├── references/       # optional
├── assets/           # optional
├── agents/           # optional Skill metadata
└── .pipe-agents/        # optional PipeBuilder extension
```

`SKILL.md`：

- name 与目录名一致；
- description 写清触发条件；
- body 使用短小、可执行的指令；
- 不写 fixture 搭建过程、expected output 或测试解释；
- 核心正文尽量少于 50 行；
- 细节放入 `references/`，确定性动作放入 Python `scripts/`。

Skill 目录内不添加 README、安装指南或 changelog。Fixture 的测试 metadata 放在测试侧 Python catalog，不污染交给 Agent 的 package。

所有可执行 fixture 都使用 Python：Skill scripts、hooks、local MCP server 和 receipt writer 均不得使用 MJS、TypeScript 或 shell script。Markdown、JSON、TOML、YAML 和 `.rules` 只作为产品输入或 expected data。

### 2.2 正交而非重复

一个 fixture 应有一个主要目的：

- common package preservation；
- 某 Agent 的完整 capability projection；
- Provider resolution；
- 一个明确失败原因；
- 一个 live consumption 能力。

同一个事实不在四套几乎相同的 Skill 中重复维护。平台差异只进入对应 `.pipe-agents/<agent>`。

### 2.3 Supported、gated、unsupported 三态

每项 Agent 能力必须处于以下一种状态：

| 状态 | Fixture 行为 |
| --- | --- |
| `supported` | 进入 full-capability Skill，必须有 E0 golden 和 E1 client verification |
| `gated` | 保留 candidate 输入；真实客户端验证通过并冻结 schema 后才能进入 full-capability Skill |
| `unsupported` | 放入负向 fixture，必须稳定失败并返回 diagnostic |

“目录看起来存在”不等于 supported。尤其是 Cursor 的 hooks/agents/config/MCP、CodeBuddy rules 等版本相关能力，不得通过普通文件复制冒充支持。

### 2.4 Fixture 不复用 production oracle

Fixture 可以由测试侧 Python 复制和填充 nonce，但不得调用 PipeBuilder 的 resolver、adapter 或 renderer。Expected target、lock 和 report 仍是独立 golden。

---

## 3. 测试目录

在 `tests/e2e/` 下增加：

```text
fixtures/
├── catalog.py
├── skill-packs/
│   ├── portable/
│   │   ├── fixture-minimal/
│   │   └── fixture-bundled/
│   ├── agent-capabilities/
│   │   ├── fixture-codex-capabilities/
│   │   ├── fixture-cursor-capabilities/
│   │   ├── fixture-codebuddy-capabilities/
│   │   └── fixture-claude-code-capabilities/
│   ├── resolution/
│   │   ├── space-local-provider/
│   │   ├── provider-high/
│   │   └── provider-low/
│   ├── invalid/
│   │   ├── bad-frontmatter/
│   │   ├── unsupported-surface/
│   │   ├── semantic-conflict/
│   │   └── security/
│   └── live-codex/
│       └── fixture-live-codex/
└── space-overlays/
    ├── all-agents/
    ├── merge-with-skill/
    └── conflict-with-skill/
```

`catalog.py` 只保存测试 metadata 和复制位置，例如 fixture id、pack、合法性、目标 Agent 和 capability tags；它不解析 `SKILL.md`，也不计算期望投影。

Case 创建 sandbox 时：

1. 复制 case 自己的 `input/`；
2. 将选中的 fixture pack byte-for-byte 复制到指定 Provider；
3. 必要时用测试侧 Python 填充 `$FIXTURE_NONCE`；
4. 对完成组装的输入做 snapshot；
5. subprocess 执行最终 `pipebuilder.py`。

不使用跨目录 symlink 复用 fixture，避免 Windows 和 symlink policy 改变测试语义。

---

## 4. Pack A：Portable common Skills

这套 fixture 不包含 `.pipe-agents`，负责证明标准 Skill package 能被四个平台一致复制，并且 `.pipe-agents` 排除逻辑不会误伤 common resources。

### 4.1 `fixture-minimal`

```text
fixture-minimal/
└── SKILL.md
```

覆盖：

- 最小合法 frontmatter；
- name/目录一致；
- description discovery metadata；
- Markdown body byte preservation；
- 四个平台的 Skill target；
- explicit selection 和未选择时 absence。

### 4.2 `fixture-bundled`

```text
fixture-bundled/
├── SKILL.md
├── scripts/
│   └── write_receipt.py
├── references/
│   └── protocol.md
├── assets/
│   └── payload.txt
└── agents/
    └── openai.yaml
```

覆盖：

- nested directory preservation；
- Python executable bit；
- progressive disclosure reference；
- asset 非 context 资源；
- Skill UI metadata；
- common package digest；
- 四个目标目录内容 byte-for-byte 一致。

`write_receipt.py` 只使用 Python 标准库，输入 argv，输出版本化 JSON receipt，可在 E2 中被 Agent 调用。

---

## 5. Pack B：四 Agent full-capability Skills

每个平台一个 Skill。它包含该平台当前所有 `supported` `.pipe-agents` surface，并刻意不包含其他平台目录。

```text
fixture-codex-capabilities/
├── SKILL.md
└── .pipe-agents/codex/...

fixture-cursor-capabilities/
├── SKILL.md
└── .pipe-agents/cursor/...

fixture-codebuddy-capabilities/
├── SKILL.md
└── .pipe-agents/codebuddy/...

fixture-claude-code-capabilities/
├── SKILL.md
└── .pipe-agents/claude-code/...
```

这种拆分有三个作用：

- 单 Agent case 可以准确定位 adapter 问题；
- all-agents catalog smoke 可以证明四套能力可同时构建；
- 某个平台 schema 变化时不会改动另外三套 fixture。

### 5.1 Capability matrix

图例：`P` 为 positive supported fixture，`G` 为 client-version gated candidate，`R` 为 rejection fixture，`—` 为不单独建模。

| Surface | Codex | Cursor | CodeBuddy | Claude Code |
| --- | --- | --- | --- | --- |
| Common Skill | P | P | P | P |
| Workspace rule | PipeSpace fixture | PipeSpace fixture | PipeSpace fixture | PipeSpace fixture |
| Rules | P：`.rules` command policy | P：`.mdc` | G：锁定客户端后启用 | P：`.md`/path scope |
| Commands | R：首版 unsupported | P | P | P + migration warning |
| Agents | P：config agent roles | G | P | P |
| Hooks | P | G | P：settings merge | P：settings merge |
| Generic config | P：TOML strict subset | G | —：由 settings surface 表达 | —：由 settings surface 表达 |
| MCP | P：config TOML | G | P：`mcp.json` | P：`.mcp.json` |
| Builder-owned target regeneration | P | P | P | P |
| Human-owned source preservation | `.pipebuilder/agents/codex` | `.pipebuilder/agents/cursor` | `.pipebuilder/agents/codebuddy` | `.pipebuilder/agents/claude-code` |

Capability status 以 Adapter 规范和锁定的客户端版本为准。`G` 变成 `P` 必须同时提交：

1. 精确 source grammar；
2. target path/schema；
3. semantic key；
4. merge/conflict policy；
5. E0 golden；
6. E1 client parse/discovery case；
7. compatibility note。

### 5.2 Codex capability Skill

至少包含：

- 一个最小 `.rules` allow/deny policy；
- 一个 additive lifecycle hook；
- 一个命名 agent role；
- 一个安全的 config fragment；
- 一个本地 Python stdio MCP server definition；

额外断言：

- `.pipe-agents/codex/.codex/commands` 不在正向 Skill 中；
- 单独负向 fixture 放入该目录时稳定返回 unsupported；
- canonical workspace section、Space source 与 Skill `AGENTS.md` source 可稳定合成；
- generated 根 `AGENTS.md` 被修改后 rebuild 恢复；
- `codex execpolicy check`、config discovery 和 hook probe 进入 E1。

### 5.3 Cursor capability Skill

baseline 至少包含：

- `.mdc` rule；
- Markdown command；

hooks、agents、config 和 MCP 在团队锁定的 Cursor 客户端上确认 schema 前保持 `G`，放在 candidate case，不进入 baseline full-capability Skill。确认后逐项加入，而不是一次性宣称全部支持。

### 5.4 CodeBuddy capability Skill

baseline 至少包含：

- command；
- sub-agent；
- settings hook fragment；
- MCP server；

rules 在锁定版本真实发现成功后从 `G` 升级。每个 hook、agent 和 MCP 使用唯一 semantic name，避免 full smoke 自身制造冲突。

### 5.5 Claude Code capability Skill

至少包含：

- always-loaded rule；
- path-scoped rule；
- compatibility command；
- sub-agent，引用已安装 fixture Skill；
- settings hook；
- local Python MCP server；

额外断言：

- command 生成 migration warning；
- `tools`、`disallowedTools`、`skills`、`mcpServers` 和 hook shape 被验证；
- `.pipebuilder/agents/claude-code` source 不变，根 `CLAUDE.md` 和 target settings 可完整重生成。

---

## 6. Pack C：Provider 与选择

这套不是单个 Skill，而是三棵 Provider root。相同 Skill name 的内容使用明显不同 marker：

```text
resolution/
├── space-local-provider/
│   ├── fixture-space-local/SKILL.md
│   └── fixture-shadow/SKILL.md       # marker: space-local
├── provider-high/
│   ├── fixture-explicit/SKILL.md
│   ├── fixture-tagged/SKILL.md
│   ├── fixture-shadow/SKILL.md       # marker: high
│   └── fixture-unselected/SKILL.md
└── provider-low/
    ├── fixture-shadow/SKILL.md       # marker: low
    └── fixture-low-only/SKILL.md
```

用一个完整 PipeSpace 覆盖：

- space-local Skill 隐式全选；
- explicit `skills` 优先选择；
- `tags` 匹配加入并集；
- high provider shadow low provider；
- space-local shadow 所有 external provider；
- unselected Skill 不出现在任何 Agent target；
- lock 和 `explain` 给出 `selectedBy`、provider 和 `shadowedCandidates`；
- 调整 provider 顺序后结果和 provenance 按协议变化。

该 pack 不加入 rules/hooks 等 Agent surface，避免 resolution failure 与 adapter failure 混在一起。

`fixture-tagged` 专门覆盖一个/多个 tags、tag union、重复或类型错误的负向变体，以及未识别 frontmatter 字段的原样保留。Portable fixtures 的 frontmatter 只使用标准 `name` 和 `description`；带 tags 的 Skill 明确属于 PipeBuilder resolution extension，不冒充最小跨平台标准。

---

## 7. Pack D：Invalid、conflict 与 security

负向 fixture 必须“一 case 一主错误”。不要创建一个同时缺 `SKILL.md`、frontmatter 错误、路径越界和 secret 泄漏的目录，否则只能验证 fail-fast 顺序。

至少覆盖：

### Skill package

- 缺失 `SKILL.md`；
- malformed frontmatter；
- name 缺失、非法或与目录不一致；
- description 空；
- tags 非列表、重复或元素非字符串；
- 不允许的编码或不可读文件；
- 非法 symlink/循环。

### Agent surface

- unknown `.pipe-agents/<agent>` directory；
- 当前 adapter 的 gated/unsupported surface；
- rule/command/agent 文件扩展名错误；
- frontmatter/schema 错误；
- 同 semantic key 不同定义；
- Skill-level 与 Space-level 冲突；
- config 无法安全 round-trip。

### Security

- 原生 source tree 中的 absolute/path traversal/symlink escape；
- hook 外部路径或高风险 wrapper；
- MCP secret literal；
- 宽泛 allow policy；
- generated target 被人工修改后再次 build 会恢复 source 定义；
- 与 plan/旧 lock 无关的 sibling 文件保持不变；
- 旧 `tagents/`、Space root `.pipe-agents/` 与新 `.pipebuilder/agents/` 单独或同时存在。

需要 symlink、junction、case-folding 或权限的输入由 `case.py` 在 sandbox 中创建，不把平台特有 inode 行为伪装成普通 Git fixture。

---

## 8. Pack E：Codex live Skill

首版真实模型只使用一个可复用 Skill package：

```text
fixture-live-codex/
├── SKILL.md
├── scripts/
│   ├── write_receipt.py
│   └── mcp_probe.py
├── references/
│   └── protocol.md
├── assets/
│   └── payload.txt
└── .pipe-agents/
    └── codex/
        ├── AGENTS.md
        └── .codex/
            ├── config.toml
            ├── hooks.json
            └── rules/
```

模型不在 fixture 中固定；普通运行使用 client default，release job 可显式 `--model`。下表是可按兼容风险拆分的目标 case：

| Live case | 验证内容 | Machine oracle |
| --- | --- | --- |
| `explicit-skill` | Skill 可发现并显式加载 | 返回本次 nonce 和 skill id |
| `auto-discovery` | description 自动匹配 | receipt 标记 Skill body 已加载；非 release-hard gate |
| `progressive-resources` | reference、asset、Python script | reference nonce、asset digest、script JSON receipt |
| `workspace-context` | generated `AGENTS.md` 原生发现 | 返回 `.code-workspace` 中的 folder identity |
| `skill-hook` | Skill hook 被真实会话执行 | hook receipt 文件 |
| `subagent` | config agent role 可发现并启动 | subagent receipt/structured result |
| `mcp-tool` | 本地 MCP server 被加载并调用 | MCP tool receipt 和 nonce |

Rules 的语法和 allow/deny 优先由 E1 `codex execpolicy check` 做确定性验证；E2 可以补一个 harmless command policy case，但不让模型尝试破坏性命令。

### 8.1 Per-run nonce

每个 live case 生成随机 nonce，在 build 前填入该 case 唯一的 reference、asset、hook 或 MCP response。Prompt 不包含 expected nonce。

```text
HARNESSBUILDER_LIVE_<random>
```

只有真正加载对应 surface 才能得到 nonce。测试比较 nonce/receipt，不比较自然语言全文。

### 8.2 Receipt schema

所有 Python probe 输出：

```json
{
  "schema": "pipebuilder-fixture-receipt.v1",
  "fixture": "fixture-live-codex",
  "capability": "mcp-tool",
  "nonce": "$FIXTURE_NONCE",
  "argv": [],
  "status": "ok"
}
```

Receipt 只能写到 sandbox 的 capture 目录，不读取真实 home，不记录 token 或凭据。

### 8.3 Live case 隔离

- 每个 capability 独立 Codex session；
- `--ephemeral`；
- 独立 PipeSpace sandbox 和 capture；
- model、client version、prompt digest、nonce digest 和每次重试进入 report；
- session 失败不能复用前一次生成的 receipt；
- 自动触发测试与显式 Skill 测试分开统计。

---

## 9. Space-level overlay fixture

PipeSpace `.pipebuilder/agents/<agent>` 单独维护，并保持各平台原生配置树：

```text
space-overlays/
├── all-agents/
├── merge-with-skill/
└── conflict-with-skill/
```

覆盖：

- PipeSpace-only workspace-specific command/hook/rule；
- 与 Skill artifact additive merge；
- 相同 digest 去重；
- 同 semantic key 不同定义失败；
- scope 不提供隐式 override；
- provenance 区分 `space` 和 `skill:<name>`。

这套 fixture 不包含 `SKILL.md`，也不应被 Provider index 发现。

---

## 10. 五种完整 PipeSpace topology

Fixture pack 最终通过以下 E2E topology 消费：

### T1：Portable smoke

四 Agent + Pack A，检查 common package 在四个平台完全一致。

### T2：Adapter full smoke

每个平台单独执行一次 Pack A + 对应 capability Skill；另有一次 all-agents build 同时选择四个 capability Skills，检查 merge 和 ownership。

### T3：Resolution matrix

四 Agent + Pack C，检查 space-local/explicit/tag/shadow/unselected 的最终结果和 provenance。

### T4：Negative matrix

每个 case 只安装 Pack D 的一个错误输入，断言 stable diagnostic、零非预期写入和可恢复性。

### T5：Codex live

构建 Pack E 后使用 Codex live profile。当前 baseline 为一个组合哨兵请求，同时验证 AGENTS、显式 Skill 与 SessionStart hook；将来只有在定位波动或独立发布门禁需要时再拆成多个模型请求。

PipeSpace overlay fixture 分别加入 T2 的 merge/conflict case，不另造一套虚假的 Skill。

---

## 11. Fixture 变更门禁

任何新增 Agent capability 必须同时更新：

1. Adapter capability matrix；
2. 对应 full-capability Skill；
3. isolated E0 case；
4. all-capabilities smoke golden；
5. conflict/invalid case；
6. E1 client verification；
7. `COVERAGE.md` requirement mapping；
8. 若属于 Codex live 核心路径，再增加一个短 E2 case。

删除或重命名 fixture 必须证明没有 requirement 失去唯一覆盖。Golden 更新不能替代 capability review。

---

## 12. 当前 baseline 与扩展清单

当前已提交一套静态 all-agent golden fixture，并由动态 sandbox case 构造下面这些等价能力：

```text
portable common package
explicit/tag/local/shadow resolution
codex/cursor/codebuddy/claude-code full native surfaces
invalid/conflict/security variants
live Codex AGENTS + Skill + hook sentinel
```

当前 baseline 还包括：

- 动态 multiple Provider、space-local、显式名单、tag 和 shadow 输入；
- 每个 v1 stable diagnostic 的真实失败路径；PB012 仅保留历史编号，不属于 v1 stable contract；
- 同目录、目录解耦、多 folder 和特殊字符 workspace topology；
- 四 Agent E0 projection、Codex E1 client report；
- 一个 Codex release-relevant 组合 live case。

新增实体 fixture pack 前必须证明它比动态 case 更容易审查或能锁定新的二进制/客户端契约；不能只为达到目录数量复制已有输入。
