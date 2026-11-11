# detect：S2 规则检测与 G3 风格计量

本模块实现去 AI 味工作流里的两个阶段（见 [docs/工作流编排.md](../docs/工作流编排.md)），评测时也拿来当第一层的结构信号，用来替代已经丢失的 `zh_slop.py`。

```python
from detect.stages import s2, g3   # 配置里写 "S2": "detect.stages:s2", "G3": "detect.stages:g3"
```

两个函数都收 3.1 节规定的 `ctx`，返回结果 dict。

- **S2**（`kind: report`）：`verdict` 恒为 `pass`，`route_to` 为 `null`。只输出 `hits`，交给 S3 定向改写。`metrics` 里有 `hit_counts`、`rules_off` 和 `protected_spans`。
- **G3**（`kind: soft`）：只算指标。阈值从 `ctx["config"]["thresholds"]` 读，没给阈值时一律 `pass`，只记录指标。

**检测分数不是优化目标。** 这里的规则和指标只用来告诉改写“哪里可能有问题”，评测时它们的分数也只记录、不排名（评测方案第 3 节）。要是哪个 skill 专门去压这些分，改出来的稿子会更差。

## 文件

| 文件 | 内容 |
|---|---|
| `rules.json` | 规则数据：S2 每条规则的档位、正则或词表、给改写看的 message；G3 的连接词表、buzzword 表、最小长度 |
| `text.py` | 切段、切句、切分句，读 profile，处理受保护片段和说话人前缀 |
| `s2.py` | 每类规则一个小函数（`FINDERS`），`detect()` 统一处理档位、开关、例外 |
| `g3.py` | 指标计算、阈值判断 |
| `stages.py` | 入口 |
| `samples/台词.json`、`samples/口播.json` | 自写示例：一组 AI 腔，一组“不该改” |

要增删规则：在 `rules.json` 里加一条，`kind` 写成已有的函数名（多数规则用 `regex` 就够了），再在 `tests/test_detect_s2.py` 的 `CASES` 里补命中和不命中的例子。新的规则 id 要先补进设计文档 3.2 节的表。

## 切分与通用处理

- **段**：每个非空行算一段。台词里一行就是一个人的一次发言，或一条动作线。“同段 ≥2 才标”按这个口径数。
- **句**：在 `。！？!?…` 处断开，右引号和右括号跟着前一句走。
- **分句**：在 `，、；：` 和句末标点处断开。
- **说话人前缀**：台词线把行首的 `角色名：`、`角色名（动作）：` 换成等长的空格之后再检测，所以角色名后面的冒号不算结论式冒号。span 仍然是原文的下标。
- **受保护片段**：命中位置和这些片段重叠就不报。片段有两个来源：profile `fidelity.exact` 列出的字段（G2 要求逐字一致，S3 改不了，报了也没用），以及例外 `slogan_verbatim` 生效时的 `brief.must_include.brand_terms`。
- **severity**：规则在 profile 里是 `on`（或没写）时为 `warn`，是 `hint` 时为 `hint`。S2 从不给 `block`，因为它只报告，不拦截。
- 所有密度都按“每千个可计数字符”算。可计数字符是汉字、英文字母和数字，不含标点和空白。

## S2 规则

| id | 档位 | 台词默认 | 口播默认 | 怎么判 |
|---|---|---|---|---|
| `not_x_but_y` | 单次即标 | on | on | 不是……而是、并非……而是、与其……不如、不在于……而在于，以及 不仅（仅）/ 不只 / 不单（单）/ 不光 是……而是 / 更是；“不仅……还 / 也 / 而且”这类正常递进不算 |
| `jinxing_verb` | 单次即标 | on | on | “进行(了/着)(一次/一番…)”后面紧跟两个汉字；排除 进行到 / 进行中 / 进行曲 / 进行的 等 |
| `cliche_opening` | 单次即标 | on | on | 只看每段第一句的开头：随着……的发展、在这个……的时代、众所周知、近年来 等 |
| `cliche_ending` | 单次即标 | on | on | 只看全文最后两句：总之、让我们一起、未来可期、开启……新篇章、拥抱……未来 等 |
| `colon_conclusion` | 单次即标 | on | on | 核心 / 关键 / 本质 / 答案 / 说白了 / 一句话 …… 后面 4 字以内接冒号 |
| `punchline_ending` | 单次即标 | on | on | 只看全文最后一句（跳过纯动作线）：才是最好的、真正的……是、从来不是、本身就是、愿你 等 |
| `triple_parallel` | 单次即标 | on | **hint** | 连续 ≥3 个短分句（每个 ≤12 字）开头相同：要么是词表里的排比开头（更 / 让 / 每一 / 有 / 是 等），要么共用 ≥2 字前缀且不以代词开头、不用顿号隔开；另加 无论是……还是……亦或是、从……到……再到 |
| `de_stacking` | 同段 ≥2 | on | on | 一个分句里有 ≥3 个“的”（的确 / 目的 / 的士 / 的话 这类不算），同一段出现两处才标 |
| `bei_stack` | 同段 ≥2 | on | on | 被（被子 / 被窝 / 被告 / 被动 这类不算），同一段两次才标 |
| `four_char_parallel` | 同段 ≥2 | on | on | 连续 ≥3 个恰好四个汉字的分句，不跨句，算一组排比；同一段两组才标 |
| `dash` | 同段 ≥2 | **off** | on | 破折号（数字范围 10—20 不算），同一段两个才标 |
| `rhetorical_question` | 同段 ≥2 | **hint** | **hint** | 问句后面紧跟本段内的陈述句，算自问自答；连着发问不算 |

档位严格按设计文档 3.2 节的表；台词和口播的默认值就是 `profiles/` 里写的值，没写的按 `on`。

### 规则依据和已知分歧

依据来自[课题背景](../docs/去AI味-课题背景与首轮调研.md)的“小规模试验发现”和“公开资料与方法对照”两节。那两节里的数字本轮都没有复算，下面只说方向。

- **`not_x_but_y`**：小试验里 AI 明显更多；lieflat 称这是最强的纯写作信号；Peng 等 2026 年的论文给出商业模型密度是人类参照的 2.5–9.2 倍。几个来源方向一致，所以单次即标。同一篇论文也指出，大多数用例是“正确但没必要”，所以 message 让改写先确认真有人持前一种看法，不直接要求删。口语里常见的“不是我，是他”不带“而是”，不算。
- **`cliche_opening` / `cliche_ending` / `punchline_ending`**：对应 blader/humanizer、stop-slop 等英文规则里的“起跑式铺垫”“一行收束”“伪深度”，没有找到中文实测数字。所以只看位置（段首、全文最后一两句），不扫全文，尽量少误伤。台词的锁定金句通过 `fidelity.exact` 受保护，不会被当成金句收尾。
- **`colon_conclusion`**：小试验里冒号**总数**没有区分度；lieflat 的语义层称“核心是：”这类结论提示冒号 AI 约为人类的 2.1 倍（单模型判断，误判率自报 15%–30%）。所以只认引出结论的那几个词，不算冒号总数。冒号总密度放在 G3 里，只记录。
- **`dash`**：分歧最大。小试验没有区分度；lieflat 称破折号在 Opus 上很多，在 GPT 上反而比人类少。台词里破折号多半表示打断，所以台词默认 off；口播默认 on，但要同段两个才标。
- **`rhetorical_question`、`triple_parallel`**：口播里设问和三段式是正常手法（评测方案第 3 节），所以默认 hint，还有例外放行（见下）。
- **`jinxing_verb`、`bei_stack`、`de_stacking`、`four_char_parallel`**：来自中文写作规范和各中文 skill 的共识，没有看到 AI 和真人对照的数据。档位按设计文档的表来，阈值（≥3 个“的”、≥3 个四字分句）是自定的，等盲审标注回来再调。

## 例外怎么生效

| 线 | 例外 id | 检测器的做法 |
|---|---|---|
| 台词 | `dash_interrupt` | 破折号后面到行尾没有别的字，或者紧跟括号、省略号，或者紧跟“算了 / 不对 / 我是说 / 等等 / 呃 / 你 / 我”这类重新起头的词，算打断，不计数。S2 的 `dash` 和 G3 的 `dash_per_kchar` 都这样处理 |
| 台词 | `unfinished_line` | 以 …… 或 —— 结尾的句子，不参与收尾类规则（`cliche_ending`、`punchline_ending`）；以省略号收住的排比也不标 |
| 台词 | `catchphrase_repeat` | 三个一模一样的分句（“得嘞，得嘞，得嘞”）不算排比，`triple_parallel` 和 `four_char_parallel` 都放行。G3 的用词多样性本来就是“越重复越低”，不会因为口头禅而被判成换词过勤 |
| 台词 | `short_fragment` | 所在句子 ≤4 个字的命中一律不报（“去哪？回家。”不算自问自答） |
| 台词 | `children_screen_recap`、`action_line_adverbs`、`first_episode` | 不归 S2 管，检测器什么都不做：`first_episode` 归 G1 合规，`children_screen_recap` 和 `action_line_adverbs` 留给 S3 和以后的语义规则。样本里留了这些写法，确认不会误报 |
| 口播 | `spoken_rhetorical_question` | 问句里带“你 / 您 / 大家 / 家人们 / 姐妹们”这类对观众说话的词时，不算设问；“为什么它能做到？因为……”这种自问自答仍然报，只是 profile 里是 hint |
| 口播 | `spoken_triple` | 三项里至少两项带数字或量词（180 克、7 天、35 分贝）时，不算硬凑三点 |
| 口播 | `short_repeat` | 同 `catchphrase_repeat`：一模一样的重复（“买它，买它，买它”）不算排比 |
| 口播 | `slogan_verbatim` | `brief.must_include.brand_terms` 里的品牌词和 slogan 原文受保护，S2 不报，G3 的词表计数也不算 |
| 口播 | `keep_connectives` | 只影响改写：G3 的 `connector_density` message 写的是“换成具体的因果或先后，不要删成电报体”。自写的口播自然样本里，连接词密度反而比 AI 腔样本高，这也说明连接词不能当硬指标 |

## G3 指标

| 指标 | 对应规则 id | 算法 | 什么时候不算（值为 `null`） |
|---|---|---|---|
| `heading_per_kchar` | `heading_density` | 带“一、 / 1. / 第一部分 / 【】 / #”标记的行，或 ≤15 字、没有标点、下一段长度是它两倍以上的行；台词里带说话人前缀的行不算 | 正文为空 |
| `connector_per_kchar` | `connector_density` | 词表里的连接词，只在分句开头计；长词优先（“总而言之”不再另算“总之”） | 同上 |
| `buzzword_per_kchar` | `buzzword` | 词表里的词，出现在哪都算 | 同上 |
| `semicolon_per_kchar`、`dunhao_per_kchar` | `semicolon_dunhao` | ；和、的个数 | 同上 |
| `dash_per_kchar` | `dash` | 破折号，按 `dash_interrupt` 例外扣掉打断 | 同上 |
| `colon_per_kchar` | `colon_conclusion` | 冒号，不含说话人前缀 | 同上 |
| `sentence_len_cv` | `uniform_length` | 句长（可计数字符）的变异系数 = 总体标准差 ÷ 均值；不含纯动作线 | 少于 3 句 |
| `paragraph_len_cv` | `uniform_length` | 段长的变异系数 | 少于 3 段 |
| `char_mattr` | `synonym_rotation` | 字级 MATTR（滑动窗口 50 字的平均型例比） | 少于 100 字 |
| `bigram_mattr` | `synonym_rotation` | 字二元组的 MATTR，窗口 50 | 少于 100 字 |
| `batch_distinct_2`、`batch_distinct_3` | `batch_diversity`（阈值用 `min`） | 当前稿和 `batch_texts` 合起来，字二元组 / 三元组的不重复比例 | 合格的稿子不到 2 份；字数少于 20 的稿子不参与 |
| `batch_self_bleu` | `batch_diversity`（阈值用 `max`） | 每份稿子对其余稿子算字级 BLEU-4（n>1 加一平滑），取平均；越高说明越雷同 | 同上 |
| `batch_bleu_current` | `batch_diversity`（阈值用 `max`） | 当前稿对其余稿子的 BLEU-4 | 同上 |

另有 `chars`、`sentences`、`paragraphs` 几个计数，`exceeded`（超标的指标名），以及 `skipped_thresholds`（给了阈值但没检查的指标，原因可能是规则 off、指标为 null，或者指标名不认识）。

**太短不能算。** 变异系数少于 3 句或 3 段时不算，用词多样性少于 100 字时不算，批次多样性每份少于 20 字时不算。每千字密度在短文本上也很不稳：一条 45 秒的口播大约 200 字，出现一个连接词就是 5 / 千字。所以密度虽然照算，阈值一定要按实际长度的稿子来校准，不能照搬长文的数字（小试验那批是少数派长文）。

### 阈值格式

```json
{
  "thresholds": {
    "dash_per_kchar": { "max": 6 },
    "sentence_len_cv": { "min": 0.3 },
    "connector_per_kchar": 4
  }
}
```

写成数字时按 `max` 处理。指标超标时：

- 规则在 profile 里是 `on`：`verdict: "route"`，`route_to: "S3"`，并附上 `warn` 级命中。
- 规则是 `hint`：附上 `hint` 级命中，但不打回，`verdict` 仍是 `pass`。
- 规则是 `off`：不检查，记进 `skipped_thresholds`。

`batch_diversity` 是新增的规则 id（计量，约定文档 3.2 节的表由主会话补）。两条线的 profile 里都没写它，所以按 `on` 处理。

命中位置：密度类指标给出每个计数位置；批次内多样性给全文；句长、段长过匀给出长度最接近的那一串连续句子或段落（至少 3 个，找不到就给全文）；用词多样性给全文。轮数上限由 runner 按槽位 D 控制，G3 不管。

**现在没有任何默认阈值。** 设计文档规定，阈值要等工作台的人工盲审数据回来再校准，在那之前 G3 只记录。

### 已知分歧（G3）

- **`connector_density` 和 `buzzword`**：小试验里能把 AI 和真人分开（连接词 AI 约 5.6 / 千字，真人中位数是 0），但 lieflat 的第二轮配对复测（同题、同事实）里差距消失了（δ +0.02，赋能类词配对后没有差异）。两边都不能盖过另一边，所以两条线的 profile 都把它们设成 hint，阈值即使超了也不打回。词表要随模型更新重测。
- **`synonym_rotation`**：方向和直觉相反。小试验和 lieflat 都发现 AI 的用词多样性**更高**（模型爱轮换“优化 / 增强 / 提升”），所以这个指标要设 `max`，不是 `min`。把“用词丰富”当成目标会改反。
- **`uniform_length`**：两边方向一致（AI 更匀）。但 lieflat 提醒不要为了参差而逐句改句长，所以 message 写的是“按意思自然断句”。
- **`heading_density`**：小试验里区分度最强，但台词和口播本来就没有小标题，两条线的 profile 都设成 off。指标照样记录，方便以后用到长文。
- **顿号、分号、破折号、冒号**：小试验里都没有区分度；lieflat 说顿号、分号更像 GPT 的指纹，破折号要看是哪个模型。所以只记录，阈值留空。

## 局限

- **没有分词。** 只用标准库，词表是逐字匹配（“生态”在“生态环境”里也会被算成 buzzword），多样性按字和字二元组算，不是按词算。所以 `synonym_rotation` 测的其实是用字多样性，查不出“优化 / 增强 / 提升”这种真正的同义词轮换，只能间接反映。要测真正的同义词轮换，需要分词和同义词表，留给以后。
- **正则会漏，也会误报。** 尤其是 `triple_parallel` 的共同前缀判断和 `jinxing_verb` 的“后接两个汉字”。不命中的例子写在测试里，发现新的误报就补进去。
- **切段靠换行。** 约定要求统一格式时保留换行；如果上游把口播压成一整段，“同段 ≥2”就会按全文来数。
- 词表和正则都是本仓库自写的。lieflat-less-ai-tone 是 CC BY-NC，这里只参考它公开的结论，没有用它的代码、词表和规则文本。活人感写作的 `check_prose.py` 是参赛者之一的工具，这里没有照搬它的规则，以免检测器偏向它。
