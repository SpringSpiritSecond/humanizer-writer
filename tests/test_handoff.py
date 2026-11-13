"""交接包里复制过去的文件要和源头保持一致：skill 需要能单独复制到 ~/.claude/skills/ 使用，所以只能放副本。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "handoff/skill/humanizer-writer/references"


def test_scene_anchored_copy_in_sync():
    assert (REF / "scene-anchored.md").read_text(encoding="utf-8") == \
        (ROOT / "skills/variants/scene-anchored/SKILL.md").read_text(encoding="utf-8")


def test_brief_template_copy_in_sync():
    assert (REF / "brief_template.json").read_text(encoding="utf-8") == \
        (ROOT / "writer/brief_template.json").read_text(encoding="utf-8")


def test_handoff_links_exist():
    for p in ["handoff/使用手册.md", "handoff/网页聊天提示词.md", "handoff/skill/humanizer-writer/SKILL.md",
              "AGENTS.md", "writer/README.md", "docs/工作流-当前推荐.md"]:
        assert (ROOT / p).is_file(), p
