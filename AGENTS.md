# humanizer-writer

一套已经调好的中文去 AI 味写稿工作流。

- **用户要写或改中文文案时**（台词、科普、口播、带练口令、通知、文章等）：照 `handoff/skill/humanizer-writer/SKILL.md` 做。流程是：整理 brief → 用 `python -m writer run` 写 3 份 → 检查 → 交给用户挑。
- **API key 只从环境变量读**（`RELAYROUTER_BASE_URL`、`RELAYROUTER_API_KEY`），不要写进文件。
- 工作流的配置（模型、skill、检查规则）由维护者来调。用户只是用，不要替用户改这些。
