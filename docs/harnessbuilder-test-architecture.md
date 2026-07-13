# HarnessBuilder：Python E2E 集成测试架构

状态：proposal  
日期：2026-07-13  
适用范围：`harnessbuilder.py` 的离线验收、四 Agent 客户端兼容性、真实 Agent 验收与发布门禁

相关文档：

- [HarnessBuilder 架构提案](harnessbuilder-architecture-proposal.md)
- [Harness Space 与 Skill Provider 协议](harnessbuilder-space-json-spec.md)
- [四 Agent Adapter 首版规范](harnessbuilder-agent-adapters.md)
- [Skill Fixture Catalog 与 Agent 能力覆盖](harnessbuilder-skill-fixture-catalog.md)

---

## 1. 结论

HarnessBuilder 的测试代码统一使用 Python，并只建设 E2E 集成测试，不建设按内部函数、class 或 adapter 拆分的单元测试层。

每个测试都必须：

1. 创建一个完整且隔离的 Harness Space sandbox；
2. 使用 `subprocess` 执行准备发布的同一个 `harnessbuilder.py`；
3. 从 CLI exit code、stdout/stderr、文件系统、lock、transaction 和 Agent 客户端可观察行为验收结果；
4. 不 import `harnessbuilder.py`，不调用内部 parser、resolver、renderer 或 adapter；
5. 不复用 production 中的规范化、选择、merge、digest 或 render 实现来计算期望值。

测试代码可以拆成多个 `.py` 文件以便维护；“单文件”约束只针对发布产物：

```text
发布：harnessbuilder.py
测试：tests/e2e/**/*.py
```

JSON 仍用于 Harness Space 输入、CLI report 和 golden data，但不再使用 MJS、TypeScript、npm test runner 或 shell test script。

---

## 2. 为什么采用 E2E-only

HarnessBuilder 的主要风险不在某个纯函数是否按实现运行，而在完整构建的边界行为：

- 多个 Skill Provider 的发现、优先级、显式名单和 tag 匹配能否共同工作；
- workspace 路径能否在不同 cwd 和操作系统上正确解释；
- 四个 adapter 的投影是否能被对应 Agent 实际发现；
- Human-owned 文件是否始终保持 byte-for-byte 不变；
- managed artifact、lock 和 provenance 是否一致；
- build 失败或进程被终止后是否保持原子性并可恢复；
- clean 是否只删除 HarnessBuilder 拥有的内容；
- argv、路径、symlink、secret 和配置 merge 是否跨越了安全边界。

这些结论只有经过完整 CLI、真实文件系统和真实子进程路径后才成立。

AI 生成实现和测试时，细粒度单元测试还容易复制实现中的同一个错误假设：production helper 和 test helper 同时“算错但一致”。本项目因此把发布门禁放在独立 contract、固定输入、人工可审查 golden、负向场景以及真实客户端行为上。

这不是“Python `unittest` 模块不能用于 E2E”的概念争论，也不是断言所有项目的单元测试都无价值；它是 HarnessBuilder 的明确工程取舍：不建立 unit suite，测试预算全部用于外部可观察契约。

---

## 3. 被测对象与黑盒边界

### 3.1 唯一被测入口

Runner 必须拿到明确的 release candidate 路径，并以当前 Python 解释器启动：

```python
subprocess.run(
    [sys.executable, str(harnessbuilder), "build", "--format", "json"],
    cwd=space_root,
    env=controlled_env,
    shell=False,
    text=True,
    capture_output=True,
)
```

禁止：

```python
import harnessbuilder
harnessbuilder.build(...)
```

也禁止测试时复制 production 中某段函数出来作为 oracle。

### 3.2 完整系统边界

一次离线 E2E 至少包含：

```text
harness-space.json
<name>.code-workspace
Harness Space root .harness-agents/
private/skills/
一个或多个外部 folder Skill Provider
workspace 引用的项目目录
harnessbuilder.py 子进程
真实临时文件系统
可选 Harness Space command 子进程
四个 adapter 的生成结果
.harnessbuilder-lock.json
.harnessbuilder/transactions/
CLI JSON report
```

安装了 Agent CLI 的测试还要把生成后的整个 Harness Space 交给真实客户端检查，而不是只验证“文件存在”。

### 3.3 不 mock 的边界

离线 E2E 不 mock：

- 文件读写、rename、权限和 symlink；
- `harnessbuilder.py` 进程；
- Harness Space `command.argv` 的进程启动；
- JSON/TOML/frontmatter 的最终解析；
- lock、transaction、rollback 和 clean。

离线 fixture 可以包含一个 Python 编写的 command probe。它是被 HarnessBuilder 真正启动的外部进程，用来记录 argv、cwd、env 和 exit code，不是对 HarnessBuilder 内部接口的 mock。

Agent CLI、账号和网络不作为 PR 离线测试的强依赖，而进入后续两个 E2E 运行级别。

---

## 4. 三个 E2E 运行级别

这里的级别表示外部依赖和验收强度，不表示 unit/integration 的代码分层。

### E0：离线 Harness Space E2E

每个 case 从完整 Harness Space 输入开始，执行最终 `harnessbuilder.py`，检查构建后的完整状态。

特征：

- 无网络；
- 无账号；
- 不要求安装 Codex、Cursor、CodeBuddy 或 Claude Code；
- Linux、Windows、macOS 均使用本机文件系统执行；
- 确定性强，全部 PR 必跑；
- 覆盖绝大多数 manifest、selection、adapter projection、ownership、transaction 和 security contract。

### E1：已安装客户端 E2E

使用 E0 构建出的真实 Harness Space，再调用机器上安装的 Agent CLI 或官方检查命令，验证客户端能够解析和发现生成结果。

特征：

- 使用真实客户端版本；
- 优先使用不发起模型请求的 parse、check、policy、config discovery 或 hook probe；
- 记录 Agent CLI 名称、版本、平台和实际执行命令；
- nightly、main 或 release runner 执行；
- `--require` 模式下缺失客户端是失败，不是 skip。

首版已明确可验证的 Codex 项目包括生成 hook 的直接执行、项目配置发现以及 `codex execpolicy check`。其他平台只在确认了对应版本的稳定官方入口后加入，不臆造 CLI 参数。

### E2：真实 Agent E2E

在生成后的 sandbox 中发起最小真实 Agent 会话，使用 sentinel Skill、rule、hook、command 或 subagent 验证 Agent 实际消费了产物。

特征：

- 需要安装客户端、账号、凭据和网络；
- 默认 opt-in；
- 不比较完整自然语言输出；
- 只验收机器可判定的 sentinel、文件或结构化事件；
- 用于 nightly、release candidate 或人工兼容性认证；
- 结果与 E0 确定性门禁分开报告，避免模型波动阻断普通开发。

首版 E2 只使用 Codex；默认模型固定为 `gpt-5.4-mini`，与 Rounditer 当前真实模型测试保持一致。它只影响 E2，不进入 E0/E1，也不写入 Harness Space 产品协议。Cursor、CodeBuddy 和 Claude Code 首版完成 E0 投影与 E1 真实客户端发现验证，不要求再付费执行各自的模型会话；未来有明确兼容风险时再加入对应 live profile。

---

## 5. 测试仓库目录

建议 HarnessBuilder 开发仓库采用：

```text
harnessbuilder/
├── harnessbuilder.py
└── tests/
    └── e2e/
        ├── run.py
        ├── support/
        │   ├── __init__.py
        │   ├── case.py
        │   ├── sandbox.py
        │   ├── cli.py
        │   ├── assertions.py
        │   ├── snapshot.py
        │   ├── golden.py
        │   ├── mutations.py
        │   ├── agent_client.py
        │   └── artifacts.py
        ├── cases/
        │   ├── offline/
        │   │   ├── build/
        │   │   ├── workspace/
        │   │   ├── providers/
        │   │   ├── selection/
        │   │   ├── adapters/
        │   │   │   ├── codex/
        │   │   │   ├── cursor/
        │   │   │   ├── codebuddy/
        │   │   │   └── claude_code/
        │   │   ├── ownership/
        │   │   ├── lifecycle/
        │   │   ├── transaction/
        │   │   ├── command/
        │   │   ├── diagnostics/
        │   │   └── security/
        │   ├── client/
        │   │   ├── codex/
        │   │   ├── cursor/
        │   │   ├── codebuddy/
        │   │   └── claude_code/
        │   └── live/
        │       └── codex/
        ├── fixtures/
        │   ├── catalog.py
        │   ├── skill-packs/
        │   │   ├── portable/
        │   │   ├── agent-capabilities/
        │   │   ├── resolution/
        │   │   ├── invalid/
        │   │   └── live-codex/
        │   └── space-overlays/
        ├── tools/
        │   └── update_goldens.py
        ├── COVERAGE.md
        └── .artifacts/
```

初期仍在 THarness 仓库开发时，可以放在 `harness/harnessbuilder/`；独立发布时目录原样迁走。

`.artifacts/` 必须被 Git ignore。失败 case 的 sandbox、stdout、stderr、report、tree diff 和客户端版本写入其中，成功 case 默认删除临时目录。

Fixture 不只是一份最小 Skill。首版使用五套 Skill fixture pack 和一套 Space-level overlay；具体 package、能力矩阵、per-run nonce 和 live probe 见 [Skill Fixture Catalog 与 Agent 能力覆盖](harnessbuilder-skill-fixture-catalog.md)。

---

## 6. E2E case 协议

### 6.1 一个 case 的目录

```text
minimal-all-agents/
├── case.py
├── input/
│   ├── space/
│   │   ├── harness-space.json
│   │   ├── demo.code-workspace
│   │   ├── .harness-agents/
│   │   └── private/
│   ├── providers/
│   │   ├── provider-a/
│   │   └── provider-b/
│   └── projects/
│       ├── primary/
│       └── reference/
└── expected/
    ├── files/
    ├── tree.json
    ├── report.json
    └── lock.json
```

`input/` 内的相对关系就是测试中的实际相对关系。Runner 把整个 `input/` 复制到同一个临时根，不能只复制 `space/` 后重新拼造 Provider 路径，否则测不到真实的 workspace 和 Provider path resolution。

### 6.2 为什么 case 行为写在 Python

不再设计一套 `case.json` 测试 DSL。复杂生命周期本来就是过程：build、修改人工文件、再次 build、制造 command failure、clean、比较前后状态。用 Python 表达更直接，也避免为测试再维护一个解释器。

`harness-space.json` 和 expected JSON 是产品输入与验收数据，不属于测试执行语言。

### 6.3 case.py 最小形态

```python
from support.case import HarnessBuilderE2ECase


class Case(HarnessBuilderE2ECase):
    id = "offline.build.minimal_all_agents"
    tier = "offline"
    tags = {"build", "all-agents", "golden"}

    def run(self):
        box = self.create_sandbox()
        inputs_before = box.snapshot_inputs()

        first = box.harnessbuilder("build", "--format", "json")
        self.expect_exit(first, 0)
        self.expect_report_schema(first, "harnessbuilder-report.v1")
        self.expect_golden_tree(box)
        self.expect_golden_lock(box)
        self.expect_inputs_unchanged(box, inputs_before)

        built = box.snapshot_all()
        second = box.harnessbuilder("build", "--format", "json")
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
- 清除会改变 Agent 或 HarnessBuilder 行为的用户级环境变量；
- 仅保留启动 Python 和受测客户端所需的最小 `PATH`；
- 不继承真实用户的 `.codex`、Cursor、CodeBuddy 或 Claude Code 配置。

客户端 E2E 如必须读取登录态，应显式挂载只读凭据位置；不得把真实 home 直接作为 Harness Space home。

所有子进程均以 argv list 和 `shell=False` 启动。测试本身也不能靠 shell quoting 得出正确结果。

---

## 8. 每个离线 E2E 的基础断言

成功 build case 默认检查以下 invariants，case 只有明确理由才可关闭某一项。

### 8.1 输入不可变

以下输入在 build 前后必须 byte-for-byte 不变：

- `harness-space.json`；
- `<name>.code-workspace`；
- Harness Space root `.harness-agents/`；
- `private/skills/` 和 `private/scripts/`；
- 所有外部 Skill Provider；
- workspace 引用的项目；
- Human-owned `AGENTS.md`、`CLAUDE.md` 和平台配置内容。

需要 semantic merge 的平台配置必须同时验收 Human-owned key、注释和未拥有区域；如果协议无法安全 round-trip，应失败而不是悄悄改写。

### 8.2 生成树精确

测试不只断言少数文件存在，还要比较：

- path；
- file/directory/symlink kind；
- UTF-8 内容或 binary digest；
- executable bit；
- symlink target；
- 不应出现的额外文件。

尤其要断言 `.harness-agents` 输入不会泄漏到 Agent 可见的 common Skill package。

### 8.3 report 与 diagnostic

使用 `--format json` 验证：

- schema 为 `harnessbuilder-report.v1`；
- command、status、exit semantics；
- stable diagnostic code；
- operation summary；
- selected/shadowed Skill；
- provenance；
- transaction/recovery 状态；
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
- 不产生新的 transaction 残留。

### 8.6 clean 是 build 的受控逆操作

执行 clean 后：

- 仅删除 lock 中属于 HarnessBuilder 的 artifact；
- Human-owned 文件和用户后加文件保持不变；
- 非空人工目录不被递归删除；
- Harness Space 可以再次 build 并得到相同结果；
- clean 重复执行具有明确且稳定的幂等语义。

### 8.7 原子性

在输入冲突、非法 manifest、adapter 冲突、command 非零退出或写入前校验失败时：

- HarnessBuilder-owned 最终树保持调用前状态；
- lock 不前移到新状态；
- 临时文件不暴露为最终 artifact；
- report 指明失败 phase 和 rollback/recovery 结果。

Harness Space `command` 自身对外部项目造成的副作用无法由 HarnessBuilder 通用回滚。协议只保证 HarnessBuilder-owned writes 的原子性，并要求 report 明确 command 已运行及其 exit status。

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

- 最小四 Agent Harness Space；
- `harness-space.json.name` 与目录 basename 不同；
- workspace 文件缺失、多份、名称不匹配；
- JSON malformed、schema/version 不支持、unknown key；
- 仅存在旧 THarness `tagents/.harness-space.yaml/.harness-lock.yaml` layout 时返回 `HB018` 且零写入；
- 新旧 layout 同时存在时不 merge、不猜测优先级；
- workspace folder 相对路径、绝对路径、重复路径、缺失路径；
- 路径含空格、Unicode、`#`、引号和 shell metacharacter；
- Harness Space 从自身 cwd 和显式目录参数构建；
- `check`、`explain`、`build --dry-run` 不产生写入。

### 10.2 Skill Provider 与选择

- 零、一个、多个 folder Provider；
- Harness Space-local `private/skills` 的最高优先级；
- 显式 `skills` 名单优先；
- tag 匹配并集；
- 同名 Skill shadow 与 provenance；
- provider 顺序变化；
- 缺失 `SKILL.md`、非法 Skill name、重复 canonical name；
- provider 路径越界、symlink 越界和循环；
- 未选择 Skill 不进入任何 Agent 输出。

### 10.3 四个 adapter

每个 adapter 都以完整 Harness Space build case 覆盖：

- portable common Skills 和该平台 full-capability Skill 安装；
- workspace rule；
- 每一种已支持 `.harness-agents/<agent>/` 输入；
- gated/unsupported surface 的明确拒绝；
- Space-level 与 Skill-level artifact 合并；
- unknown directory；
- semantic key 冲突；
- Human-owned target 冲突；
- config semantic merge；
- hook/MCP secret lint；
- clean 与重复 build；
- Windows path normalization。

Codex 额外覆盖：

- `SessionStart` 和 `SubagentStart` workspace context hook；
- compact 后 context 恢复；
- Windows `commandWindows`；
- project config discovery；
- `.codex/rules` command policy；
- Human-owned `AGENTS.md` byte-for-byte 不变。

这些都是通过完整 build 和最终文件/客户端行为测试，不允许直接构造 adapter class 调用 render。

### 10.4 Ownership 与生命周期

- 首次 build；
- 无变化重复 build；
- source 变化后的受控更新；
- 人工修改 managed file 后冲突；
- 人工文件占用计划目标；
- lock 缺失、损坏、旧 schema、builder 版本变化；
- managed file 被删除或类型改变；
- clean 只删除 owned artifact；
- build/clean 并发锁竞争；
- 失败后再次 build 可恢复。

### 10.5 Transaction 与 crash recovery

- 规划阶段失败时零写入；
- staging 失败时零最终写入；
- commit 中途存在完整 transaction journal 时恢复；
- rollback 中断后再次调用恢复；
- 不完整 journal 触发 `HB016`；
- recovery 目标被人工修改时触发 `HB017` 且不覆盖人工内容；
- 成功后无活动 transaction 残留。

确定性 recovery case 可以把协议允许的中断 journal 和 staging tree 作为完整输入 fixture 预置，再执行真实 CLI。另设 native crash case：启动大 fixture，观察 journal checkpoint 后由测试进程发送 `SIGKILL` 或 Windows `TerminateProcess`，随后再次执行 CLI 验证恢复。后者用于 nightly 压力门禁，不代替确定性 recovery fixtures。

### 10.6 Harness Space command

- Python command probe 收到精确 argv；
- cwd 固定为 Harness Space root；
- 环境变量白名单和覆盖语义；
- stdout、stderr 和 exit code 进入 report；
- 非零退出；
- executable 不存在；
- 路径和参数包含 shell metacharacter 时不发生 shell expansion；
- command 产生 runtime 文件时 ownership 归属符合协议；
- command 超时和外部终止的语义。

### 10.7 Security 与 portability

- `..`、absolute target、symlink escape；
- symlink loop；
- Windows junction/reparse point；
- Windows drive、UNC 和 case-insensitive collision；
- macOS/Linux case-sensitive 差异；
- reserved device name 和非法文件名；
- secret 出现在 manifest、env、hook、MCP config 时的 lint/redaction；
- executable bit；
- UTF-8 BOM、CRLF/LF 和 Unicode normalization；
- 超长路径及深层 Skill tree。

平台文件系统行为必须在对应原生 OS runner 上验收，不能只靠字符串模拟 Windows 或 macOS。

### 10.8 Diagnostics

Harness Space 协议定义的每个 stable diagnostic code 至少对应一个完整失败 E2E。`COVERAGE.md` 建立 requirement/diagnostic 到 case id 的映射；没有 E2E case 的诊断码不能进入 stable contract。

---

## 11. 真实客户端 E2E

### 11.1 两阶段执行

每个 E1 case 都执行：

```text
阶段 A：harnessbuilder.py build 完整 sandbox
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

Codex E2 使用：

```text
agent: codex
model: gpt-5.4-mini
```

这是 suite-level default，不应在每个 case 中重复硬编码。选择它的理由是与 Rounditer 的 live proof 对齐，并适合频繁、短小的兼容性 sentinel；OpenAI 当前将其定位为面向 coding、computer use 和 subagents 的高吞吐 mini 模型。模型标识以官方页面为准：<https://developers.openai.com/api/docs/models/gpt-5.4-mini>。

Runner 的优先级为：

```text
CLI --model
> suite profile
> gpt-5.4-mini
```

CI 默认不得通过环境变量静默改模型。确需覆盖时必须使用显式 `--model`，并把 requested model、effective model、override source、Codex client version 和测试结果写入 `e2e-report.json`。无法确认客户端实际使用的模型时，case 不能标记 `live-consumed`。

默认使用 rolling alias `gpt-5.4-mini`，以便和 Rounditer 保持同一个运行基线；若 release reproducibility 需要固定 snapshot，可在 release job 显式传入 snapshot model，但报告必须同时保留 suite default 和实际值，不得悄悄替换。

Runner 最终调用的形态应等价于：

```text
codex exec \
  --model gpt-5.4-mini \
  --ephemeral \
  --ignore-user-config \
  --sandbox workspace-write \
  --json \
  --cd <space-sandbox> \
  <sentinel-prompt>
```

Python runner 仍以 argv list 和 `shell=False` 启动它。不得使用 `--dangerously-bypass-approvals-and-sandbox`。若自动化必须验证 project hook，可仅在 disposable sandbox 中使用 `--dangerously-bypass-hook-trust`，且先核对待执行 hook 的 path 和 digest 都属于本 case 的 expected managed tree。

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
python3 tests/e2e/run.py --tier offline --case offline.transaction.recover_commit
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --model gpt-5.4-mini
python3 tests/e2e/run.py --tier offline --jobs 8
```

Runner 只使用 Python 标准库。并行执行可使用 `concurrent.futures.ProcessPoolExecutor`，每个 case 仍有独立 sandbox；标记为 serial 的并发锁或真实客户端 case 单独运行。

### 13.2 Runner 输出

人类输出保持简洁：

```text
PASS offline.build.minimal_all_agents  0.42s
FAIL offline.ownership.human_conflict   0.11s
SKIP client.cursor.discovery            client-not-installed
```

同时生成结构化 `e2e-report.json`，至少包含：

- suite schema/version；
- release artifact path 和 SHA256；
- Python/OS 信息；
- case id、tier、duration、status；
- HarnessBuilder exit/report；
- Agent client version、requested/effective model 和 override source；
- skip/failure reason；
- artifact capture path。

Release report 必须证明所有 case 执行的是同一个 SHA256 的 `harnessbuilder.py`。

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
- transaction journal；
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
- 可选 Codex/`gpt-5.4-mini` E2 live sentinel；
- 客户端版本变化和兼容矩阵报告。

### 14.3 Release candidate

1. 冻结一个 `harnessbuilder.py` SHA256；
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

这里的 mutation 指对 Harness Space、Provider、managed artifact、lock 或 transaction 状态做外部改变后重新执行完整 CLI，不是调用内部函数做微型测试。

---

## 16. 从现有 Builder 测试迁移

当前 Node/TypeScript Builder 的测试不继续扩建，逐步迁成 Python E2E：

| 现有内容 | 新位置 | 迁移方式 |
| --- | --- | --- |
| `tests/integration/builtin-builder.mjs` | `cases/offline/build/cursor_legacy_parity/` | 转成完整 `harness-space.json`、workspace、Provider 和 Cursor 产物 golden |
| `tests/integration/command-runner.mjs` | `cases/offline/command/` | Python command probe 真进程覆盖 argv/cwd/env/stdout/stderr/exit |
| `tests/fixtures/builtin/*` | `cases/offline/**/input/` | 转成标准 `skills/foo/SKILL.md` 与 `.harness-agents/` |
| `tests/fixtures/command/*` | `cases/offline/command/**/input/` | 删除 MJS fixture，改用 Python probe |

迁移期间允许旧 Builder 自己的 Node integration test 暂时存在，但 HarnessBuilder 的任何新行为只能进入 Python E2E suite。HarnessBuilder 达到 Cursor parity 后，旧 suite 作为旧实现测试随旧 Builder 一起退役。

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
- semantic conflict 和 Human-owned target conflict。

### Step 3：ownership/transaction/security

- managed artifact mutation；
- stale/corrupt lock；
- pre-seeded recovery journal；
- symlink/path escape；
- command argv/no-shell。

### Step 4：真实客户端

- 先接入 Codex E1；
- 每确认一个平台稳定入口，就为其建立固定 runner 和 capability report；
- 最后增加最小 E2 sentinel。

首版发布不能只完成 happy path。至少 E0 全矩阵、四 adapter 投影、ownership、clean、transaction recovery 和 security 边界通过后，才具备替代现有 Builder 的条件。

---

## 18. 验收标准

测试架构完成的定义是：

1. 所有测试执行代码均为 Python；
2. 没有 HarnessBuilder unit suite，也没有 adapter direct-call test；
3. 每个 case 都通过 subprocess 执行待发布的 `harnessbuilder.py`；
4. PR 可在无 Agent、无账号、无网络环境完成全部 E0；
5. 四 Agent 都有完整 Harness Space projection case 和真实客户端 E1 入口；
6. build、重复 build、失败回滚、恢复、clean 和再次 build 都有 E2E；
7. Human-owned 输入、ownership、provenance、secret redaction 和路径边界有负向验证；
8. Linux、Windows、macOS 的平台行为在原生 runner 上验证；
9. release report 能追溯到唯一 `harnessbuilder.py` SHA256；
10. 任何 stable diagnostic 和 supported adapter capability 都能映射到至少一个 E2E case。
