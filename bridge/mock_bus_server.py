"""Mock Agent Panel WS — Tires DB'siz e2e testi.

Çalıştırma:
    uv run python bridge/mock_bus_server.py
    # ws://127.0.0.1:8788/bus   (gerçek bridge ile çakışmasın)

Senaryo: bağlanınca 3 ajan, user.message → called/thinking/say/done,
2 mention → pair, «devret X» → handoff.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

HOST = "127.0.0.1"
PORT = 8788

AGENTS = ["MICHELIN", "CONTI", "PIRELLI"]


def ev(type_: str, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "ts": int(time.time() * 1000), **payload}


def scenario_for(text: str, mentions: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    lead = mentions[0] if mentions else AGENTS[0]
    helpers = mentions[1:] if mentions else []
    events.append(ev("agent.called", lead=lead, helpers=helpers))

    if len(mentions) == 2:
        events.append(ev("agent.pair", a=mentions[0], b=mentions[1], mode="side"))

    events.append(ev("agent.thinking", agentId=lead, state="thinking"))
    say = f"mock: «{text}»"
    if "devret" in text.lower() or "@" in text:
        target = helpers[0] if helpers else next(a for a in AGENTS if a != lead)
        events.append(ev("agent.say", agentId=lead, text=f"İşi {target} alıyor."))
        events.append(ev("agent.handoff", from_=lead, to=target, task=text))
        events.append(ev("agent.thinking", agentId=target, state="thinking"))
        events.append(ev("agent.say", agentId=target, text="Devraldım."))
        events.append(ev("agent.thinking", agentId=target, state="idle"))
        events.append(ev("agent.done", agentId=target))
    else:
        events.append(ev("agent.say", agentId=lead, text=say))

    events.append(ev("agent.thinking", agentId=lead, state="idle"))
    events.append(ev("agent.done", agentId=lead))
    # wire format: agent.handoff alanı `from` — JSON reserved olmasın diye düzelt
    for e in events:
        if e.get("type") == "agent.handoff" and "from_" in e:
            e["from"] = e.pop("from_")
    return events


async def handler(ws: ServerConnection) -> None:
    hello = [
        ev("agent.called", lead=AGENTS[0], helpers=AGENTS[1:]),
        *[ev("agent.say", agentId=a, text=f"mock {a} hazır.") for a in AGENTS],
        *[ev("agent.done", agentId=a) for a in AGENTS],
    ]
    for e in hello:
        await ws.send(json.dumps(e, ensure_ascii=False))

    async for message in ws:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            continue
        if data.get("type") != "user.message":
            continue
        text = str(data.get("text") or "")
        mentions = list(data.get("mentions") or [])
        # user.message yankı
        await ws.send(json.dumps({**data, "ts": int(time.time() * 1000)}, ensure_ascii=False))
        for e in scenario_for(text, mentions):
            await ws.send(json.dumps(e, ensure_ascii=False))
            await asyncio.sleep(0.05)


async def main() -> None:
    print(f"mock bridge → ws://{HOST}:{PORT}/bus")
    async with serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
