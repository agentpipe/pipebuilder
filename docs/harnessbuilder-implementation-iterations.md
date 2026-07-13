# HarnessBuilder v0.1.0 落地与 20 轮迭代记录

日期：2026-07-13
验证解释器：CPython 3.11.9（隔离构建，仅用于测试）
第 20 轮结束结果：40/40 passed
第一次交付前 hardening：43/43 passed
全面 E2E 重写后：E0 57/57、Codex E1 5/5、Codex E2 1/1

当前主机默认 `python3` 为 3.6.8，低于项目明确要求的 Python 3.11。为保持“只依赖 3.11 标准库 `tomllib`”的发布约束，本次在 `/tmp` 隔离构建 CPython 3.11.9 运行测试，没有向仓库或系统 Python 安装依赖。

| 轮次 | 新增验证或改进 | 结果 |
| --- | --- | --- |
| 1 | 完成单文件 CLI、四 Adapter、lock/clean 与初始 21 个黑盒 E2E；识别默认 Python 版本不满足要求 | 隔离 3.11 下 21/21 passed |
| 2 | manifest 重复 Agent、workspace 绝对路径与重复 realpath | 23/23 passed |
| 3 | 缺失 Provider 与缺失显式 Skill 的稳定诊断码 | 24/24 passed |
| 4 | common package 的 binary、隐藏文件、executable bit、`.DS_Store` 排除和 source 不可变 | 25/25 passed |
| 5 | 删除 Agent 后只清理该 Adapter 的 owned targets | 26/26 passed |
| 6 | 反选 Skill 后清理安装目录和 Agent artifact | 27/27 passed |
| 7 | JSON handler additive merge 与相同定义去重 | 28/28 passed |
| 8 | Codex TOML quoted key/array 确定性 render 后可由 `tomllib` 往返解析 | 29/29 passed |
| 9 | lock 中每个 artifact digest/provenance 与实际 target 对应 | 30/30 passed |
| 10 | clean 幂等；损坏 lock 零副作用失败 | 32/32 passed |
| 11 | source symlink 和 target-parent symlink 逃逸；修正一个未实际命中 target 的错误测试前提 | 33/33 passed |
| 12 | semantic conflict 必须在任何写入前失败并释放 operation lock | 33/33 passed |
| 13 | owned target 从 file 漂移为 directory 的故障注入 | 发现并修复 build preflight bug，34/34 passed |
| 14 | apply 中断时旧 lock 不前移，下一次 build 完整收敛 | 35/35 passed |
| 15 | 进程硬崩溃留下 stale `build.lock`，Human 删除后恢复 | 36/36 passed |
| 16 | clean 对所有 target kind 先 preflight 再删除 | 发现并修复 partial-clean bug，37/37 passed |
| 17 | secret literal 拒绝与环境变量 secret reference 允许 | 38/38 passed |
| 18 | 大小写不同的 target portability collision | 39/39 passed |
| 19 | runner `--case` 拼错导致 0 tests 假绿 | 发现并修复 runner bug；无匹配返回 2，单 case passed |
| 20 | 未选择 Agent 的 Space/Skill source 不读取；最终 py_compile + 全量回归 | 40/40 passed |

测试均通过 `tests/e2e/support/` 以 `shell=False` 子进程执行最终 `harnessbuilder.py`。轮次 13、14、15 以及后续真实并发 case 使用受测脚本内仅供 E2E 的 `HARNESSBUILDER_TEST_*` 故障/时序注入变量验证 apply failure、crash 与锁竞争；正常环境未设置时不影响构建路径。

后续全面重写把测试拆成 case/fixture/golden/support，并补齐结构化报告、失败制品、并行安全 metadata 和 `COVERAGE.md`。本机 Codex CLI 0.144.1 已完成 E1 真实 prompt assembly/config/execpolicy/hook schema 验证，并用一次真实模型请求同时通过 generated AGENTS、Skill 与 SessionStart hook 哨兵。其他三个平台仍只声称 E0 projection 覆盖。

20 轮完成后的交付前 hardening 继续增加了 3 个 case：Codex machine/user-level key 拒绝、Cursor 跨目录 slash command semantic collision、Claude Code legacy command migration warning。它们不计入上述 20 轮循环，最终全量为 43/43。
