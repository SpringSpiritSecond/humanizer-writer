"""第三轮盲审后加的通用检查：提示词痕迹、brief 回声、口语化密度、模板句。"""
from detect.trace import annotate, brief_echo, colloquial, prompt_trace, template_ratio
from pipeline.adapters.openai_compat import _public_brief


def test_check_only_is_hidden_from_writer():
    b = {"id": "x", "line": "科普", "facts": [{"field": "能力", "value": "双侧整合"}],
         "check_only": {"不能出现的说法": ["左右脑"]}, "must_not": ["不承诺疗效"]}
    pub = _public_brief(b)
    assert "check_only" not in pub and "must_not" not in pub and pub["facts"]


def test_prompt_trace_counts_forbidden_phrases():
    b = {"check_only": {"不能出现的说法": ["左右脑", "疗效承诺或改善比例"]}, "must_not": ["不说“左右脑失衡”"]}
    r = prompt_trace("有人说这是左右脑失衡，其实不是。", b)
    assert r["prompt_trace"] >= 2 and "左右脑" in r["prompt_trace_terms"]
    assert prompt_trace("双手配合需要练。", b)["prompt_trace"] == 0


def test_brief_echo_reports_repeated_brief_terms():
    b = {"situation": "孩子常常拍到同一边", "screen_cues": ["拍到对面的膝盖"]}
    text = "拍对面。对面的膝盖。再拍对面，记住是对面。"
    r = brief_echo(text, b)
    assert r["brief_echo_max"] >= 3 and any("对面" in t for t in r["brief_echo_terms"])
    assert brief_echo("左手拍右膝。", b)["brief_echo_max"] == 0


def test_colloquial_density():
    assert colloquial("咱们孩子啥都好，别瞎操心呗。")["colloquial"] == 4
    assert colloquial("我们先看孩子转圈后多久能站稳。")["colloquial"] == 0


def test_template_ratio_flags_sentences_shared_across_briefs():
    texts = {"a": "您先放宽心，这个很常见。孩子转圈后会晕。", "b": "您先放宽心，这个很常见。孩子跳绳手脚对不上。"}
    tr = template_ratio(texts, min_chars=4)
    assert tr["a"] == 0.5 and tr["b"] == 0.5


def test_annotate_has_all_keys():
    keys = annotate("我们看看。", {}).keys()
    assert {"prompt_trace", "brief_echo_max", "colloquial_per_kchar"} <= set(keys)
