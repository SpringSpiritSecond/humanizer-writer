# humanizer-writer

中文去 AI 味写稿工作流。适用于各种文案：台词、科普、口播、带练口令、通知、文章都行。流程经过四轮人工盲审验证。

## 先看这个

**[handoff/使用手册.md](handoff/使用手册.md)**：这套流程是什么、怎么写 brief、怎么用、怎么挑稿，十分钟能看完。

一句话总结：**brief 只写场景和事实，不写风格要求，也不写不能说的话；用 Gemini 4 Argon 一次写 3 份，人来挑。**

## 三种用法

| 你是 | 怎么用 |
|---|---|
| 只想写稿，不碰代码 | 打开 Gemini 网页版，复制 [handoff/网页聊天提示词.md](handoff/网页聊天提示词.md)，填好就能用 |
| 用 Claude Code 或其他 AI 助手 | 在这个仓库里打开 Claude Code，说“帮我写一段……”就行，它会按 [AGENTS.md](AGENTS.md) 走流程；也可以把 [handoff/skill/humanizer-writer](handoff/skill/humanizer-writer/) 复制到 `~/.claude/skills/`，在别的地方用 |
| 会用命令行 | `python -m writer run --brief 你的brief.json`，用法见 [writer/README.md](writer/README.md) |

命令行和 AI 助手调用 Gemini 时，需要设置环境变量 `RELAYROUTER_BASE_URL` 和 `RELAYROUTER_API_KEY`。用你自己或团队的 key，不要提交进仓库，也不要转发给别人。

## 准备环境（只有命令行和 AI 助手的用法需要）

- Python 3.11 及以上，只用标准库，不用另外装依赖
- 跑测试要装 pytest：`python -m pytest -p no:cacheprovider --basetemp=<临时目录>`

## 仓库里有什么

| 目录 | 内容 |
|---|---|
| `handoff/` | 使用手册、网页聊天提示词、给 AI 用的 skill |
| `writer/` | 推荐的写稿工作流：检查 brief → 写 3 份 → 检查 → 报告 |
| `skills/` | 参加过评测的 skill：`upstream/` 是原版，`variants/` 是我们改写和自写的，其中 `scene-anchored` 是当前推荐 |
| `detect/` | 通用检测：AI 腔句式、感叹句、碎句、口令句的比例，提示词痕迹，口语化程度，模板句 |
| `eval/` | 盲审工具：批量生成稿子（`sample_pack.py`）、生成可分发的盲审 HTML（`build_review_artifact.py`）、揭晓结果（`reveal.py`），以及评测用的 brief |
| `docs/` | [工作流-当前推荐](docs/工作流-当前推荐.md)（结论和依据）、[工作流编排](docs/工作流编排.md)（完整流水线设计）、调研文档 |
| `pipeline/`、`workbench/`、`configs/`、`profiles/` | 早期搭的完整流水线（含自动改稿）和多人工作台，还没有接进推荐流程 |

## 继续改进

想换模型、加 skill 或改 brief 写法，先跑一轮盲审再决定。步骤见 [docs/工作流-当前推荐.md](docs/工作流-当前推荐.md) 最后一节。
