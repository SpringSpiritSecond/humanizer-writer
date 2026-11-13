---
name: humanizer-writer
description: 写不像 AI 的中文文案（台词、科普、口播、带练口令、通知、文章），按评测过的工作流：整理 brief、用 Gemini 4 Argon 写 3 份、逐份检查、出报告，由人挑。用户要写或改中文文案、想去 AI 味时用。
---

# humanizer-writer

这套流程经过四轮人工盲审，依据见仓库里的 `docs/工作流-当前推荐.md`。核心结论是：**brief 写得对，比换模型、加 skill 都管用。** 写稿用 Gemini 4 Argon，配 scene-anchored 规则，一次写 3 份，检查后由人来挑。

## 步骤

### 1. 整理 brief

把用户给的材料整理成一份 brief，格式照 `references/brief_template.json`（仓库里是 `writer/brief_template.json`）。

- `speaker`：谁在说、对谁说、在什么场合、两人是什么关系。缺了就问用户，不要自己编。
- `situation`、`facts`：只写事实，每件事只写一次。数字和专名照原样抄。
- 用户提到的风格要求（“短一点”“口语一点”“专业点”“有紧张感”），先改写成对身份和场合的描述，再写进 `speaker`；写不进去的就不写。比如“专业点”可以写成“康复师，在机构里当面回答家长”。
- 用户提到的不能说的话、不能承诺的事，放进 `check_only`。

完成标准：`speaker` 和要讲的内容都齐了；brief 里没有风格形容词，也没有强调语。

### 2. 写 3 份

写稿的模型只能看到 brief 里除 `check_only` 和 `must_not` 以外的部分。规则见 `references/scene-anchored.md`。

- **仓库在本地，并且设了 `RELAYROUTER_BASE_URL` 和 `RELAYROUTER_API_KEY`**：把 brief 存成 JSON，运行 `python -m writer run --brief <文件>`。这条命令会用 Gemini 4 Argon 写，自动藏起 `check_only`，再做检查，结果放在 `writer/out/<id>-<时间>/`。
- **没有 Gemini 的 key**：由你自己写。先把 brief 去掉 `check_only` 和 `must_not`，再连同 `references/scene-anchored.md` 交给一个干净的子代理写 3 份，这样它看不到不能出现的内容。没法开子代理时，就自己写，写的时候只看 brief 的公开部分。告诉用户这一次没用推荐的模型。

完成标准：拿到 3 份完整的稿子。

### 3. 逐份检查

- 仓库在本地：用 `python -m writer run` 写的，直接读生成的 `report.md`；其他方式写的稿子，对每份运行 `python -m writer check-text --brief <brief> --text <稿子>`。
- 没有仓库：按 `references/checklist.md` 逐份逐项过一遍。

完成标准：每份稿子都有结论，要么“不过”并写明原因，要么“通过”，并列出所有提示。

### 4. 交给用户

把 3 份稿子和每份的检查结论一起给用户，由用户来挑。检查只能抓硬错误和疑似问题，写得好不好要用户判断。如果 3 份都不行，先帮用户改 brief，把身份、场合、情况写得更清楚，然后重跑。

## 已知限制

- 带练口令（按节拍喊的跟练口令）目前的效果都不好，交稿时提醒用户需要人工重写。
- 这些结论来自一位评审、小样本。用户想换模型或改流程时，指给他看仓库里 `eval/scripts/` 的盲审工具。
