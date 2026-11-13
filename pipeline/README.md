# pipeline：去 AI 味工作流的骨架与硬闸门

设计见 `docs/工作流编排.md`，接口约定是那份文档的第 3 节。只用 Python 标准库。

## 跑一份 brief

```bash
python -m pipeline run --config configs/口播-baseline-none.json --brief pipeline/examples/briefs/vo-example-01.json --text-file pipeline/examples/drafts/vo-example-01_通过.txt --out pipeline/data/runs/vo.json
python -m pipeline export pipeline/data/runs/vo.json --out pipeline/data/runs/for_workbench.json
python -m workbench import pipeline/data/runs/for_workbench.json
```

- 给了 `--text-file`（可以给多次）就不跑 S1，拿现成稿件过闸门；`--gates-only` 再跳过 S3、G4，完全不碰模型适配器。
- 不给 `--text-file` 时由 S1 生成。
- 运行摘要打印到标准错误，完整报告写到 `--out`。brief 被 S0 退回时退出码是 3，配置错误是 2。
- `export` 只导第一层存活的稿件；`--exclude-review` 再去掉要人工复核的。

## 目录

| 路径 | 内容 |
|---|---|
| `runner.py` | 阶段顺序 S0 → S1 → G0 → S2 → S3 → G1 → G2 → G3 → G4 → G5、轮次控制、运行报告 |
| `config.py` | 读 `configs/<名字>.json`，按点分路径加载阶段，解析槽位里的 skill |
| `contract.py` | 阶段结果的约定和校验 |
| `gates/brief.py` | S0：按 `eval/briefs/<线>/_template.json` 检查必填字段、占位文字 |
| `gates/format.py` | G0：长度/时长、品牌词和 CTA、锁定台词、禁用词 |
| `gates/compliance.py` | G1：《广告法》第九条通用极限词 + 执法指南第六条豁免分流 |
| `gates/fidelity.py` | G2：逐字字段、新增数字和承诺、锁定台词和人名道具；beat 占位 |
| `adapters/` | S1 / S3 / G4 的模型适配器接口、测试用假适配器、OpenAI 兼容的真实模型适配器 |
| `data/广告法极限词.json` | G1 词典。**行业条款待法务补** |
| `data/承诺词.json` | G2 用的承诺类说法 |
| `examples/` | 示例 brief 和稿件（全部虚构） |
| `export.py` | 导出成 `workbench import` 的 JSON |

## 状态

每份稿件的 `status`：

- `passed`：全部放行。
- `eliminated`：被硬闸门拦下（G0 或 G1 fail）。
- `human`：要人看，原因写在 `needs_review`，包括 G1 豁免区或模糊区、改写轮数用完、软闸门转人工。

`layer1.survived` 是评测的第一层淘汰：G0–G2 有硬拦，或 G2 的问题到轮数用完都没修好，就是 false。

## 轮次

第 0 轮的 S3 只改 S2 的命中，没有命中就原样放行，不调用模型；改了就按新文本再跑一次 S2（只出报告）。G2 或 G3 打回 S3 时轮次加 1，S3 只改打回的命中，然后从 G1 重跑。轮次到了槽位 D 的 `max_rounds`，或者配置里没有 S3，就转人工。G4 建议重写时，这一期不自动回流，直接转人工。

## 接 detect/

`detect/` 合进来后，在配置的 `stages` 里填 `"S2": "detect.stages:s2"`、`"G3": "detect.stages:g3"`（以 detect 的实现为准）即可。runner 会校验返回值是否符合约定，不符合会报出是哪个阶段。

## 接真实模型

`adapters/openai_compat.py` 的 `OpenAICompatAdapter` 走 OpenAI 兼容的 `/chat/completions`，OpenRouter、RelayRouter、DeepSeek、Kimi、GLM 都能用。配置里只写**环境变量名**，不写密钥：

```json
"generator": {"adapter": "pipeline.adapters.openai_compat:OpenAICompatAdapter",
              "model": "anthropic/claude-opus-5.5", "vendor": "anthropic",
              "params": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
                         "temperature": 1.0, "max_tokens": 1500, "reasoning_effort": "low"}}
```

- 接口地址也可以写成环境变量名：`"base_url_env": "RELAYROUTER_BASE_URL"`。
- skill 正文（SKILL.md）放进 system prompt：S1 用槽位 A，S3 用槽位 B。槽位 C 的改动范围写在 `slots.C.scope` 里，取值为 `in-place` / `bounded` / `structural`。`references/` 下的附属文件不会自动带上。
- 每次调用的 token 用量记在报告里各阶段的 `metrics.usage`。OpenRouter 还会返回 `cost`。
- 只做了 S1、S3；G4 的真实裁判还没接。
