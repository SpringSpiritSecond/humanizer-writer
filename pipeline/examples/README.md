# pipeline 示例

这里的 brief 和稿件全部是为演示 pipeline 临时编写的示例，人物、品牌、产品都是虚构的，不是任何真实作品，也没有调用任何模型。brief 里都带 `"is_example": true`，导出到工作台后也会标成示例。

| 文件 | 用来演示 |
|---|---|
| `briefs/vo-example-01.json` | 口播 brief |
| `drafts/vo-example-01_通过.txt` | 全部闸门放行 |
| `drafts/vo-example-01_合规不过.txt` | G1 拦下（最佳、第一）；G1 硬拦后这一份结束，后面的 G2 不再跑 |
| `drafts/vo-example-01_保真不过.txt` | G2 发现“保温 6 小时”被改成 8 小时；配置里的 S3 是不改稿的假适配器，轮数用完转人工、第一层淘汰 |
| `briefs/dlg-example-01.json` | 台词 brief |
| `drafts/dlg-example-01_通过.txt` | 全部闸门放行 |
| `drafts/dlg-example-01_锁定台词被改.txt` | G0 拦下（锁定台词被改） |

```bash
python -m pipeline run --config configs/口播-baseline-none.json --brief pipeline/examples/briefs/vo-example-01.json --text-file pipeline/examples/drafts/vo-example-01_通过.txt --text-file pipeline/examples/drafts/vo-example-01_合规不过.txt --text-file pipeline/examples/drafts/vo-example-01_保真不过.txt --out pipeline/data/runs/vo-example-01.json
python -m pipeline export pipeline/data/runs/vo-example-01.json --out pipeline/data/runs/for_workbench.json
python -m workbench --db pipeline/data/runs/demo.sqlite3 import pipeline/data/runs/for_workbench.json
```
