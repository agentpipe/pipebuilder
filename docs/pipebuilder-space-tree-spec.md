# PipeBuilder General PipeSpace Children Tree Specification

Status: implemented

Schema: `pipespace-tree.v1`

Builder: `0.5.0`

Date: 2026-07-14

This document defines the discovery, build, verification, cleanup, concurrency, and failure-recovery contract for any ordinary PipeSpace that physically contains N explicitly declared child PipeSpaces within its own directory. It is a general orchestration layer above `pipespace.v1`; it neither changes the single-Space specification followed by each member nor defines Leader, Worker, or any other product role.

## 1. Topology and Ownership

```text
root-space/                          # ordinary PipeSpace + PipeSpace Tree root
├── pipespace.json
├── root-space.code-workspace
├── pipespace-tree.json
├── .pipebuilder/
│   ├── lock.json                    # single-Space ownership for the root PipeSpace
│   └── tree-lock.json               # aggregate receipt for the entire Tree
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

The Tree root is itself an ordinary PipeSpace; no additional container PipeSpace is introduced. Directory containment allows an Agent operating from the root to discover and manage the children naturally, and allows a child working directory to inherit root instructions according to the Agent's native ancestor-resolution rules. This is not equivalent to asymmetric OS permission isolation; strict write boundaries must still be enforced by a sandbox, broker, or ACL.

Each member independently owns its manifest, workspace file, Provider resolution, generated artifacts, `.pipebuilder/lock.json`, and `build.lock`. The Tree receipt only aggregates and validates these ownership locks; it does not take ownership of child files.

The existing member kind `parent` in the implementation and receipt denotes only the structural position of "the root of this Tree operation." It is not a special PipeSpace type and carries no product role.

## 2. Tree Manifest

The Tree root must contain:

```json
{
  "schema": "pipespace-tree.v1",
  "children": [
    {"path": "children/child-01", "expectName": "child-01"},
    {"path": "children/child-02", "expectName": "child-02"}
  ]
}
```

At the top level, only `schema` and `children` are accepted; `children` must be a non-empty array. Each item accepts only:

- `path`: a POSIX path relative to the Tree root;
- `expectName`: the expected child `pipespace.json.name`.

v1 does not scan directories; declaration order is build order. Every component of `path` must already exist, must be an ordinary directory rather than a symlink, and must remain within the Tree root after canonicalization. Absolute paths, drive-qualified paths, `..`, backslashes, control characters, Windows reserved names, and paths beginning with `.git`, `.pipebuilder`, or an Agent-managed root are rejected.

All child paths, realpaths, and logical names must be unique under portability comparison, and a child name must not equal the root name. Children must not contain one another, and a child must not declare another `pipespace-tree.json`.

Any ordinary PipeSpace can serve as a Tree root when used independently, but a single v1 Tree supports only one level of direct children. A child that has its own children would form a recursive Tree, which the current schema and implementation do not support.

## 3. CLI

```bash
python3 pipebuilder.py check-tree [ROOT] [--offline] [--format text|json]
python3 pipebuilder.py explain-tree [ROOT] [--offline] [--format text|json]
python3 pipebuilder.py build-tree [ROOT] [--offline] [--dry-run] [--format text|json]
python3 pipebuilder.py verify-tree [ROOT] [--format text|json]
python3 pipebuilder.py clean-tree [ROOT] [--format text|json]
```

`check-tree`, `explain-tree`, and `build-tree --dry-run` produce complete plans for the root and all children, but do not execute Provider post commands or write any Tree or member state. The ordinary `build`, `check`, `explain`, and `clean` commands retain single-Space semantics and never recurse merely because a Tree manifest exists.

## 4. `build-tree`

The build sequence for the entire Tree is fixed:

1. Acquire the Tree root's `.pipebuilder/tree-build.lock`.
2. Acquire the independent `build.lock` for the root and every child in canonical root-path order.
3. Verify that any existing Tree receipt matches the current manifest and member order exactly.
4. Complete the plan for the entire Tree before writing to any member, and verify consistent resolution of identical Provider identities.
5. Write `tree-journal.json`.
6. Re-plan each member in root → declared-children order and compare it with the initial plan fingerprint.
7. Run the ordinary build for that member, followed by its Provider post commands.
8. Verify every member's manifest, workspace file, ownership lock, and managed artifacts.
9. Finally, write `tree-lock.json`, delete the journal, and release all locks.

If an earlier member's post command changes the inputs of a child that has not yet been built, the fresh plan is rejected with `PB017`. If multiple members declare the same Folder Provider or Git Provider identity, they must resolve to the same directory digest or the same Git commit and digest.

## 5. Receipt and Verification

A successful build produces `.pipebuilder/tree-lock.json` with schema `pipespace-tree-lock.v1`. It records at least:

- the Builder version and release-script digest;
- the root PipeSpace name, Tree manifest path, and digest;
- each member's kind, path, and name in topology order;
- the digest of each member's `.pipebuilder/lock.json`.

`verify-tree` requires the receipt to exist. It verifies that the Tree manifest is unchanged, member order and identities are unchanged, each member's inputs match its ownership lock, and the contents and executable bit of every managed artifact have not drifted. It then compares the member lock digests.

v1 fails closed on member additions, removals, and reordering: when a receipt already exists, restore the original Tree manifest and run `clean-tree` before changing membership and running `build-tree` again.

## 6. `clean-tree`

`clean-tree` acquires the same whole-Tree locks as build and preflights every member before deleting any file. Only after the entire Tree passes preflight does it invoke single-Space clean in reverse declared-child order → root. It deletes only targets that each member's valid ownership lock proves are Builder-owned; it does not delete child roots, manifests, workspace files, Provider sources, or the Tree manifest.

## 7. Partial Failure and Recovery

Tree operations guarantee atomic replacement only for each managed file; they do not promise a cross-PipeSpace transaction or rollback. If a re-plan, Builder operation, post command, or final validation fails after writes have begun:

- no successful Tree receipt is written; any existing old receipt is removed before changes begin;
- `.pipebuilder/tree-journal.json` is retained;
- the journal `status` is `partial`, with phases such as planned, applied, post, and clean recorded for each member;
- successfully completed members retain their valid ownership locks;
- after correcting the root cause, rerun the complete `build-tree` to converge from the current sources and replace the journal.

A hard process exit can leave both Tree and member operation locks behind. As with a single Space, the Builder reports active or stale locks with `PB013`/`PB014`; a human must confirm that the process is no longer running before deleting a stale operation lock.

## 8. Diagnostics and v1 Boundaries

- `PB016`: Provider post-command working-directory, startup, or exit failure;
- `PB017`: Tree schema, path, identity, receipt, member-state, or cross-member consistency failure;
- existing PB001–PB015 diagnostics from single-member plan, build, or clean operations pass through unchanged.

v1 explicitly excludes recursive Trees, automatic directory scanning, dynamic child creation, cross-machine transactions, Tree-level permission brokers, and root-only OS ACLs. These capabilities require a separate schema and version; they must not be approximated by relaxing v1.
