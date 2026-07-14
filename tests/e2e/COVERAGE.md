# HarnessBuilder E2E 覆盖矩阵

状态：implemented
基线日期：2026-07-14
最近验证：完整 E0 101/101（含 HSpace Tree 定向 9/9），Codex E1 5/5，Codex E2 1/1

这里统计的是独立黑盒 test method；一个 method 内的 table/subtest 还会覆盖多个输入变体。所有 case 都执行最终 `harnessbuilder.py`，不 import production。

## 运行级别

| Tier | 当前覆盖 | 外部依赖 | 默认门禁 |
| --- | --- | --- | --- |
| E0 offline | 101 个 case，200+ 个正负场景 | Python 3.7+、Git、真实文件系统；不访问网络 | PR 必跑 |
| E1 client | Codex 5 个 case | Codex CLI；不请求模型、不要求登录 | main/release |
| E2 live | Codex 1 个组合哨兵 case | Codex CLI、登录、网络、模型 | opt-in/release |

## E0 requirement 映射

| Requirement | 主要 case/module | 验收内容 |
| --- | --- | --- |
| CLI/report | `test_contract.CliContractCases` | cwd/显式 space、text/JSON、version、check/explain/dry-run 零写入、compile、Python 3.7 语法基线 |
| init | `test_contract.InitCases` | 创建目录与默认必需文件、目录名/显式 name、已有文件校验、幂等与失败零写入 |
| 静态 golden | `test_contract.GoldenBuildCases` | 四 Agent 完整 managed target 集、关键文件全文、lock digest/provenance、二次 build byte stability |
| manifest | `test_manifest_workspace.ManifestValidationCases` | malformed/non-object、required/unknown fields、schema、name、agents、skills、tags、providers、description |
| workspace | `test_manifest_workspace.WorkspaceValidationCases` | 必选文件、malformed、folder shape、同目录、目录解耦、多 folder、重复 realpath、Unicode/空格/引号/`#`/`$` |
| legacy namespace | `test_manifest_workspace.LegacyNamespaceCases` | `tagents`、`private`、root `.harness-agents`、旧 YAML/lock/workspace source；零写入 |
| folder provider/selection | `test_providers_skills.ProviderResolutionCases` | 零/缺失/multiple、同目录/外部/symlink root、file root、realpath alias、Unicode/shell metacharacter、digest 更新、local 优先、显式+tag+local 并集、shadow provenance、provider 顺序 |
| Git provider | `test_providers_skills.GitProviderCases` | branch/tag、subdir、commit lock、在线推进、离线锁定复用、独立 cache、缺 cache/ref/subdir、digest 篡改、archive symlink、混合优先级 |
| common Skill | `test_providers_skills.SkillPackageCases` | binary、hidden、executable、YAML block scalar、unknown nested frontmatter、BOM/CRLF、深目录、`.DS_Store`、`.harness-agents` 排除、symlink、invalid/missing Skill |
| Codex adapter | `test_adapters.CodexAdapterCases` | AGENTS、config TOML、native hooks schema、hook files、rules、稳定 merge、target drift、machine key 拒绝 |
| Cursor adapter | `test_adapters.OtherAdapterCases` | skills、workspace rule、`.mdc` rules、commands、frontmatter |
| CodeBuddy adapter | `test_adapters.OtherAdapterCases` | skills、workspace rule、commands、agents、settings、MCP、hook files |
| Claude Code adapter | `test_adapters.OtherAdapterCases` | skills、CLAUDE、rules、commands warning、agents、settings、MCP、hook files |
| adapter negatives | `test_adapters.AdapterRejectionCases` | gated/unknown/empty surface、hook/MCP/settings/agent/rule schema、TOML 子集、semantic conflict、portable collision、command/MCP secret lint |
| ownership/clean | `test_lifecycle_security.OwnershipLifecycleCases` | clean 只删 owned、幂等、rebuild、反选 Skill、移除 Agent、source update、managed file 删除、Builder version 变化、无 lock 不猜 ownership |
| lock/concurrency | `test_lifecycle_security.LockAndInterruptionCases` | 两个真实进程争锁、active/stale/malformed lock、硬崩溃、apply failure、旧 lock 保持、恢复收敛 |
| filesystem security | `test_lifecycle_security.FilesystemBoundaryCases` | forged lock、unowned target、type drift、Builder state/target symlink escape、NFC/NFD/case collision、Windows reserved name、invalid lock、recursive provider |
| Leader-rooted HSpace Tree | `test_space_tree.HSpaceTreeCases` | 显式内嵌 children、全树 check/explain/build/verify、单 Space 非递归、反向 clean、独立 ownership/锁、越界/保留路径/symlink/嵌套拒绝、成员身份与顺序漂移、跨成员 stale plan、post/最终验收失败 journal 与重跑收敛 |
| release/runner | `test_contract.CliContractCases` | 单文件复制后独立执行、SHA256 report、command record credential redaction、失败制品排除 auth/home |

## Stable diagnostics

| Code | E2E 入口 | 状态 |
| --- | --- | --- |
| HB001 | malformed/shape/schema/unknown manifest、invalid lock | covered |
| HB002 | invalid space name table | covered |
| HB003 | exact workspace missing/name mismatch | covered |
| HB004 | malformed workspace、folder/path table | covered |
| HB005 | missing folder/Git cache/branch/tag/subdir | covered |
| HB006 | unsupported provider type | covered |
| HB007 | missing explicitly selected Skill | covered |
| HB008 | invalid Skill/frontmatter table | covered |
| HB009 | gated/unknown/malformed agent artifact table | covered |
| HB010 | semantic/path/ownership/type conflict | covered |
| HB011 | secret、symlink、machine config、injected filesystem failure | covered |
| HB012 | `adapter-not-implemented` | retired/reserved number；不属于 v1 stable contract，未知 Agent 由 HB001 拒绝 |
| HB013 | real concurrent active lock | covered |
| HB014 | stale dead-pid lock/crash recovery | covered |
| HB015 | every legacy marker | covered |
| HB016 | Provider post command start/cwd/exit failure、Tree partial journal | covered |
| HB017 | Tree schema/path/identity/receipt/stale-plan/member-state | covered |
| HBW001 | provider shadow | covered |
| HBW002 | Claude command migration | covered |

## E1：真实 Codex 客户端

使用已安装 Codex CLI 的真实命令，而非文件存在断言：

- `codex --version` 和非交互命令面 capability probe；
- `codex debug prompt-input` 证明生成的根 `AGENTS.md` 进入 model-visible project instructions；
- 同一个 prompt assembly 证明 `.agents/skills/<name>/SKILL.md` 被扫描并暴露 metadata；
- 隔离 `CODEX_HOME` 写入 disposable project trust，证明生成的 `.codex/config.toml` 被项目层加载；
- `codex execpolicy check` 真实解析并匹配生成的 `.rules`；
- 真实客户端接受当前三层 `hooks.json` schema。

## E2：真实模型

一个模型请求同时验证三条链，减少费用与波动：

1. prompt 只显式提及 `$hb-live-sentinel`，不包含两个期望值；
2. Skill 来自本地真实 Git repository 的 `branch + subdir` Provider，build lock 到 commit 后由 Skill body 提供 Skill sentinel；生成的 `AGENTS.md` 提供另一个 sentinel；
3. `--output-schema` 限定两字段 JSON，最终值必须精确匹配；
4. generated `SessionStart` hook 在 disposable workspace 写 receipt，测试校验 event 与 cwd；
5. 使用 `--ephemeral`、`--ask-for-approval never`、workspace sandbox 和临时 `CODEX_HOME`；真实 auth 只以 symlink 挂载，不复制进 fixture/report。

## 明确未声称覆盖的边界

- 当前机器只完成 Linux 原生文件系统运行；Windows/macOS 的大小写、权限和 symlink 行为仍需对应 OS CI，字符串归一化测试不能替代原生 runner。
- 仓库已加入 Linux/Windows/macOS GitHub Actions E0 matrix；本地结论仍只代表 Linux，首次远端结果需要单独审查。
- Cursor、CodeBuddy、Claude Code 已有完整 E0 projection，但尚未加入真实客户端 E1；只有确认稳定官方 CLI 入口后才添加。
- E2 当前只运行 Codex；不把其他平台模型调用作为首版发布依赖。
- permission denied、磁盘满、真实断电无法可靠地在普通进程内制造；当前以安全故障注入覆盖 apply failure/crash，并用真实双进程覆盖锁竞争。
- `--jobs` 使用线程并行独立 sandbox；真实客户端、模型和锁 timing case 标记 serial。
- 原 THarness `shared-skills` 本机迁移审计为 45 个中 43 个直接兼容；剩余 `BotAI-Log-Analyzer` 和 `ts-local-launch` 是 canonical name/目录名数据问题。仓库内用 multiline/nested fixture 固化解析回归，不把外部 THarness 路径变成 E0 依赖。
