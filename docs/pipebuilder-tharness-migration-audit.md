# THarness Builder 迁移审计

状态：current baseline  
日期：2026-07-13

本文只记录旧 THarness Builder 到 PipeBuilder 的迁移边界。Rounditer 不属于 Builder；它可以作为符合 PipeBuilder 规范的 Skill 分发。

## 已迁移

- 显式 Skill、tag 选择、Space-local Skill 与 Provider shadow；
- flat `SKILL.md` common package、binary/hidden/executable 文件复制；
- Skill/Space 两级 Agent source；
- Cursor rules/commands 与基础 frontmatter 校验；
- workspace folder inventory；
- provenance lock、重复 build、clean、故障恢复和简单并发锁。

## 明确删除或改模

- command pipeline/no-shell runner；
- `runtime/`、`saved/`、`work/`、`artifacts/`、`logs/`；
- THarness repo root、中心注册表和固定 `shared-skills` 路径；
- `.code-workspace.src` 发布；
- generic `files/` escape hatch；
- nested `skill/SKILL.md` 正式协议。

这些内容不应重新进入 PipeBuilder core。旧 nested Skill、`tagents`、YAML manifest/lock 的转换由独立迁移工具或 Human 显式完成。

## 真实 Skill catalog 结果

对 `/data/workspace/THarness/harness/shared-skills` 的 45 个 `SKILL.md` 使用当前 parser/validator 审计：

- 43 个直接兼容；
- `BotAI-Log-Analyzer` 的 name/目录不符合 lowercase canonical name；
- `ts-local-launch` 的 frontmatter name 为 `tikistar-local-launch`，与目录名不一致。

PipeBuilder 已支持这些旧 Skill 普遍使用的 `description: >`、`|`、`>-`、未知 block scalar、未知嵌套 metadata、BOM 和 CRLF，并原样复制 common package。剩余两个问题必须显式 rename，Builder 不静默改变 Skill identity。

外部 THarness checkout 不属于仓库 E0 依赖。对应 parser 行为由仓库内 self-contained fixture 固化；迁移时可以额外对目标 catalog 执行一次完整 `check`。

## 尚未完成的外部认证

- Cursor、CodeBuddy、Claude Code 的真实客户端 E1；
- 已加入但尚需观察首轮结果的 Windows/macOS 原生 CI；
- nested Skill/tagents 的独立批量迁移工具；
- Git/registry Provider 和 adapter plugin，二者仍属于后续阶段。
