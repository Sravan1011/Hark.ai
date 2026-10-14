"""Minimal Ollama HTTP client (https://github.com/ollama/ollama/blob/main/docs/api.md)."""

from __future__ import annotations

import httpx

from ..errors import HarkError


class LLMError(HarkError):
    pass


class OllamaClient:
    def __init__(self, url: str, http: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self._http = http or httpx.Client()

    def _request(self, method: str, path: str, *, timeout: float, **kwargs) -> dict:
        try:
            resp = self._http.request(method, self.url + path, timeout=timeout, **kwargs)
        except httpx.TimeoutException:
            raise LLMError(f"Ollama didn't answer within {timeout:.0f}s") from None
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama isn't reachable at {self.url} ({e}). "
                           "Start it with: sudo systemctl start ollama") from None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code == 404 and "model" in kwargs.get("json", {}):
            model = kwargs["json"]["model"]
            raise LLMError(f"model '{model}' isn't pulled. Run: ollama pull {model}")
        if resp.status_code != 200:
            raise LLMError(f"Ollama error {resp.status_code}: {data.get('error', resp.text)}")
        return data

    def models(self) -> list[str]:
        return [m["name"] for m in self._request("GET", "/api/tags", timeout=3).get("models", [])]

    def loaded(self) -> list[str]:
        return [m["name"] for m in self._request("GET", "/api/ps", timeout=3).get("models", [])]

    def has_model(self, model: str) -> bool:
        names = self.models()
        return model in names or f"{model}:latest" in names

    def warm_up(self, model: str, keep_alive: str, timeout: float = 300) -> None:
        """Load the model into memory without generating (a request with no prompt)."""
        self._request("POST", "/api/generate", timeout=timeout,
                      json={"model": model, "keep_alive": keep_alive})

    def chat(self, model: str, system: str, user: str, *, timeout: float, keep_alive: str,
             examples: list[tuple[str, str]] = (), max_tokens: int | None = None) -> str:
        messages = [{"role": "system", "content": system}]
        for example_in, example_out in examples:
            messages += [{"role": "user", "content": example_in},
                         {"role": "assistant", "content": example_out}]
        messages.append({"role": "user", "content": user})
        options: dict = {"temperature": 0}
        if max_tokens:
            options["num_predict"] = max_tokens
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,  # reasoning models (qwen3, deepseek-r1) would be far too slow
            "keep_alive": keep_alive,
            "options": options,
        }
        data = self._request("POST", "/api/chat", timeout=timeout, json=body)
        return data.get("message", {}).get("content", "")
