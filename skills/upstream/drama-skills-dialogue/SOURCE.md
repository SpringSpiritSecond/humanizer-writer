# 来源：drama-skills-dialogue

- 仓库：https://github.com/zenstory-ai/drama-skills
- commit：`8cf7404981b7095b498e061832bb3c9ffd6a42be`（提交时间 2026-11-10T20:23:11+08:00）
- 复制范围：仓库内的 `skills/short-drama-write`
- 许可证：MIT，原文见同目录 `LICENSE`
- 抓取日期：2026-11-11

本目录是上游原文，除新增这份 `SOURCE.md`、并把仓库根目录的 `LICENSE` 复制进来以外，没有改动任何文件。它作为参赛者之一进入盲审，不能被 `skills/variants/` 下的改写版替换。

复现：

```bash
git clone https://github.com/zenstory-ai/drama-skills.git && git -C drama-skills checkout 8cf7404981b7095b498e061832bb3c9ffd6a42be
```

## 评测时用哪部分

candidates.csv 里的这个候选指 drama-skills 的台词规则。规则主要在 `references/dialogue-craft.md` 和 `references/script-craft.md`（“能演的不说”“画面已经证明的不复述”“动作线用可表演动词”）。整个 `short-drama-write` 目录原样保留，是因为 `SKILL.md` 按需引用这些文件；评测时作为 A 槽生成约束加载整个 skill，不单独抽出规则段落。
