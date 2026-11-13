---
name: humanizer-writer
description: 写不像 AI 的中文文案（任何文体），按已经调好的工作流：整理 brief、写 3 份（推荐 Gemini 4 Argon）、逐份检查、出报告，由人挑。用户要写或改中文文案、想去 AI 味时用。
---

# humanizer-writer

这套工作流已经调好：**brief 写对最管用。** 按 scene-anchored 规则一次写 3 份，检查后由用户挑。写稿模型推荐用 Gemini 4 Argon，换别的模型也可以。

## 步骤

### 1. 整理 brief

把用户给的材料整理成一份 brief，格式照 `references/brief_template.json`（仓库里是 `writer/brief_template.json`）。

- `speaker`：谁在说、对谁说、在什么场合、两人是什么关系。缺了就问用户，不要自己编。
- `situation`、`facts`：只写事实，每件事只写一次。数字和专名照原样抄。
- 用户提到的风格要求（“短一点”“口语一点”“专业点”“有紧张感”），先改写成对身份和场合的描述，再写进 `speaker`；写不进去的就不写。比如“专业点”可以写成“康复师，在机构里当面回答家长”。
- 用户提到的不能说的话、不能承诺的事，放进 `check_only`。

完成标准：`speaker` 和要讲的内容都齐了；brief 里没有风格形容词，也没有强调语。

### 2. 写 3 份

写稿时只依据 brief 里写给写稿人看的部分，`check_only` 和 `must_not` 留到第 3 步检查时再用。规则见 `references/scene-anchored.md`。

- **推荐：用 Gemini 4 Argon。** 在 humanizer-writer 仓库根目录，把 brief 存成 JSON，运行 `python -m writer run --brief <brief 文件>`。这条命令会写 3 份并逐份检查，结果放在 `writer/out/<id>-<时间>/`。需要环境变量 `RELAYROUTER_BASE_URL` 和 `RELAYROUTER_API_KEY`。
- **换别的模型**：任何 OpenAI 兼容接口的模型都可以。复制一份 `writer/config.json`，改掉里面的 `model`，再加上 `--config <新配置>` 运行。
- **没有 key，或者用户想让你直接写**：你按 `references/scene-anchored.md` 写 3 份，存成 3 个文本文件，然后跟用户说明这次没有用推荐的模型。

完成标准：拿到 3 份完整的稿子。

### 3. 看检查结果

用 `python -m writer run` 写的，直接读 `report.md`。其他方式写的稿子，或者用户自己带来的稿子，每份都运行 `python -m writer check-text --brief <brief> --text <稿子>`。

### 4. 交给用户

把 3 份稿子和每份的检查结论一起给用户，由用户来挑。检查只能抓硬错误和疑似问题，写得好不好要用户判断。如果 3 份都不行，先帮用户改 brief，把身份、场合、情况写得更清楚，然后重跑。

## 注意

- 工作流配置（模型、规则、检查）由维护者来调。用户要改，请他联系维护者，这里不替他改。
