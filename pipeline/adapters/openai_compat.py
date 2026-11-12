"""OpenAI 兼容接口的模型适配器（OpenRouter、DeepSeek、Kimi、GLM 等都能用）。

配置示例（models.generator）：

    {"adapter": "pipeline.adapters.openai_compat:OpenAICompatAdapter",
     "model": "anthropic/claude-opus-5.5", "vendor": "anthropic",
     "params": {"base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "temperature": 1.0, "max_tokens": 2000, "reasoning_effort": "low"}}

params：
    base_url / base_url_env   接口地址，或存地址的环境变量名（二选一）
    api_key_env               存密钥的环境变量名。配置里只写变量名，不写密钥本身
    temperature, max_tokens   采样参数
    reasoning_effort          "low" / "medium" / "high"；按 OpenRouter 的 reasoning.effort 传
    timeout                   单次请求秒数，默认 120
    max_retries               429 / 5xx 时最多重试几次，默认 3
    extra_body                原样并进请求体的其他字段

只调用 /chat/completions。每次调用的 token 用量（以及 OpenRouter 返回的 cost）记在 self.usage，
describe() 里给出汇总，所以运行报告里能看到每份配置实际花了多少。

已知限制：skill 只取 SKILL.md 正文；references/ 里的附属文件不会自动带上。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import ModelAdapter

LINE_FORMAT = {
    "台词": "只输出这场戏的剧本正文，不要标题、说明或任何解释。格式：每句台词一行，写成“角色名：台词”；动作线单独一行，用全角括号括起来。",
    "口播": "只输出口播稿正文，就是要念出来的话，不要标题、分镜、说明或任何解释。按说话的停顿分段，段与段之间换行。",
    "科普": "只输出要念出来的解说词，不要标题、分镜、画面说明或任何解释。按说话的停顿分段，段与段之间换行。",
}

LINE_FORMAT["训练"] = ("只输出教练在跟练时要说的话。按时间写，每行一句，格式是“起止秒｜要说的话”，例如“3–5｜……”；"
                     "不说话的时间段不用写。不要标题、动作说明或任何解释。")

ROLE = {"台词": "编剧", "口播": "短视频口播文案作者", "科普": "科普短视频的解说词作者", "训练": "儿童跟练视频的带练口令作者"}

SCOPE = {
    "in-place": "只改被指出的那几处，其余文字一个字都不动。",
    "bounded": "只改被指出的那几处所在的句子或段落，其他段落一个字都不动。",
    "structural": "可以调整整体结构，但事实、人名、数字、锁定台词、品牌词和行动号召必须原样保留。",
}


class AdapterError(RuntimeError):
    pass


def _public_brief(brief: dict) -> dict:
    """去掉只有管理员能看的字段，以及下划线开头的说明字段。"""
    return {k: v for k, v in brief.items()
            if k not in ("source", "status", "fictional", "is_example", "notes_admin") and not k.startswith("_")}


class OpenAICompatAdapter(ModelAdapter):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        p = self.params
        self.base_url = (p.get("base_url") or os.environ.get(p.get("base_url_env") or "", "")).rstrip("/")
        if not self.base_url:
            raise AdapterError(f"{self.role}：没有接口地址（params.base_url 或 base_url_env）")
        self.api_key_env = p.get("api_key_env") or ""
        if not self.api_key_env:
            raise AdapterError(f"{self.role}：params.api_key_env 没填（只写环境变量名）")
        self.usage: list[dict] = []

    # ---------- 请求 ----------

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise AdapterError(f"{self.role}：环境变量 {self.api_key_env} 是空的")
        return key

    def _body(self, messages: list[dict]) -> dict:
        p = self.params
        body: dict = {"model": self.model, "messages": messages}
        for k in ("temperature", "max_tokens", "top_p"):
            if p.get(k) is not None:
                body[k] = p[k]
        openrouter = "openrouter.ai" in self.base_url
        if p.get("reasoning_effort"):
            # OpenRouter 用 reasoning.effort；其他 OpenAI 兼容网关（RelayRouter 等）用 reasoning_effort
            if openrouter:
                body["reasoning"] = {"effort": p["reasoning_effort"]}
            else:
                body["reasoning_effort"] = p["reasoning_effort"]
        if openrouter:
            body["usage"] = {"include": True}
        body.update(p.get("extra_body") or {})
        return body

    def _post(self, body: dict) -> dict:
        """发一次请求，返回解析后的 JSON。测试时替换这个方法。"""
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json",
                     # 有些网关（Cloudflare 后面的）会拦 Python 默认的 User-Agent
                     "User-Agent": self.params.get("user_agent", "humanizer-writer-pipeline/0.1")},
            method="POST")
        with urllib.request.urlopen(req, timeout=float(self.params.get("timeout", 120))) as r:
            return json.loads(r.read().decode("utf-8"))

    def _chat(self, messages: list[dict], purpose: str) -> str:
        body = self._body(messages)
        retries = int(self.params.get("max_retries", 3))
        last = None
        for attempt in range(retries + 1):
            t0 = time.monotonic()
            try:
                resp = self._post(body)
            except urllib.error.HTTPError as e:
                try:
                    detail = (e.read() or b"").decode("utf-8", "replace").strip()[:200]
                except Exception:
                    detail = ""
                last = f"HTTP {e.code}" + (f"：{detail}" if detail else "")
                if e.code in (429, 500, 502, 503, 504, 524) and attempt < retries:
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise AdapterError(f"{self.role}：请求失败（{last}）") from None
            except (urllib.error.URLError, TimeoutError) as e:
                last = type(e).__name__
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise AdapterError(f"{self.role}：网络错误（{last}）") from None
            choices = resp.get("choices") or []
            text = ((choices[0].get("message") or {}).get("content") if choices else None) or ""
            u = resp.get("usage") or {}
            self.usage.append({"purpose": purpose, "model": resp.get("model", self.model),
                               "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                               "cost": u.get("cost"), "seconds": round(time.monotonic() - t0, 2),
                               "finish_reason": choices[0].get("finish_reason") if choices else None})
            if not text.strip():
                raise AdapterError(f"{self.role}：模型返回了空内容（finish_reason={self.usage[-1]['finish_reason']}）")
            return text.strip()
        raise AdapterError(f"{self.role}：重试 {retries} 次后仍失败（{last}）")

    # ---------- prompt ----------

    def _skills_text(self, keys: list[str]) -> str:
        parts = []
        for k in keys:
            for s in (self.slots.get(k) or {}).get("skills", []):
                t = s.text().strip()
                if t:
                    parts.append(f"<skill id=\"{s.id}\">\n{t}\n</skill>")
        return "\n\n".join(parts)

    def generation_messages(self, ctx: dict) -> list[dict]:
        line = ctx["line"]
        system = f"你是中文{ROLE[line]}。按用户给的 brief 写稿。{LINE_FORMAT[line]}"
        skills = self._skills_text(["A"])
        if skills:
            system += "\n\n写作时遵守下面的 skill：\n\n" + skills
        brief = json.dumps(_public_brief(ctx["brief"]), ensure_ascii=False, indent=1)
        return [{"role": "system", "content": system}, {"role": "user", "content": f"brief：\n{brief}"}]

    def rewrite_messages(self, ctx: dict, hits: list[dict]) -> list[dict]:
        line = ctx["line"]
        scope = (self.slots.get("C") or {}).get("scope", "in-place")
        system = (f"你在修改一篇中文{line}稿。{SCOPE.get(scope, SCOPE['in-place'])}"
                  f"brief 里的事实、数字、人名、锁定台词、品牌词和行动号召必须原样保留，不能新增 brief 里没有的事实、数字或承诺。"
                  f"{LINE_FORMAT[line]}")
        skills = self._skills_text(["B"])
        if skills:
            system += "\n\n修改时遵守下面的 skill：\n\n" + skills
        lines = []
        for i, h in enumerate(hits, 1):
            where = f"「{h.get('excerpt')}」" if h.get("excerpt") else "全文"
            lines.append(f"{i}. {where}：{h.get('message', '')}（{h.get('rule')}）")
        brief = json.dumps(_public_brief(ctx["brief"]), ensure_ascii=False, indent=1)
        user = f"brief：\n{brief}\n\n原稿：\n{ctx['text']}\n\n要处理的问题：\n" + "\n".join(lines)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ---------- 接口 ----------

    def generate(self, ctx: dict, n: int) -> list[str]:
        msgs = self.generation_messages(ctx)
        return [self._chat(msgs, f"generate#{i}") for i in range(n)]

    def rewrite(self, ctx: dict, hits: list[dict]) -> str:
        return self._chat(self.rewrite_messages(ctx, hits), f"rewrite@round{ctx.get('round')}")

    def describe(self) -> dict:
        d = super().describe()
        costs = [u["cost"] for u in self.usage if isinstance(u.get("cost"), (int, float))]
        d["usage"] = {"calls": len(self.usage),
                      "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in self.usage),
                      "completion_tokens": sum(u.get("completion_tokens") or 0 for u in self.usage),
                      "cost": round(sum(costs), 6) if costs else None}
        return d
