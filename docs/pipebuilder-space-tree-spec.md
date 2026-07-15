# PipeBuilder 通用 PipeSpace children Tree 协议

状态：implemented

Schema：`pipespace-tree.v1`

Builder：`0.4.0`

日期：2026-07-14

本文定义任意普通 PipeSpace 在自身目录内物理包含 N 个显式 child PipeSpaces 时的发现、构建、验证、
清理、并发和故障恢复契约。它是 `pipespace.v1` 之上的通用编排层，不改变成员的单 Space
协议，也不定义 Leader、Worker 或其他产品 role。

## 1. 拓扑与所有权

```text
root-space/                          # 普通 PipeSpace + PipeSpace Tree root
├── pipespace.json
├── root-space.code-workspace
├── pipespace-tree.json
├── .pipebuilder/
│   ├── lock.json                    # root PipeSpace 的单 Space ownership
│   └── tree-lock.json               # 全树聚合 receipt
└── children/
    ├── child-01/
    │   ├── pipespace.json
    │   ├── child-01.code-workspace
    │   └── .pipebuilder/lock.json
    └── child-02/
        ├── pipespace.json
        ├── child-02.code-workspace
        └── .pipebuilder/lock.json
```

Tree root 本身就是一个普通 PipeSpace，不增加额外容器 PipeSpace。目录包含关系使从 root 工作的 Agent
能自然发现和管理 children，也让 child cwd 按 Agent 原生祖先规则继承 root 指令。它不等同于
非对称 OS 权限隔离；严格写边界仍由 sandbox、broker 或 ACL 提供。

每个成员独立拥有自己的 manifest、workspace、Provider resolution、generated artifacts、
`.pipebuilder/lock.json` 与 `build.lock`。Tree receipt 只聚合和校验这些 ownership lock，
不接管 child 文件。

实现和 receipt 中现有的 member kind `parent` 只表示“本次 Tree 操作的 root”这一结构位置，
不是特殊 PipeSpace 类型，也不承载任何产品 role。

## 2. Tree manifest

Tree root 必须包含：

```json
{
  "schema": "pipespace-tree.v1",
  "children": [
    {"path": "children/child-01", "expectName": "child-01"},
    {"path": "children/child-02", "expectName": "child-02"}
  ]
}
```

顶层严格只接受 `schema` 与 `children`；`children` 必须是非空数组。每项严格只接受：

- `path`：相对 Tree root 的 POSIX 路径；
- `expectName`：预期的 child `pipespace.json.name`。

v1 不扫描目录，声明顺序就是构建顺序。`path` 的每个组件必须已经存在、是普通目录、不含
symlink，并在 canonicalize 后仍位于 Tree root 内。绝对路径、盘符、`..`、反斜线、控制字符、
Windows 保留名以及以 `.git`、`.pipebuilder` 或 Agent managed root 开头的路径均拒绝。

所有 child path、realpath 和 logical name 在 portability comparison 下必须唯一，child name 不能
等于 root name。children 彼此不得包含；child 不得再声明 `pipespace-tree.json`。

任意普通 PipeSpace 均可在独立使用时成为 Tree root；但 v1 的同一棵 Tree 只支持一层 direct
children。child 继续拥有 children 属于递归 Tree，当前 schema/实现未支持。

## 3. CLI

```bash
python3 pipebuilder.py check-tree [ROOT] [--offline] [--format text|json]
python3 pipebuilder.py explain-tree [ROOT] [--offline] [--format text|json]
python3 pipebuilder.py build-tree [ROOT] [--offline] [--dry-run] [--format text|json]
python3 pipebuilder.py verify-tree [ROOT] [--format text|json]
python3 pipebuilder.py clean-tree [ROOT] [--format text|json]
```

`check-tree`、`explain-tree` 和 `build-tree --dry-run` 对 root 与全部 children 做完整 plan，但不执行
Provider post command，也不写任何 Tree/member 状态。普通 `build`、`check`、`explain` 和
`clean` 保持单 Space 语义，绝不因 Tree manifest 存在而递归。

## 4. `build-tree`

整树构建顺序固定为：

1. 获取 Tree root 的 `.pipebuilder/tree-build.lock`；
2. 按 canonical root 顺序获取 root 与所有 children 的独立 `build.lock`；
3. 校验已有 Tree receipt 与当前 manifest/member 顺序完全一致；
4. 在任何成员写入前完成全树 plan，并校验同一 Provider identity 的解析一致性；
5. 写入 `tree-journal.json`；
6. 按 root → children 声明顺序逐成员重新 plan，对比初始 plan fingerprint；
7. 对该成员执行普通 build，再执行其 Provider post commands；
8. 验证全部成员的 manifest、workspace、ownership lock 和 managed artifact；
9. 最后写入 `tree-lock.json`，删除 journal，释放全部锁。

较早成员的 post command 如果改变尚未构建的 child 输入，fresh plan 会以 `PB017` 拒绝。若多个
成员声明同一 folder/Git Provider identity，它们必须解析到同一 directory digest 或 Git
commit+digest。

## 5. Receipt 与 verify

成功构建生成 `.pipebuilder/tree-lock.json`，schema 为
`pipespace-tree-lock.v1`，至少记录：

- Builder version 与发布脚本 digest；
- root PipeSpace name、Tree manifest path 与 digest；
- 按拓扑顺序记录的 member kind/path/name；
- 每个成员 `.pipebuilder/lock.json` 的 digest。

`verify-tree` 要求 receipt 存在，并验证 Tree manifest 未变、成员顺序与 identity 未变、每个成员
输入与 ownership lock 匹配、每个 managed artifact 的内容和 executable bit 未漂移，最后比较
member lock digest。

v1 对成员增删和重排采取 fail-closed：已有 receipt 时，必须先恢复原 Tree manifest 并
`clean-tree`，再修改 membership 后重新 `build-tree`。

## 6. `clean-tree`

`clean-tree` 获取与 build 相同的整树锁，并在删除任何文件前 preflight 所有成员。只有全树
preflight 成功后，才按 children 声明逆序 → root 调用单 Space clean。它只删除各成员有效
ownership lock 证明属于 Builder 的 target，不删除 child root、manifest、workspace、Provider
source 或 Tree manifest。

## 7. 部分失败与恢复

Tree 操作只保证每个 managed 文件 atomic replace，不承诺跨 PipeSpace transaction/rollback。
开始写入后发生 replan、Builder、post command 或最终验收失败时：

- 不写成功的 Tree receipt；已存在的旧 receipt 在变更开始前移除；
- 保留 `.pipebuilder/tree-journal.json`；
- journal `status` 为 `partial`，每个成员记录 planned/applied/post/clean 等阶段；
- 已成功成员保留自己的有效 ownership lock；
- 修正根因后重新执行完整 `build-tree`，以当前 source 收敛并替换 journal。

进程硬退出可能同时留下 Tree/member operation lock。与单 Space 一致，Builder 以
`PB013`/`PB014` 报告 active/stale lock，Human 确认进程消失后再删除 stale operation lock。

## 8. Diagnostics 与 v1 边界

- `PB016`：Provider post command cwd/启动/退出失败；
- `PB017`：Tree schema、路径、identity、receipt、member state 或跨成员一致性失败；
- 单成员 plan/build/clean 的既有 PB001–PB015 仍原样透出。

v1 明确不包含递归 Tree、自动目录扫描、动态 child 创建、跨机器 transaction、Tree 级权限
broker 或 root-only OS ACL。这些能力需要独立 schema/version，不能通过放宽 v1 猜测实现。
