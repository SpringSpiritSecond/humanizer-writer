# writer：写稿工作流（当前推荐版）

一条命令：检查 brief → 写 3 份 → 逐份检查 → 出报告，由人挑。适用于任何中文文体。先看 [handoff/使用手册.md](../handoff/使用手册.md)。

## 1. 写 brief

复制 [brief_template.json](brief_template.json)，按场景填：

| 字段 | 写什么 | 注意 |
|---|---|---|
| `line` | 文体：科普、台词、口播、通知、文章…… | 台词、训练、口播有内置格式，其他文体用通用格式 |
| `speaker` | 谁在说、对谁说、在什么场合、两人什么关系 | 说话的分寸（多正式、多口语）由模型从这里推，**不要写“专业一点”“口语一点”** |
| `situation` | 此刻发生了什么，对方带着什么问题来 | 只写事实，**每件事只写一次，不加强调** |
| `facts` | 要讲的事，数字和专名原样写 | 数字会逐个检查有没有写进稿子 |
| `check_only` | 不能出现的说法 | **写稿模型看不到**，写完才检查；出现就判“不过” |
| `target.chars` | 目标字数 | 差 30% 以上会提示 |
| `format` | 交付格式（可选） | 例如“角色名：台词；（动作线）” |

台词可以沿用 `scene_card`（前情、人物、目标、冲突、beat），例子见 [examples/台词-星图暗了.json](examples/台词-星图暗了.json)。

不要在 brief 里写：
- 风格要求：“要短”“制造紧张感”“语气平实”“接地气”。模型会照字面执行，第一轮“要短”就被写成了碎句加感叹号。
- 强调和反复提醒。模型会把强调过的词在稿子里一遍遍地说。
- 不能说的话。这些放 `check_only`，否则会被写进稿子：第三轮 15 份稿子里有 15 份都写了“左右脑”。

## 2. 跑

```bash
python -m writer check --brief writer/examples/科普-双侧整合.json
```

```bash
python -m writer run --brief writer/examples/科普-双侧整合.json
```

- `check` 只检查 brief，不花钱。
- `run` 会写 3 份（`--n` 可以改），结果放在 `writer/out/<brief id>-<时间>/`：`稿1.txt`…`稿3.txt`、`report.md`、`report.json`。
- 需要环境变量 `RELAYROUTER_BASE_URL`、`RELAYROUTER_API_KEY`（Gemini）。每份约半美分。

已经有一份稿子，只想检查：

```bash
python -m writer check-text --brief <brief.json> --text <稿子.txt>
```

## 3. 看报告、挑稿

`report.md` 给每份稿子列出：

- **不过**：出现了 `check_only` 里的说法；或者事实里的数字没写对。这类直接不用。
- **提示**：brief 里没有的数字（是换算还是编的）、长度偏差、brief 里的词被反复说、口语化标记偏多（和身份合不合）、感叹句/碎句/没头没尾的口令偏多、AI 腔句式命中。

检查只是提示，**写得好不好由人判断**。报告里的“建议先看”只是按问题从少到多排了个序。

## 4. 配置

[config.json](config.json)：模型、skill、份数。这些是维护者调好的，使用时不用改，见 [docs/维护说明.md](../docs/维护说明.md)。
