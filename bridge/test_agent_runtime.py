"""K1 smoke — AgentRuntime fallback konuşma + alt ajan transcript.

    uv run python bridge/test_agent_runtime.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_runtime import AgentRuntime, SOURCE_TO_ID  # noqa: E402
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


def main() -> int:
    # anahtar yok → fallback
    rt = AgentRuntime(":memory:", REGISTRY, central_llm=LlmConfig(api_key=None))
    errors: list[str] = []

    ev = rt.dispatch_user("merhaba, nasılsın?", ["PIRELLI"])
    types = [e["type"] for e in ev]
    for need in ("agent.called", "agent.thinking", "agent.say", "agent.done"):
        if need not in types:
            errors.append(f"eksik: {need}")
    says = [e for e in ev if e["type"] == "agent.say" and e["agentId"] == "PIRELLI"]
    if not says or "Pirelli" not in says[0]["text"] and "PIRELLI" not in says[0]["text"]:
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

    # agent.task
    turn = rt.reply_turn("PIRELLI", "şu raporu topla", task="rapor topla", from_id="MICHELIN")
    if not any(e["type"] == "agent.task" for e in turn):
        errors.append("agent.task yok")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("agent_runtime OK — fallback konuşma + alt ajan + task")
    print("kaynaklar:", ", ".join(SOURCE_TO_ID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
