# 来源：sw-dialogue（只登记，不收录文件）

- 仓库：https://github.com/jtydhr88/screenwriting-skills
- commit：`51115f18d160aa8b2ac5813e4432b6f0b425358f`（提交时间 2026-10-02T21:34:42-04:00）
- 评测用文件：`plugins/screenwriting/skills/sw-dialogue/SKILL.md`（只用这一个文件，不用同目录的 `reference.md`）
- 许可证：MIT，但仓库的 `NOTICE` 写明 MIT 不覆盖其中引用的原书片段和中译文
- 抓取日期：2026-11-11

## 为什么这里没有文件

`sw-dialogue/SKILL.md` 本身就夹着大量原书引文和译文（麦基《对白》、沃尔特、希克斯、陆军、王骥德《曲律》等），`reference.md` 更是逐场的原书摘录。课题约定不把这些原书片段放进本仓库，所以这里只记录固定版本，评测时临时取用，用完不提交。

原版仍是参赛者。评测脚本按下面的命令取到同一个 commit 的文件，直接作为 A 槽生成约束加载：

```bash
git clone https://github.com/jtydhr88/screenwriting-skills.git /tmp/screenwriting-skills
git -C /tmp/screenwriting-skills checkout 51115f18d160aa8b2ac5813e4432b6f0b425358f
cp /tmp/screenwriting-skills/plugins/screenwriting/skills/sw-dialogue/SKILL.md <评测临时目录>/sw-dialogue/SKILL.md
```

本仓库没有做 sw-dialogue 的改写版：改写版必然要带上原 skill 的正文，也就带上了引文。
