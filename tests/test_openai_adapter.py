import json
import urllib.error

import pytest

from pipeline.adapters.base import resolve_skill
from pipeline.adapters.openai_compat import AdapterError, OpenAICompatAdapter

BRIEF = {"id": "vo-t", "line": "口播", "source": {"human_original": "秘密路径"}, "status": "draft",
         "facts": [{"field": "价格", "value": "89 元"}], "must_include": {"brand_terms": ["某牌"], "cta": "点链接"}}


def make(monkeypatch, responses, slots=None, **params):
    monkeypatch.setenv("TEST_KEY", "sk-should-not-leak")
    p = {"base_url": "https://example.invalid/v1", "api_key_env": "TEST_KEY", **params}
    ad = OpenAICompatAdapter("generator", "m-1", "v", p, slots or {})
    sent = []

    def fake_post(body):
        sent.append(body)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    ad._post = fake_post
    monkeypatch.setattr("time.sleep", lambda s: None)
    return ad, sent


def ok(text, cost=0.01):
    return {"model": "m-1", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": cost}}


def test_generate_n_calls_and_usage(monkeypatch):
    ad, sent = make(monkeypatch, [ok("一"), ok("二"), ok("三")])
    out = ad.generate({"line": "口播", "brief": BRIEF}, 3)
    assert out == ["一", "二", "三"] and len(sent) == 3
    u = ad.describe()["usage"]
    assert u["calls"] == 3 and u["prompt_tokens"] == 300 and u["cost"] == pytest.approx(0.03)


def test_admin_fields_and_key_not_in_prompt(monkeypatch):
    ad, sent = make(monkeypatch, [ok("x")])
    ad.generate({"line": "口播", "brief": BRIEF}, 1)
    blob = json.dumps(sent, ensure_ascii=False)
    assert "秘密路径" not in blob and "sk-should-not-leak" not in blob and "draft" not in blob
    assert "89 元" in blob
    assert "sk-should-not-leak" not in json.dumps(ad.describe(), ensure_ascii=False)


def test_skill_text_goes_into_system(monkeypatch):
    slots = {"A": {"skills": [resolve_skill("stop-slop-zh-koubo")], "combine": "serial"}}
    ad, sent = make(monkeypatch, [ok("x")], slots=slots)
    ad.generate({"line": "口播", "brief": BRIEF}, 1)
    system = sent[0]["messages"][0]["content"]
    assert '<skill id="stop-slop-zh-koubo">' in system


def test_baseline_none_has_no_skill_block(monkeypatch):
    slots = {"A": {"skills": [resolve_skill("baseline-none")], "combine": "serial"}}
    ad, sent = make(monkeypatch, [ok("x")], slots=slots)
    ad.generate({"line": "台词", "brief": {**BRIEF, "line": "台词"}}, 1)
    assert "<skill" not in sent[0]["messages"][0]["content"]


def test_rewrite_lists_hits_and_scope(monkeypatch):
    slots = {"B": {"skills": [], "combine": "serial"}, "C": {"skills": [], "scope": "bounded"}}
    ad, sent = make(monkeypatch, [ok("改好了")], slots=slots)
    hits = [{"rule": "not_x_but_y", "excerpt": "不是需求而是态度", "message": "删掉，或换成具体信息"},
            {"rule": "g0.length", "excerpt": None, "message": "太长"}]
    out = ad.rewrite({"line": "口播", "brief": BRIEF, "text": "原稿", "round": 1}, hits)
    assert out == "改好了"
    msgs = sent[0]["messages"]
    assert "所在的句子或段落" in msgs[0]["content"]
    assert "「不是需求而是态度」" in msgs[1]["content"] and "全文：太长" in msgs[1]["content"]


def test_reasoning_and_openrouter_usage_flag(monkeypatch):
    ad, sent = make(monkeypatch, [ok("x")], base_url="https://openrouter.ai/api/v1",
                    reasoning_effort="low", temperature=1.0)
    ad.generate({"line": "口播", "brief": BRIEF}, 1)
    assert sent[0]["reasoning"] == {"effort": "low"} and sent[0]["usage"] == {"include": True}
    assert sent[0]["temperature"] == 1.0


def test_reasoning_effort_for_other_gateways(monkeypatch):
    ad, sent = make(monkeypatch, [ok("x")], reasoning_effort="low")
    ad.generate({"line": "口播", "brief": BRIEF}, 1)
    assert sent[0]["reasoning_effort"] == "low" and "reasoning" not in sent[0] and "usage" not in sent[0]


def test_retry_then_success(monkeypatch):
    err = urllib.error.HTTPError("u", 429, "rate", {}, None)
    ad, sent = make(monkeypatch, [err, ok("x")])
    assert ad.generate({"line": "口播", "brief": BRIEF}, 1) == ["x"] and len(sent) == 2


def test_non_retryable_error(monkeypatch):
    err = urllib.error.HTTPError("u", 401, "auth", {}, None)
    ad, _ = make(monkeypatch, [err])
    with pytest.raises(AdapterError, match="HTTP 401"):
        ad.generate({"line": "口播", "brief": BRIEF}, 1)


def test_empty_content_is_error(monkeypatch):
    ad, _ = make(monkeypatch, [{"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}])
    with pytest.raises(AdapterError, match="空内容"):
        ad.generate({"line": "口播", "brief": BRIEF}, 1)


def test_missing_env_key(monkeypatch):
    monkeypatch.delenv("NO_SUCH_KEY_X", raising=False)
    ad = OpenAICompatAdapter("generator", "m", "v", {"base_url": "https://x.invalid", "api_key_env": "NO_SUCH_KEY_X"}, {})
    with pytest.raises(AdapterError, match="NO_SUCH_KEY_X"):
        ad._key()


def test_requires_key_env_name():
    with pytest.raises(AdapterError, match="api_key_env"):
        OpenAICompatAdapter("generator", "m", "v", {"base_url": "https://x.invalid"}, {})
