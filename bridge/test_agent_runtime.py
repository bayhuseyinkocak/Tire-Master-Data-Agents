"""K1.5 smoke — AgentRuntime fallback, niyet, araçlar, provider preset.

    uv run python bridge/test_agent_runtime.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_runtime import (  # noqa: E402
    SOURCE_TO_ID,
    AgentRuntime,
    route_intent,
)
from llm import LlmConfig  # noqa: E402

REGISTRY = {
    "pirelli_de": {
        "rol": "toplayici",
        "marka": "Pirelli",
        "son_mesaj": "SKU sayfaları taranıyor...",
        "misyon": [
            {"id": "kesif", "ad": "Sitemap keşfi", "ipucu": "pkw sitemap"},
            {"id": "kazi", "ad": "Sayfaları indir", "ipucu": "SKU HTML"},
        ],
        "persona": "Sen PIRELLI toplayıcısın.",
    },
    "michelin_de": {
        "rol": "toplayici",
        "marka": "Michelin",
        "son_mesaj": "model sayfaları ayrıştırılıyor...",
        "misyon": [{"id": "kesif", "ad": "Sitemap keşfi", "ipucu": "modeller"}],
    },
}


def _say_texts(events: list[dict], agent_id: str | None = None) -> list[str]:
    out = []
    for e in events:
        if e.get("type") != "agent.say":
            continue
        if agent_id and e.get("agentId") != agent_id:
            continue
        out.append(str(e.get("text") or ""))
    return out


def test_smoke(rt: AgentRuntime, errors: list[str]) -> None:
    ev = rt.dispatch_user("merhaba, nasılsın?", ["PIRELLI"])
    types = [e["type"] for e in ev]
    for need in ("agent.called", "agent.thinking", "agent.say", "agent.done"):
        if need not in types:
            errors.append(f"eksik: {need}")
    says = _say_texts(ev, "PIRELLI")
    if not says or ("Pirelli" not in says[0] and "PIRELLI" not in says[0]):
        errors.append(f"fallback ses yok: {says}")

    ev2 = rt.dispatch_user("misyon adımlarını özetle", ["PIRELLI"])
    t2 = [e["type"] for e in ev2]
    if "agent.subspawn" not in t2 or "agent.subdone" not in t2:
        errors.append(f"alt ajan yok: {t2}")
    if not any(e.get("agentId", "").startswith("PIRELLI.") for e in ev2 if e["type"] == "agent.say"):
        errors.append("alt ajan say yok")

    ev3 = rt.dispatch_user("görev: durumu bak", ["MICHELIN"])
    if not any(e["type"] == "agent.say" for e in ev3):
        errors.append("MICHELIN cevap yok")

    turn = rt.reply_turn("PIRELLI", "şu raporu topla", task="rapor topla", from_id="MICHELIN")
    if not any(e["type"] == "agent.task" for e in turn):
        errors.append("agent.task yok")


def test_intents(rt: AgentRuntime, errors: list[str]) -> None:
    cases = {
        "kaç SKU topladın?": "count",
        "kaç kayıt ve eksik var mı?": "count",
        "eksik veri var mı?": "quality",
        "kural ihlali var mı?": "quality",
        "en son ne zaman çalıştın?": "history",
        "kaç kez çalıştın?": "history",
        "durum ne, ne yapıyorsun?": "status",
        "misyon ne?": "status",
        "hata var mı?": "error",
        "merhaba": "hello",
        "selam": "hello",
    }
    for text, want in cases.items():
        got = route_intent(text)
        if got != want:
            errors.append(f"intent {text!r}: {got} != {want}")

    if route_intent("bugün hava nasıl") != "other":
        errors.append("intent other beklenirdi")

    # araç metni — anahtar yok, fallback
    t_count = " ".join(_say_texts(rt.reply_turn("PIRELLI", "kaç SKU topladın?")))
    if "toplam" not in t_count.lower() and "sku" not in t_count.lower():
        errors.append(f"count metni zayıf: {t_count}")

    t_quality = " ".join(_say_texts(rt.reply_turn("PIRELLI", "eksik veri var mı?")))
    if "eksik" not in t_quality.lower() and "kalite" not in t_quality.lower() and "kayıt yok" not in t_quality.lower():
        errors.append(f"quality metni zayıf: {t_quality}")

    t_hist = " ".join(_say_texts(rt.reply_turn("PIRELLI", "en son ne zaman çalıştın?")))
    if "koşu" not in t_hist.lower() and "bitti" not in t_hist.lower() and "yok" not in t_hist.lower():
        errors.append(f"history metni zayıf: {t_hist}")


def test_empty_db(errors: list[str]) -> None:
    rt = AgentRuntime(":memory:", REGISTRY, central_llm=LlmConfig(api_key=None))
    for call, label in (
        (lambda: rt.tools.scrape_status("pirelli_de"), "scrape_status"),
        (lambda: rt.tools.count_skus(), "count_skus"),
        (lambda: rt.tools.count_skus("pirelli_de"), "count_skus_source"),
        (lambda: rt.tools.run_history("pirelli_de"), "run_history"),
        (lambda: rt.tools.data_quality(), "data_quality"),
    ):
        try:
            text = call()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label} exception: {e}")
            continue
        if not isinstance(text, str) or not text:
            errors.append(f"{label} boş metin: {text!r}")

    # boş DB cevabı da kırılmamalı
    says = _say_texts(rt.reply_turn("PIRELLI", "kaç SKU topladın?"))
    if not says:
        errors.append("boş DB fallback yok")


def test_provider_presets(errors: list[str]) -> None:
    os.environ["DEEPSEEK_API_KEY"] = "sk-test-deepseek"
    os.environ["OPENAI_API_KEY"] = "sk-test-openai"

    c = LlmConfig.from_dict({"provider": "deepseek"})
    if c.base_url != "https://api.deepseek.com/v1" or c.model != "deepseek-chat":
        errors.append(f"deepseek preset: {c}")
    if c.api_key_env != "DEEPSEEK_API_KEY" or c.api_key != "sk-test-deepseek":
        errors.append(f"deepseek anahtar: {c}")

    c2 = LlmConfig.from_dict({"provider": "deepseek", "model": "custom-model", "baseUrl": "https://x/v1"})
    if c2.model != "custom-model" or c2.base_url != "https://x/v1":
        errors.append(f"override yok: {c2}")

    c3 = LlmConfig.from_dict({"provider": "mimo", "baseUrl": "https://mimo.local/v1", "model": "m1"})
    if c3.api_key_env != "MIMO_API_KEY" or c3.model != "m1":
        errors.append(f"mimo preset: {c3}")

    c4 = LlmConfig.from_dict({})
    if c4.provider != "openai" or c4.model != "gpt-4o-mini":
        errors.append(f"varsayılan: {c4}")


def main() -> int:
    rt = AgentRuntime(":memory:", REGISTRY, central_llm=LlmConfig(api_key=None))
    errors: list[str] = []

    test_smoke(rt, errors)
    test_intents(rt, errors)
    test_empty_db(errors)
    test_provider_presets(errors)

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("agent_runtime OK — smoke + intent + boş DB + provider preset")
    print("kaynaklar:", ", ".join(SOURCE_TO_ID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
