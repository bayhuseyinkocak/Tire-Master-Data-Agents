"""LLM istemcisi — OpenAI-uyumlu /v1/chat/completions.

Ajan bazlı override → merkezi → kural tabanlı fallback (anahtar yoksa).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class LlmConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout: float = 30.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, fallback: "LlmConfig | None" = None) -> "LlmConfig":
        base = fallback or cls()
        data = data or {}
        api_key_env = str(data.get("apiKeyEnv") or base.api_key_env)
        api_key = os.environ.get(api_key_env) or base.api_key
        return cls(
            base_url=str(data.get("baseUrl") or base.base_url),
            model=str(data.get("model") or base.model),
            api_key=api_key,
            api_key_env=api_key_env,
        )


def chat_completion(
    cfg: LlmConfig,
    system: str,
    messages: list[dict[str, str]],
) -> str | None:
    """Başarıda metin, ağ/anahtar hatasında None (fallback)."""
    if not cfg.api_key:
        return None
    payload = {
        "model": cfg.model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": 0.6,
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return None
