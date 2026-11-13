# humanizer-writer

一套已经调好的中文去 AI 味写稿工作流，台词、科普、口播、带练口令、通知、文章都能用。

## 先看这个

**[handoff/使用手册.md](handoff/使用手册.md)**：怎么写 brief、怎么用、怎么挑稿，十分钟看完。

一句话：**brief 只写场景和事实，不写风格要求，也不写不能说的话；用 Gemini 4 Argon 一次写 3 份，你来挑。**

## 三种用法

| 你是 | 怎么用 |
|---|---|
| 只想写稿，不碰代码 | 打开 Gemini 网页版，把 [handoff/网页聊天提示词.md](handoff/网页聊天提示词.md) 里的内容复制进去，填好就能用 |
| 用 Claude Code 或其他 AI 助手 | 在这个仓库里打开 Claude Code，直接说“帮我写一段……”；或者把 [handoff/skill/humanizer-writer](handoff/skill/humanizer-writer/) 复制到 `~/.claude/skills/`，在别的地方也能用 |
| 会用命令行 | `python -m writer run --brief 你的brief.json`，详见 [writer/README.md](writer/README.md) |

后两种要调用 Gemini，需要设置环境变量 `RELAYROUTER_BASE_URL` 和 `RELAYROUTER_API_KEY`，用你自己或团队的 key。需要 Python 3.11 及以上，不用另外装依赖。

---

维护者（调模型、改规则、做评测）看 [docs/维护说明.md](docs/维护说明.md)。
