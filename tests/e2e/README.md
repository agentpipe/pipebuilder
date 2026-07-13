# HarnessBuilder E2E

这里是对发布文件 `harnessbuilder.py` 的黑盒验收。测试 helper 不 import production；每个 case 都在独立临时 Harness Space 中以 argv list、`shell=False` 启动同一个 release artifact。

运行方式：

```bash
python3 tests/e2e/run.py --tier offline --jobs 4
python3 tests/e2e/run.py --tier client --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --require
python3 tests/e2e/run.py --tier live --agent codex --model <model-id> --require
python3 tests/e2e/run.py --tier all --agent codex --require
```

`offline` 是无网络门禁；`client` 调用真实客户端但不请求模型；`live` 发起真实 Codex 模型会话。未传 `--model` 时，live 使用已安装 Codex 的默认模型，避免把可能过期的模型名固化在测试中。

Runner 生成 `e2e-report.json`，记录 release SHA256、case metadata、实际 argv、cwd、stdout/stderr 和耗时。失败 sandbox 会复制到 `.artifacts/<case-id>/`。两者都被 Git ignore。

静态 fixture 和人工审查 golden 位于 `fixtures/`。覆盖映射与仍需原生 runner 验证的边界见 [COVERAGE.md](COVERAGE.md)。
