# PipeBuilder：Python E2E 集成测试架构

状态：implemented baseline
日期：2026-07-13  
适用范围：`pipebuilder.py` 的离线验收、四 Agent 客户端兼容性、真实 Agent 验收与发布门禁

相关文档：

- [PipeBuilder 架构提案](pipebuilder-architecture-proposal.md)
- [PipeSpace 与 Skill Provider 协议](pipebuilder-space-json-spec.md)
- [四 Agent Adapter 首版规范](pipebuilder-agent-adapters.md)
- [Skill Fixture Catalog 与 Agent 能力覆盖](pipebuilder-skill-fixture-catalog.md)

---

## 1. 结论

PipeBuilder 的测试代码统一使用 Python，并只建设 E2E 集成测试，不建设按内部函数、class 或 adapter 拆分的单元测试层。

每个测试都必须：

1. 创建一个完整且隔离的 PipeSpace sandbox；
2. 使用 `subprocess` 执行准备发布的同一个 `pipebuilder.py`；
3. 从 CLI exit code、stdout/stderr、文件系统、lock 和 Agent 客户端可观察行为验收结果；
4. 不 import `pipebuilder.py`，不调用内部 parser、resolver、renderer 或 adapter；
5. 不复用 production 中的规范化、选择、merge、digest 或 render 实现来计算期望值。

测试代码可以拆成多个 `.py` 文件以便维护；“单文件”约束只针对发布产物：

```text
发布：pipebuilder.py
测试：tests/e2e/**/*.py
```

JSON 仍用于 PipeSpace 输入、CLI report 和 golden data，但不再使用 MJS、TypeScript、npm test runner 或 shell test script。

---

## 2. 为什么采用 E2E-only

PipeBuilder 的主要风险不在某个纯函数是否按实现运行，而在完整构建的边界行为：

- 多个 Skill Provider 的发现、优先级、显式名单和 tag 匹配能否共同工作；
- workspace 路径能否在不同 cwd 和操作系统上正确解释；
- 四个 adapter 的投影是否能被对应 Agent 实际发现；
- Human-owned source 是否始终保持 byte-for-byte 不变；
- managed artifact、lock 和 provenance 是否一致；
- build 失败是否只留下可通过再次 build 覆盖的 Builder-owned target；
- clean 是否只删除 PipeBuilder 拥有的内容；
- argv、路径、symlink、secret 和配置 merge 是否跨越了安全边界。

这些结论只有经过完整 CLI、真实文件系统和真实子进程路径后才成立。

AI 生成实现和测试时，细粒度单元测试还容易复制实现中的同一个错误假设：production helper 和 test helper 同时“算错但一致”。本项目因此把发布门禁放在独立 contract、固定输入、人工可审查 golden、负向场景以及真实客户端行为上。

这不是“Python `unittest` 模块不能用于 E2E”的概念争论，也不是断言所有项目的单元测试都无价值；它是 PipeBuilder 的明确工程取舍：不建立 unit suite，测试预算全部用于外部可观察契约。

---

## 3. 被测对象与黑盒边界

### 3.1 唯一被测入口

Runner 必须拿到明确的 release candidate 路径，并以当前 Python 解释器启动：

```python
subprocess.run(
    [sys.executable, str(pipebuilder), "build", "--format", "json"],
    cwd=space_root,
    env=controlled_env,
    shell=False,
    text=True,
    capture_output=True,
)
```

禁止：

```python
import pipebuilder
pipebuilder.build(...)
```

也禁止测试时复制 production 中某段函数出来作为 oracle。

### 3.2 完整系统边界

一次离线 E2E 至少包含：

```text
pipespace.json
<name>.code-workspace
PipeSpace .pipebuilder/agents/
PipeSpace .pipebuilder/skills/
一个或多个外部 folder Skill Provider
workspace 引用的项目目录
pipebuilder.py 子进程
真实临时文件系统
四个 adapter 的生成结果
.pipebuilder/lock.json
.pipebuilder/build.lock
CLI JSON report
```

安装了 Agent CLI 的测试还要把生成后的整个 PipeSpace 交给真实客户端检查，而不是只验证“文件存在”。

### 3.3 不 mock 的边界

离线 E2E 不 mock：

- 文件读写、rename、权限和 symlink；
- `pipebuilder.py` 进程；
- JSON/TOML/frontmatter 的最终解析；
- lock、并发锁、逐文件 atomic replace 和 clean。

Agent CLI、账号和网络不作为 PR 离线测试的强依赖，而进入后续两个 E2E 运行级别。

---

## 4. 三个 E2E 运行级别

这里的级别表示外部依赖和验收强度，不表示 unit/integration 的代码分层。

### E0：离线 PipeSpace E2E

每个 case 从完整 PipeSpace 输入开始，执行最终 `pipebuilder.py`，检查构建后的完整状态。

特征：

- 无网络；
- 无账号；
- 不要求安装 Codex、Cursor、CodeBuddy 或 Claude Code；
- Linux、Windows、macOS 均使用本机文件系统执行；
- 确定性强，全部 PR 必跑；
- 覆盖绝大多数 manifest、selection、adapter projection、ownership、concurrency 和 security contract。

### E1：已安装客户端 E2E

使用 E0 构建出的真实 PipeSpace，再调用机器上安装的 Agent CLI 或官方检查命令，验证客户端能够解析和发现生成结果。

特征：

- 使用真实客户端版本；
- 优先使用不发起模型请求的 parse、check、policy、config discovery 或 hook probe；
- 记录 Agent CLI 名称、版本、平台和实际执行命令；
- nightly、main 或 release runner 执行；
- `--require` 模式下缺失客户端是失败，不是 skip。

已实装的 Codex E1 包括 generated `AGENTS.md`/Skill 的原生 prompt assembly、可信项目配置发现、project hook schema parse 以及 `codex execpolicy check`。Hook 的真实执行进入 E2。其他平台只在确认了对应版本的稳定官方入口后加入，不臆造 CLI 参数。

### E2：真实 Agent E2E

在生成后的 sandbox 中发起最小真实 Agent 会话，使用 sentinel Skill、rule、hook、command 或 subagent 验证 Agent 实际消费了产物。

特征：

- 需要安装客户端、账号、凭据和网络；
- 默认 opt-in；
- 不比较完整自然语言输出；
- 只验收机器可判定的 sentinel、文件或结构化事件；
- 用于 nightly、release candidate 或人工兼容性认证；
- 结果与 E0 确定性门禁分开报告，避免模型波动阻断普通开发。

首版 E2 只使用 Codex。当前 sentinel Skill 先写入 disposable 本地 Git repository，经 Git Provider 的 branch/subdir、commit lock 和 cache 构建，再由真实 Codex 模型消费；同一请求还验证 generated `AGENTS.md` 与 SessionStart hook。Runner 默认使用已安装 Codex 的有效默认模型，release job 可通过显式 `--model` 固定模型；不在仓库中硬编码可能下线的 model id。它只影响 E2，不进入 E0/E1，也不写入 PipeSpace 产品协议。Cursor、CodeBuddy 和 Claude Code 首版完成 E0 投影；只有确认稳定官方入口后才加入 E1/E2。

---

## 5. 测试仓库目录

当前 PipeBuilder 开发仓库采用：

```text
pipebuilder/
├── pipebuilder.py
└── tests/
    └── e2e/
        ├── run.py
        ├── support/
        │   ├── __init__.py
        │   ├── case.py
        │   ├── sandbox.py
        │   └── model.py
        ├── cases/
        │   ├── offline/
        │   │   ├── test_contract.py
        │   │   ├── test_manifest_workspace.py
        │   │   ├── test_providers_skills.py
        │   │   ├── test_adapters.py
        │   │   └── test_lifecycle_security.py
        │   ├── client/
        │   │   └── test_codex_client.py
        │   └── live/
        │       └── test_codex_live.py
        ├── fixtures/
        │   └── spaces/minimal-all-agents/
        │       ├── input/
        │       └── expected/
        ├── README.md
        ├── COVERAGE.md
        └── .artifacts/
```

初期仍在 THarness 仓库开发时，可以放在 `harness/pipebuilder/`；独立发布时目录原样迁走。

`.artifacts/` 必须被 Git ignore。失败 case 的 sandbox、stdout、stderr、report、tree diff 和客户端版本写入其中，成功 case 默认删除临时目录。

静态 all-agent fixture 负责人工可审查 golden；大量 invalid、resolution、lifecycle 和 adapter 组合由 case 在独立 sandbox 中构造，避免复制几十棵只差一个字段的目录。具体 requirement 到 case 的实装映射见 `tests/e2e/COVERAGE.md`；[Skill Fixture Catalog](pipebuilder-skill-fixture-catalog.md) 保留为后续扩大实体 fixture pack 的目标目录。

---

## 6. E2E case 协议

### 6.1 一个 case 的目录

```text
minimal-all-agents/
├── case.py
├── input/
│   ├── space/
│   │   ├── pipespace.json
│   │   ├── demo.code-workspace
│   │   └── .pipebuilder/
│   ├── providers/
│   │   ├── provider-a/
│   │   └── provider-b/
│   └── projects/
│       ├── project-a/
│       └── project-b/
└── expected/
    ├── files/
    ├── tree.json
    ├── report.json
    └── lock.json
```

`input/` 内的相对关系就是测试中的实际相对关系。Runner 把整个 `input/` 复制到同一个临时根，不能只复制 `space/` 后重新拼造 Provider 路径，否则测不到真实的 workspace 和 Provider path resolution。

### 6.2 为什么 case 行为写在 Python

不再设计一套 `case.json` 测试 DSL。复杂生命周期本来就是过程：build、修改 source 或 generated target、再次 build、clean、比较前后状态。用 Python 表达更直接，也避免为测试再维护一个解释器。

`pipespace.json` 和 expected JSON 是产品输入与验收数据，不属于测试执行语言。

### 6.3 case.py 最小形态

```python
from support.case import PipeBuilderE2ECase


class Case(PipeBuilderE2ECase):
    id = "offline.build.minimal_all_agents"
    tier = "offline"
    tags = {"build", "all-agents", "golden"}

    def run(self):
        box = self.create_sandbox()
        inputs_before = box.snapshot_inputs()

        first = box.pipebuilder("build", "--format", "json")
        self.expect_exit(first, 0)
        self.expect_report_schema(first, "pipebuilder-report.v1")
        self.expect_golden_tree(box)
        self.expect_golden_lock(box)
        self.expect_inputs_unchanged(box, inputs_before)

        built = box.snapshot_all()
        second = box.pipebuilder("build", "--format", "json")
        self.expect_exit(second, 0)
        self.expect_snapshot_equal(box.snapshot_all(), built)
```

这段测试只使用测试侧的 subprocess、snapshot 和 assertion helper，不接触 production internals。

### 6.4 metadata

每个 case 至少声明：

- 全局唯一 `id`；
- `tier`: `offline`、`client` 或 `live`；
- `tags`；
- 支持的平台；
- 对应 requirement/diagnostic id；
- 是否允许并行；
- client/live case 所需客户端能力。

Runner 启动时检查 case id 重复和 metadata 完整性。

---

## 7. Sandbox 与环境隔离

每次 case 都创建全新的 `tempfile.TemporaryDirectory`，目录至少为：

```text
<temp>/
├── input-copy/
│   ├── space/
│   ├── providers/
│   └── projects/
├── home/
├── tmp/
└── captures/
```

Runner 构造最小环境：

- 独立 `HOME`；
- Windows 下独立 `USERPROFILE`、`APPDATA` 和 `LOCALAPPDATA`；
- 独立临时目录；
- 固定 locale、timezone 和可控时间输入；
- 清除会改变 Agent 或 PipeBuilder 行为的用户级环境变量；
- 仅保留启动 Python 和受测客户端所需的最小 `PATH`；
- 不继承真实用户的 `.codex`、Cursor、CodeBuddy 或 Claude Code 配置。

客户端 E2E 如必须读取登录态，应显式挂载只读凭据位置；不得把真实 home 直接作为 PipeSpace home。

所有子进程均以 argv list 和 `shell=False` 启动。测试本身也不能靠 shell quoting 得出正确结果。

---

## 8. 每个离线 E2E 的基础断言

成功 build case 默认检查以下 invariants，case 只有明确理由才可关闭某一项。

### 8.1 输入不可变

以下输入在 build 前后必须 byte-for-byte 不变：

- `pipespace.json`；
- `<name>.code-workspace`；
- `.pipebuilder/agents/` 和 `.pipebuilder/skills/`；
- 所有外部 Skill Provider；
- workspace 引用的项目。

平台 target 配置不是 Human-owned，包括根 `AGENTS.md`、`CLAUDE.md` 和 `.mcp.json`。测试必须证明它们完全由 `.pipebuilder/agents`、Skill `.pipe-agents` 和 core-generated workspace rule 决定；直接修改 target 后再次 build 应恢复 source 定义。

### 8.2 生成树精确

测试不只断言少数文件存在，还要比较：

- path；
- file/directory/symlink kind；
- UTF-8 内容或 binary digest；
- executable bit；
- symlink target；
- 不应出现的额外文件。

尤其要断言 `.pipe-agents` 输入不会泄漏到 Agent 可见的 common Skill package。

### 8.3 report 与 diagnostic

使用 `--format json` 验证：

- schema 为 `pipebuilder-report.v1`；
- CLI command name、status 和 exit semantics；
- stable diagnostic code；
- operation summary；
- selected/shadowed Skill；
- provenance；
- build lock 状态；
- report 中没有凭据和环境 secret。

测试依赖 stable code 和结构化字段，不比较易变的人类文案全文。

### 8.4 lock 与 provenance

检查：

- 每个 managed artifact 都有 owner、source、digest 和 adapter；
- lock 不记录机器特定的不可移植路径，除非协议明确要求并经过规范化；
- source digest 与 fixture 实际内容一致；
- shadowed provider 和显式选择原因可解释；
- lock 不包含 token、完整敏感环境变量或 secret value。

### 8.5 幂等

第二次 build 后：

- 生成树无变化；
- Human inputs 无变化；
- lock 的语义内容无变化；
- report 只允许协议声明的时间、duration 等易变字段变化；
- 不产生临时文件或 `build.lock` 残留。

### 8.6 clean 是 build 的受控逆操作

执行 clean 后：

- 仅删除 lock 中属于 PipeBuilder 的 artifact；
- Human-owned 文件和用户后加文件保持不变；
- 非空人工目录不被递归删除；
- PipeSpace 可以再次 build 并得到相同结果；
- clean 重复执行具有明确且稳定的幂等语义。

### 8.7 简化失败语义

在输入冲突、非法 manifest、adapter 冲突或写入前校验失败时：

- 最终树保持调用前状态；
- lock 不前移到新状态；
- 临时文件不暴露为最终 artifact。

应用阶段只保证单文件 atomic replace，不保证跨文件 transaction。测试应验证应用中断后旧 `lock.json` 保持不变，并且删除 stale `build.lock` 后再次 build 可以按 source 收敛到完整结果；不再测试 transaction journal 或自动 rollback。

---

## 9. Golden 策略

### 9.1 Golden 内容

稳定成功场景保存：

- `expected/files/`：应生成的关键文件全文；
- `expected/tree.json`：完整 managed tree 与 digest；
- `expected/report.json`：归一化后的结构化 report；
- `expected/lock.json`：归一化后的 lock。

不是每个负向 case 都需要完整 files golden；但必须有 exit code、diagnostic code、无副作用 snapshot 和必要 report golden。

### 9.2 动态字段归一化

只允许白名单替换：

```text
$SPACE_ROOT
$SANDBOX_ROOT
$BUILDER_SHA256
$FIXED_TIME
$PLATFORM
```

Normalizer 位于测试侧，规则必须简单、显式且可审查。不得排序本来有顺序语义的数组，不得删除未知字段，不得把所有绝对路径或时间戳泛化掉来掩盖错误。

### 9.3 更新流程

Golden 只能显式更新：

```bash
python3 tests/e2e/tools/update_goldens.py \
  --case offline.build.minimal_all_agents
```

CI 永不自动更新 golden。更新提交必须同时审查：

- contract 为什么变化；
- tree diff；
- report/lock diff；
- 四 Agent 投影 diff；
- 是否意外把本机路径或 secret 写入期望值。

测试 helper 不能调用 production renderer 生成 expected 文件。Golden updater 可以捕获一次实际输出，但捕获结果只是 review candidate，不是自动正确的 oracle。

---

## 10. 必需 E2E 场景矩阵

### 10.1 Manifest 与 workspace

- 最小四 Agent PipeSpace；
- `pipespace.json.name` 与目录 basename 不同；
- workspace 文件缺失、多份、名称不匹配；
- JSON malformed、schema/version 不支持、unknown key；
- 仅存在旧 THarness `tagents/private/.harness-space.yaml/.harness-lock.yaml` layout 时返回 `PB015` 且零写入；
- 新旧 layout 同时存在时不 merge、不猜测优先级；
- workspace 单 folder `path: "."`、外部相对 folder、两种形式混合和多 folder；
- workspace folder 绝对路径、重复路径、缺失路径；
- 路径含空格、Unicode、`#`、引号和 shell metacharacter；
- PipeSpace 从自身 cwd 和显式目录参数构建；
- `check`、`explain`、`build --dry-run` 不产生写入。

### 10.2 Skill Provider 与选择

- 零、一个、多个 folder Provider；
- folder Provider 的同目录/外部相对目录/symlink root、内容 digest 更新、缺失/非目录、generated target 递归和 symlink loop；
- Git Provider 的 `branch`/`tag` 二选一 schema、subdir、URL credential 拒绝；
- Git branch 在线推进、tag 固定、branch/tag 到 immutable commit 的 lock provenance；
- Git PipeSpace-local cache、无可变 checkout、`--offline` 锁定 commit 复用、缺 cache 和 snapshot digest 篡改；
- Git archive symlink、缺 branch/tag/subdir 和 Git 命令失败返回稳定 diagnostics；
- folder/Git/space-local 混合时仍严格按统一 Provider 顺序 shadow；
- PipeSpace-local `.pipebuilder/skills` 的最高优先级；
- 显式 `skills` 名单优先；
- tag 匹配并集；
- 同名 Skill shadow 与 provenance；
- provider 顺序变化；
- 缺失 `SKILL.md`、非法 Skill name、重复 canonical name；
- provider 路径越界、symlink 越界和循环；
- 未选择 Skill 不进入任何 Agent 输出。

### 10.3 四个 adapter

每个 adapter 都以完整 PipeSpace build case 覆盖：

- portable common Skills 和该平台 full-capability Skill 安装；
- workspace rule；
- 每一种已支持的平台原生 source surface；
- gated/unsupported surface 的明确拒绝；
- Space-level 与 Skill-level artifact 合并；
- unknown directory；
- semantic key 冲突；
- Human-owned source 不变和 Builder-owned target 重生成；
- config semantic merge；
- hook/MCP secret lint；
- clean 与重复 build；
- Windows path normalization。

Codex 额外覆盖：

- canonical workspace rule、Space `AGENTS.md` source 和 Skill `AGENTS.md` source 的稳定合成；
- generated 根 `AGENTS.md` 的原生发现与 target drift 恢复；
- project config discovery；
- `.codex/rules` command policy；
- `.codex/hooks.json` source merge 与 project trust 行为。

这些都是通过完整 build 和最终文件/客户端行为测试，不允许直接构造 adapter class 调用 render。

### 10.4 Ownership 与生命周期

- 首次 build；
- 无变化重复 build；
- source 变化后的受控更新；
- 直接修改 generated target 后 rebuild 恢复 source 定义；
- 与计划无关的 sibling 文件保持不变；
- lock 缺失、损坏、旧 schema、builder 版本变化；
- managed file 被删除或类型改变；
- clean 只删除 owned artifact；
- build/clean 并发锁竞争；
- 失败后再次 build 可恢复。

### 10.5 简化写入与并发

- 规划阶段失败时零写入；
- 每个目标文件通过同目录临时文件加 atomic replace 写入；
- 成功后没有临时文件残留；
- 已存在 `build.lock` 时返回 `PB013`；
- stale `build.lock` 返回 `PB014`，由 Human 确认后删除；
- 应用中断时旧 `lock.json` 不前移，重新 build 后完整收敛；
- 不生成 transaction journal。

### 10.6 Security 与 portability

- `..`、absolute target、symlink escape；
- symlink loop；
- Windows junction/reparse point；
- Windows drive、UNC 和 case-insensitive collision；
- macOS/Linux case-sensitive 差异；
- reserved device name 和非法文件名；
- secret 出现在 manifest、hook、MCP config 时的 lint/redaction；
- executable bit；
- UTF-8 BOM、CRLF/LF 和 Unicode normalization；
- 超长路径及深层 Skill tree。

平台文件系统行为必须在对应原生 OS runner 上验收，不能只靠字符串模拟 Windows 或 macOS。

### 10.7 Diagnostics

PipeSpace 协议定义的每个 stable diagnostic code 至少对应一个完整失败 E2E。`COVERAGE.md` 建立 requirement/diagnostic 到 case id 的映射；没有 E2E case 的诊断码不能进入 stable contract。

---

## 11. 真实客户端 E2E

### 11.1 两阶段执行

每个 E1 case 都执行：

```text
阶段 A：pipebuilder.py build 完整 sandbox
阶段 B：真实 Agent 客户端读取同一个 sandbox
```

如果阶段 A 失败，不执行阶段 B；如果阶段 B 失败，保留完整构建树和客户端输出。

### 11.2 Capability probe

测试不能只根据可执行文件名猜测能力。Runner 先记录：

- executable realpath；
- version；
- OS/architecture；
- 支持的无网络验证入口；
- 是否具备账号但本 case 是否使用；
- verification level。

报告中的 verification level 建议为：

```text
generated-only
client-parsed
client-discovered
live-consumed
```

### 11.3 允许 skip 的边界

- 普通开发执行 E1 时，未安装客户端可以结构化 skip；
- nightly 应至少有每个平台的固定 runner；
- release 的 `--require --agent <id>` 不允许 skip；
- “命令不存在”和“命令执行后不兼容”必须区分；
- 版本不在支持矩阵内时报告 unsupported，不伪装成功。

### 11.4 不猜测平台行为

每个平台的 client case 必须引用 adapter 文档中已确认的官方能力和命令。客户端版本升级导致入口变化时，先更新 compatibility note 和 E1 case，再宣称支持新版本。

---

## 12. 真实 Agent E2E

### 12.1 Codex 默认模型 profile

Codex E2 不在测试仓库中硬编码默认 model id。普通 live run 使用已安装 Codex 当前有效的默认模型；需要 release reproducibility 时，由 release job 显式传 `--model <model-id>`，并在 `e2e-report.json` 记录 requested override、Codex client version、实际 argv 和结果。

Runner 的模型选择优先级为：

```text
CLI --model
> installed Codex effective default
```

这样既不会因文档中的旧模型名使 suite 无法运行，也不会通过环境变量悄悄改变 release profile。若客户端事件无法暴露 effective model，报告只能声明“使用 client default”，不能猜测具体 id。

Runner 最终调用的形态应等价于：

```text
codex --ask-for-approval never \
  --sandbox workspace-write \
  --cd <space-sandbox> \
  --dangerously-bypass-hook-trust \
  exec \
  --ephemeral \
  --json \
  --output-schema <schema> \
  --output-last-message <capture> \
  <sentinel-prompt>
```

Python runner 仍以 argv list 和 `shell=False` 启动它。不得使用 `--dangerously-bypass-approvals-and-sandbox`。当前组合 sentinel 需要验证 project hook，因此只在 disposable sandbox 中使用 `--dangerously-bypass-hook-trust`，且 hook source/path 都由本 case 构建。临时 `CODEX_HOME` 只以 symlink 挂载现有 auth，不复制凭据到 fixture 或 report。

### 12.2 Sentinel 验收

真实模型输出不适合全文 golden。每个 E2 case 使用唯一、不可偶然命中的 sentinel，例如：

```text
HARNESSBUILDER_E2E_SKILL_7F31
```

可验收方式包括：

- 指定 Skill 被触发后创建限定内容的 sandbox 文件；
- hook 把 sentinel 写入 capture 文件；
- subagent 返回结构化 sentinel；
- command 收到预期参数并留下 receipt；
- rule 对明确 allow/deny command 给出可机判定结果。

Prompt 必须短、确定、无业务数据。测试不得让 Agent访问 sandbox 外文件、修改仓库或使用生产凭据。每次执行设置时间和 token 上限，并把费用、模型、客户端版本作为报告 metadata。

E2 失败用于兼容性告警和 release 审核；是否阻断发布由平台稳定性策略决定，但不能用重试到成功掩盖真实失败率。允许固定次数重试时，必须报告每一次结果。

---

## 13. Python Runner

### 13.1 命令

```bash
python3 tests/e2e/run.py --tier offline
python3 tests/e2e/run.py --tier offline --case offline.concurrency.build_busy
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --model <model-id> --require
python3 tests/e2e/run.py --tier offline --jobs 8
```

Runner 只使用 Python 标准库。当前用 `ThreadPoolExecutor` 并发执行 subprocess-heavy 的 parallel-safe case，每个 case 仍有独立 sandbox；标记为 serial 的并发锁或真实客户端 case 单独运行。

### 13.2 Runner 输出

人类输出保持简洁：

```text
PASS offline.build.minimal_all_agents  0.42s
FAIL offline.ownership.generated_rebuild  0.11s
SKIP client.cursor.discovery            client-not-installed
```

同时生成结构化 `e2e-report.json`，至少包含：

- suite schema/version；
- release artifact path 和 SHA256；
- Python/OS 信息；
- case id、tier、duration、status；
- PipeBuilder exit/report；
- Agent client version、requested/effective model 和 override source；
- skip/failure reason；
- artifact capture path。

Release report 必须证明所有 case 执行的是同一个 SHA256 的 `pipebuilder.py`。

### 13.3 失败保留

失败时把 sandbox 复制到：

```text
tests/e2e/.artifacts/<run-id>/<case-id>/
```

包含：

- input copy；
- actual output tree；
- normalized/unnormalized report；
- stdout/stderr；
- snapshot diff；
- `build.lock` 和临时文件状态；
- client capability/version；
- 可直接复制执行的 argv 和 cwd 描述。

不得保存 secret；capture 前再次执行 redaction。

---

## 14. CI 与发布门禁

### 14.1 Pull request

必须通过：

- 全部 E0 offline cases；
- Linux 与 Windows 原生 runner；
- changed golden review；
- release candidate 单文件在临时位置执行，证明不依赖仓库 import path。

macOS E0 建议在 main 或 nightly 全量运行；与 macOS 文件系统相关的必需 case 必须在 release 前执行。

### 14.2 Main/nightly

- Linux、Windows、macOS 全量 E0；
- 四个平台固定 runner 上的 E1；
- crash/kill、并发和大 fixture stress cases；
- 可选 Codex E2 live sentinel（使用 client default 或 release job 显式 `--model`）；
- 客户端版本变化和兼容矩阵报告。

### 14.3 Release candidate

1. 冻结一个 `pipebuilder.py` SHA256；
2. 三个 OS 的 E0 都执行该内容相同的 artifact；
3. 四 Agent 的 E1 以 `--require` 执行，不得静默 skip；
4. E2 结果单独列出；
5. 归档结构化 report、客户端版本和 checksum；
6. 测试通过后发布的必须仍是同一个 SHA256。

---

## 15. 防止 AI 生成测试“自证正确”

E2E 不是自动可靠，仍要主动保持 oracle 独立：

1. 行为依据来自版本化协议，不来自当前实现结构；
2. 测试禁止 import production；
3. 测试 helper 不实现 Provider resolver 或 adapter renderer；
4. Golden 以显式文件和结构化结果入库并由人审查；
5. 每个 happy path 配套至少一个输入 mutation 或失败场景；
6. 断言完整树、输入不可变、lock/provenance 和重复构建，不只看 exit code；
7. 关键 adapter 经过真实客户端解析或消费；
8. 同一需求的正向和负向 case 使用不同 fixture；
9. 修复 bug 时先提交能在旧 artifact 上失败的完整复现 case；
10. Golden 大范围变化必须解释 contract 变化，不能简单“一键接受”。

这里的 mutation 指对 PipeSpace、Provider、generated artifact、lock 或 build-lock 状态做外部改变后重新执行完整 CLI，不是调用内部函数做微型测试。

---

## 16. 从现有 Builder 测试迁移

当前 Node/TypeScript Builder 的测试不继续扩建，逐步迁成 Python E2E：

| 现有内容 | 新位置 | 迁移方式 |
| --- | --- | --- |
| `tests/integration/builtin-builder.mjs` | `cases/offline/build/cursor_legacy_parity/` | 转成完整 `pipespace.json`、workspace、Provider 和 Cursor 产物 golden |
| `tests/fixtures/builtin/*` | `cases/offline/**/input/` | 转成标准 `skills/foo/SKILL.md` 与 `.pipe-agents/` |

现有 command-runner 测试不迁入 PipeBuilder；build command 已从新协议删除。

迁移期间允许旧 Builder 自己的 Node integration test 暂时存在，但 PipeBuilder 的任何新行为只能进入 Python E2E suite。PipeBuilder 达到 Cursor parity 后，旧 suite 作为旧实现测试随旧 Builder 一起退役。

---

## 17. 首版最小落地顺序

### Step 1：先建立 runner 和三个基准 case

- minimal all-agents build；
- malformed manifest 无写入；
- build -> build -> clean -> build 生命周期。

这三项先固定 sandbox、snapshot、report 和 golden 协议。

### Step 2：Provider/selection 与四 adapter

- provider priority；
- explicit skill + tag union；
- 每个平台完整成功投影；
- semantic conflict、Human-owned source 不变和 generated target 重生成。

### Step 3：ownership/concurrency/security

- managed artifact mutation；
- stale/corrupt lock；
- busy/stale `build.lock`；
- symlink/path escape；

### Step 4：真实客户端

- 先接入 Codex E1；
- 每确认一个平台稳定入口，就为其建立固定 runner 和 capability report；
- 最后增加最小 E2 sentinel。

首版发布不能只完成 happy path。至少 E0 全矩阵、四 adapter 投影、ownership、clean、concurrency 和 security 边界通过后，才具备替代现有 Builder 的条件。

---

## 18. 验收标准

测试架构完成的定义是：

1. 所有测试执行代码均为 Python；
2. 没有 PipeBuilder unit suite，也没有 adapter direct-call test；
3. 每个 case 都通过 subprocess 执行待发布的 `pipebuilder.py`；
4. PR 可在无 Agent、无账号、无网络环境完成全部 E0；
5. 四 Agent 都有完整 PipeSpace projection case 和真实客户端 E1 入口；
6. build、重复 build、应用中断后重新收敛、clean 和再次 build 都有 E2E；
7. Human-owned 输入、ownership、provenance、secret redaction 和路径边界有负向验证；
8. Linux、Windows、macOS 的平台行为在原生 runner 上验证；
9. release report 能追溯到唯一 `pipebuilder.py` SHA256；
10. 任何 stable diagnostic 和 supported adapter capability 都能映射到至少一个 E2E case。
