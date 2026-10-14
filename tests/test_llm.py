import json

import httpx
import pytest

from hark import config as c
from hark.llm import polish as p
from hark.llm.ollama import LLMError, OllamaClient
from hark.pipeline import process


class FakeClient:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def chat(self, model, system, user, *, timeout, keep_alive, examples=(), max_tokens=None):
        self.calls.append({"model": model, "system": system, "user": user, "timeout": timeout,
                           "examples": examples, "max_tokens": max_tokens})
        if self.error:
            raise self.error
        return self.reply(user) if callable(self.reply) else self.reply


ORIGINAL = "so we should meet on tuesday no wait wednesday at 3 pm"


@pytest.mark.parametrize("reply,ok", [
    ("So we should meet on Wednesday at 3 PM.", True),
    ('"So we should meet on Wednesday at 3 PM."', True),
    ("Here is the cleaned text:\nSo we should meet on Wednesday at 3 PM.", True),
    ("", False),
    ("Meet.", False),  # dropped too much
    (("So we should meet on Wednesday at 3 PM. Let me know if you need anything else, "
      "I am happy to help with scheduling."), False),  # added too much
    ("Schedule conference Wednesday afternoon fifteen hundred.", False),  # novel words
])
def test_validate(reply, ok):
    text, status = p.validate(ORIGINAL, reply, [])
    assert (text == "So we should meet on Wednesday at 3 PM.") is ok, status


def test_validate_keeps_questions():
    assert p.validate("can you send it today?", "Can you send it today.", [])[0] is None


def test_vocabulary_terms_are_not_novel():
    _, status = p.validate("deploy it to cube nets now", "Deploy it to Kubernetes now.",
                           ["Kubernetes"])
    assert status == "used", status


def test_polish_skips_short_and_handles_errors():
    assert p.polish("ok thanks", FakeClient("x"), model="m", style="plain", terms=[],
                    base_timeout=10, keep_alive="30m").status.startswith("skipped")
    out = p.polish(ORIGINAL, FakeClient(error=LLMError("down")), model="m", style="plain",
                   terms=[], base_timeout=10, keep_alive="30m")
    assert out.text is None and out.status == "error: down"


def test_polish_line_by_line_keeps_breaks_and_falls_back_per_line():
    text = "okay so the deploy failed because of memory\n\nwe should bump the limits and redeploy"
    fixed = {"okay so the deploy failed because of memory":
             "Okay, so the deploy failed because of memory.",
             "we should bump the limits and redeploy": "Paris"}  # second reply is bogus
    out = p.polish(text, FakeClient(fixed.get), model="m", style="plain", terms=[],
                   base_timeout=10, keep_alive="30m")
    assert out.text == ("Okay, so the deploy failed because of memory."
                        "\n\nwe should bump the limits and redeploy")
    assert out.status == "used (1/2 lines)"


def test_polish_caps_output_tokens():
    fake = FakeClient("So we should meet on Wednesday at 3 PM.")
    p.polish(ORIGINAL, fake, model="m", style="plain", terms=[], base_timeout=10,
             keep_alive="30m")
    assert fake.calls[0]["max_tokens"] == len(ORIGINAL.split()) * 2 + 16


def test_system_prompt_includes_style_and_terms():
    prompt = p.system_prompt("notes", ["Hark.ai"])
    assert "'- '" in prompt and "Hark.ai" in prompt


def test_pipeline_rules_only_and_llm():
    cfg = c.Config()
    cfg.vocabulary = [{"from": "hark ai", "to": "Hark.ai"}]
    out = process("um I love hark ai comma truly", cfg)
    assert out.text == "I love Hark.ai, truly" and out.llm_status == "off"

    fake = FakeClient("I love hark ai, truly!")  # model "un-spells" the vocabulary term
    out = process("um I love hark ai comma truly", cfg, use_llm=True, client=fake)
    assert out.llm_status == "used"
    assert out.text == "I love Hark.ai, truly!"
    assert fake.calls[0]["user"] == "I love Hark.ai, truly"
    assert fake.calls[0]["examples"] == [p.EXAMPLE]

    out = process("um I love hark ai comma truly", cfg, use_llm=True,
                  client=FakeClient(error=LLMError("timed out")))
    assert out.text == "I love Hark.ai, truly" and out.llm_status.startswith("error")


def _client(handler):
    return OllamaClient("http://ollama.test", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_ollama_client_chat_and_errors():
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
        body = json.loads(request.content)
        if body["model"] == "missing":
            return httpx.Response(404, json={"error": "model not found"})
        if body["model"] == "slow":
            raise httpx.ReadTimeout("slow")
        assert body["think"] is False and body["stream"] is False
        assert body["options"]["temperature"] == 0
        return httpx.Response(200, json={"message": {"content": "Hi."}})

    client = _client(handler)
    assert client.has_model("qwen2.5:3b") and not client.has_model("llama3")
    assert client.chat("qwen2.5:3b", "s", "u", timeout=5, keep_alive="30m",
                       examples=[("a", "A.")], max_tokens=20) == "Hi."
    with pytest.raises(LLMError, match="ollama pull missing"):
        client.chat("missing", "s", "u", timeout=5, keep_alive="30m")
    with pytest.raises(LLMError, match="didn't answer"):
        client.chat("slow", "s", "u", timeout=5, keep_alive="30m")


def test_ollama_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="systemctl start ollama"):
        _client(handler).models()
