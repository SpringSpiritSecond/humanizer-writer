# humanizer-writer

一套已经调好的中文去 AI 味写稿方法，适用于任何中文文案。

## 先看这个

**[handoff/使用手册.md](handoff/使用手册.md)**：讲 brief 怎么写、写稿规则、怎么挑稿，十分钟能看完。

一句话：**brief 只写场景和事实，不写风格要求，也不写不能说的话；一次写 3 份，挑一份。** 写稿模型推荐 Gemini 4 Argon，比较下来效果最好。

## 仓库里现成的工具（可选）

用得上就用：

| 工具 | 用途 |
|---|---|
| [handoff/网页聊天提示词.md](handoff/网页聊天提示词.md) | 一段写好的提示词，贴进任何 AI 聊天里就能用 |
| [handoff/skill/humanizer-writer](handoff/skill/humanizer-writer/) | 给 AI 助手（比如 Claude Code）用的 skill；在这个仓库里打开 AI 助手时会自动读到 |
| [writer/](writer/README.md) | 命令行：`python -m writer run --brief 你的brief.json`，写 3 份并自动检查。默认调用 Gemini，也可以换成其他模型。需要你自己的 API key（环境变量 `RELAYROUTER_BASE_URL`、`RELAYROUTER_API_KEY`），以及 Python 3.11 及以上 |

---

维护者（调模型、改规则、做评测）看 [docs/维护说明.md](docs/维护说明.md)。
