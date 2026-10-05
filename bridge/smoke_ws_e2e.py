"""WS e2e smoke — mock veya gerçek bridge'e bağlanıp BusEvent akışını doğrular.

    uv run python bridge/smoke_ws_e2e.py [ws://127.0.0.1:8788/bus]
"""

from __future__ import annotations

import asyncio
import json
import sys

from websockets.asyncio.client import connect

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8788/bus"


async def drain(ws, seen: list[str], errors: list[str], budget: float = 2.5) -> None:
    """budget süresince gelen tüm mesajları topla."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    while True:
        left = deadline - loop.time()
        if left <= 0:
            return
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=left)
        except (asyncio.TimeoutError, TimeoutError):
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"bozuk JSON: {raw[:60]!r}")
            continue
        if not isinstance(msg, dict) or "type" not in msg:
            errors.append(f"bozuk paket: {raw[:80]!r}")
            continue
        if "ts" not in msg:
            errors.append(f"ts yok: {msg['type']}")
        seen.append(msg["type"])


async def main() -> int:
    seen: list[str] = []
    errors: list[str] = []

    async with connect(URL) as ws:
        await drain(ws, seen, errors, budget=1.5)
        if not seen:
            errors.append("açılışta olay gelmedi")

        await ws.send(
            json.dumps(
                {"type": "user.message", "text": "merhaba", "mentions": ["MICHELIN"], "ts": 0}
            )
        )
        await drain(ws, seen, errors, budget=1.5)

        await ws.send(
            json.dumps(
                {
                    "type": "user.message",
                    "text": "devret CONTI",
                    "mentions": ["MICHELIN", "CONTI"],
                    "ts": 0,
                }
            )
        )
        await drain(ws, seen, errors, budget=2.5)

    types = set(seen)
    for need in ("agent.called", "agent.say", "agent.done"):
        if need not in types:
            errors.append(f"eksik olay: {need}")
    if "agent.subspawn" not in types:
        errors.append("uyarı: subspawn yok (mock değilse / LLM yolunda normal olabilir)")

    hard = [e for e in errors if not e.startswith("uyarı")]
    print(f"URL {URL}")
    print(f"olaylar ({len(seen)}): {', '.join(sorted(types))}")
    if errors:
        print("notlar:")
        for e in errors:
            print(f"  - {e}")
    if hard:
        print("FAIL")
        return 1
    print("smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
