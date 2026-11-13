# humanizer-writer

中文去 AI 味写稿工作流，以及验证它用的盲审工具。

- **用户要写或改中文文案时**：按 `handoff/skill/humanizer-writer/SKILL.md` 的步骤做。它会带你整理 brief、用 `python -m writer run` 写 3 份、检查、交给用户挑。
- **用户要比较模型、skill 或流程改动时**：先跑一轮盲审再下结论。步骤写在 `docs/工作流-当前推荐.md` 的“怎么继续改进”一节；用到的工具是 `eval/scripts/` 下的 `sample_pack.py`、`build_review_artifact.py`、`reveal.py`。
- **评审由人做，AI 不当评审**：AI 负责出稿、做去盲、在评完后揭晓。审稿页上不能出现模型名、skill 名或检测结果。
- **API key 只从环境变量读**（`RELAYROUTER_BASE_URL`、`RELAYROUTER_API_KEY` 等），配置里只写变量名。
- **跑测试**：`python -m pytest -p no:cacheprovider --basetemp=<临时目录>`。部分 Windows 机器上，pytest 默认的临时目录没有写权限，所以要显式指定一个。
- 这个项目做的是通用工作流。从样例（台词、科普……）里发现的问题，要先提炼成通用规则再落地，不要写成只针对某个场景的规则。
