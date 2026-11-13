# humanizer-writer

一套已经调好的中文去 AI 味写稿方法，适用于任何中文文案。

## 工作流

1. **写 brief**：只写场景和事实，包括谁对谁说、在什么场合、发生了什么、要讲哪些事；不写“要短”“口语一点”这类要求。不能出现的说法另外列一份“只用来检查”的清单，这份不交给 AI。
2. **让 AI 写 3 份**：把 brief 和写稿规则一起交给 AI。写稿模型推荐 Gemini 4 Argon。
3. **检查**：对照清单，看有没有写出不能出现的说法；核对数字和专名；看有没有 brief 里没有的事实、安排或承诺。
4. **挑一份**：每句话都要能对上这个场景。挑中的那份可以手改；3 份都不行，就回到第 1 步改 brief。

详细说明和写稿规则见 **[handoff/使用手册.md](handoff/使用手册.md)**，十分钟能看完。

## 仓库里现成的工具

用得上就用：

| 工具 | 用途 |
|---|---|
| [handoff/网页聊天提示词.md](handoff/网页聊天提示词.md) | 第 2 步：写稿规则已经写在里面，贴进 AI 聊天就能用 |
| [handoff/skill/humanizer-writer](handoff/skill/humanizer-writer/) | 在 AI 助手（比如 Claude Code）里帮你做第 1–3 步；在这个仓库里打开 AI 助手时会自动读到 |
| [writer/](writer/README.md) | 自动做第 2、3 步：`python -m writer run --brief 你的brief.json`，写 3 份并出检查报告。默认调用 Gemini，也可以换成其他模型。需要你自己的 API key（环境变量 `RELAYROUTER_BASE_URL`、`RELAYROUTER_API_KEY`），以及 Python 3.11 及以上 |

---

维护者（调模型、改规则、做评测）看 [docs/维护说明.md](docs/维护说明.md)。
