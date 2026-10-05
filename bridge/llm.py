"""LLM istemcisi — OpenAI-uyumlu /v1/chat/completions.

Ajan bazlı override → merkezi → kural tabanlı fallback (anahtar yoksa).
provider sadece şablon açar; baseUrl / model / apiKeyEnv her zaman override edilebilir.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# provider preset → (baseUrl, apiKeyEnv, model). Boş alan = kullanıcı doldurur.
PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "baseUrl": "https://api.openai.com/v1",
        "apiKeyEnv": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "baseUrl": "https://api.deepseek.com/v1",
        "apiKeyEnv": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "mimo": {
        "baseUrl": "",
        "apiKeyEnv": "MIMO_API_KEY",
        "model": "",
    },
    "openrouter": {
        "baseUrl": "https://openrouter.ai/api/v1",
        "apiKeyEnv": "OPENROUTER_API_KEY",
        "model": "",
    },
    "custom": {
        "baseUrl": "https://api.openai.com/v1",
        "apiKeyEnv": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
}


@dataclass
class LlmConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout: float = 30.0
    provider: str = "openai"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, fallback: "LlmConfig | None" = None) -> "LlmConfig":
        """provider şablon açar; baseUrl / model / apiKeyEnv her zaman override edilebilir."""
        base = fallback or cls()
        data = data or {}
        provider = str(data.get("provider") or "").strip().lower()
        preset: dict[str, str] = PROVIDERS.get(provider, {}) if provider else {}

        api_key_env = str(data.get("apiKeyEnv") or preset.get("apiKeyEnv") or base.api_key_env)
        api_key = os.environ.get(api_key_env) or base.api_key
        return cls(
            base_url=str(data.get("baseUrl") or preset.get("baseUrl") or base.base_url),
            model=str(data.get("model") or preset.get("model") or base.model),
            api_key=api_key,
            api_key_env=api_key_env,
            provider=provider or base.provider,
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
