# humanizer-writer

[「去 AI 味」课题背景与首轮调研](docs/去AI味-课题背景与首轮调研.md)

## 工作流骨架

去 AI 味流水线的 runner 和硬闸门，说明见 [pipeline/README.md](pipeline/README.md)。

```bash
python -m pipeline run --config configs/口播-baseline-none.json --brief pipeline/examples/briefs/vo-example-01.json --text-file pipeline/examples/drafts/vo-example-01_通过.txt
```

## 盲审工作台

本地运行的台词 / 口播盲审工具，说明见 [workbench/README.md](workbench/README.md)。

```bash
python -m workbench seed
python -m workbench serve
```

评审页 http://127.0.0.1:8765/ ，管理页 http://127.0.0.1:8765/admin 。测试：`python -m pytest`。

## 直接用

当前推荐的写稿工作流：[writer/README.md](writer/README.md)，依据见 [docs/工作流-当前推荐.md](docs/工作流-当前推荐.md)。
