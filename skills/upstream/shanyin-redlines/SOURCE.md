# 来源：shanyin-redlines

- 仓库：https://github.com/Shanyin-ai/shanyin-screenwriting-master
- commit：`ca20ce245ae028e64418393d6cf4688b7dbe3d89`（提交时间 2026-04-01T10:18:00+08:00）
- 复制范围：整个仓库（不含 `.git/` 和 `.github/`）
- 许可证：MIT，原文见同目录 `LICENSE`
- 抓取日期：2026-11-11

本目录是上游原文，除新增这份 `SOURCE.md` 外，没有改动任何文件。它作为参赛者之一进入盲审，不能被 `skills/variants/` 下的改写版替换。

复现：

```bash
git clone https://github.com/Shanyin-ai/shanyin-screenwriting-master.git && git -C shanyin-screenwriting-master checkout ca20ce245ae028e64418393d6cf4688b7dbe3d89
```

## 评测时用哪部分

candidates.csv 里的这个候选指山音的“写作红线”（禁止解释性台词、不写摄影机拍不到的心理描写等）。红线写在 `山音超级编剧大师集成版（Gemini及其他AI工具通用）.md` 里；`.skill` 文件是同一套内容给 Claude/GPT 用的打包版。两份都原样保留。
