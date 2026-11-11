# skills

台词和口播两条线的候选 skill。这里的每个版本都是盲审的参赛者，没有一个是选定的版本。评测方法见评测方案（`docs/评测方案-台词与口播.md`）。

## upstream/

`eval/candidates.csv` 里“进比赛=是”、许可证为 MIT 的候选，原样复制。每个目录有一份 `SOURCE.md`，记着仓库地址、commit hash 和复制范围。原版本身是参赛者，不能被改写版替换。

- `sw-dialogue/` 只有 `SOURCE.md`。它的 `SKILL.md` 里夹着大量原书引文，不放进本仓库，评测时按 `SOURCE.md` 里的 commit 临时取用。
- blader/humanizer 在 candidates.csv 里是“待定”，原版不在这里；它的中文改写版在 `variants/blader-humanizer-zh/`，原版按那里的 `CHANGES.md` 写的 commit 取用。
- 没有收录：CC BY-NC 或没有声明许可证的仓库（lieflat、OUBIGFA、ai-flavor-remover、iskill-copy-deslop），以及还是“待定”的 dsh-deai-audit 和 sean-copy-style。

## variants/

在上游基础上的改写版，登记在 `eval/candidates-variants.csv`，多一列 `上游id`。每个目录有一份 `CHANGES.md`：基于哪个上游版本、改了什么、为什么改、预期改善什么，以及用 `variants/SAMPLES.md` 里的自写样本手动试用的前后对照。试用只说明改写版做了什么，不说明它比原版好。

| 改写版 | 上游 | 槽位 | 线 | 一句话 |
|---|---|---|---|---|
| stop-slop-zh | stop-slop | A | 台词、口播 | 中文化，通用版 |
| stop-slop-zh-taici | stop-slop（经 stop-slop-zh） | A | 台词 | 按台词线改造 |
| stop-slop-zh-koubo | stop-slop（经 stop-slop-zh） | A | 口播 | 按口播线改造 |
| blader-humanizer-zh | blader-humanizer v4.0.0 | B | 台词、口播 | 中文化，“可补真实细节”默认关 |
| humanizer-zh-taici | humanizer-zh | B | 台词 | 正文不动，增补台词规则 |
| humanizer-zh-koubo | humanizer-zh | B | 口播 | 正文不动，增补口播规则 |
| human-writing-batch | human-writing | A/B | 台词、口播 | 不提问、不检索、只用 brief |
| human-writing-lite-batch | human-writing-lite | A/B | 台词、口播 | 精简版的非交互版 |

所有改写版的规则都写成“删掉，或者换成具体信息”，不给固定替换词。
