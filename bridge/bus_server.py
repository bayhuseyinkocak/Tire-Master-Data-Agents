"""Agent Panel WS bridge — scrape_run + registry → BusEvent.

Çalıştırma:
    uv run python bridge/bus_server.py
    # ws://127.0.0.1:8787/bus

Agent Panel: Ayarlar → Tires Master Data → transport: ws → Bağlan.

Gelen mesajlar BusEvent JSON (ts ekli). report_progress note'ları agent.say olur.
Panel süreç başlatmaz; user.message'a durum özetiyle cevap verir.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from websockets.asyncio.server import ServerConnection, serve

from agent_runtime import AgentRuntime, bus_event, now_ms
from llm import LlmConfig

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "tires.db"
REGISTRY_PATH = ROOT / "agents_registry.yaml"
HOST = "127.0.0.1"
PORT = 8787

# registry/source adı → panel paketindeki agent id
SOURCE_TO_ID = {
    "michelin_de": "MICHELIN",
    "continental_de": "CONTI",
    "pirelli_de": "PIRELLI",
}

THINK = {
    "MICHELIN": "thinking",
    "CONTI": "alert",
    "PIRELLI": "swirl",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def bus_event(type_: str, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "ts": now_ms(), **payload}


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def latest_runs(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """source_name → son scrape_run satırı."""
    try:
        rows = conn.execute(
            """
            SELECT r.id, s.name AS source, r.started_at, r.finished_at,
                   r.records_in, r.errors, r.status,
                   r.pages_done, r.pages_total, r.note, r.pid
            FROM scrape_run r
            JOIN source s ON s.id = r.source_id
            WHERE r.id IN (
                SELECT MAX(r2.id) FROM scrape_run r2 GROUP BY r2.source_id
            )
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {r["source"]: dict(r) for r in rows}


def status_line(agent_id: str, run: dict[str, Any] | None) -> str:
    if not run:
        return f"{agent_id}: henüz scrape_run yok."
    done = run.get("pages_done") or 0
    total = run.get("pages_total") or 0
    note = run.get("note") or ""
    records = run.get("records_in") or 0
    errors = run.get("errors") or 0
    if run.get("finished_at"):
        return f"Bitti: {records} kayıt, {errors} hata."
    if total:
        return note or f"{done}/{total} sayfa…"
    return note or "koşu açık…"


class Bridge:
    def __init__(self) -> None:
        self.clients: set[ServerConnection] = set()
        self.registry = load_registry()
        self.runtime = AgentRuntime(
            DB_PATH,
            self.registry,
            central_llm=LlmConfig.from_dict(self.registry.get("_llm") or {}),
        )
        self._seen: dict[str, tuple[Any, ...]] = {}
        self._announced: set[str] = set()

    async def handler(self, ws: ServerConnection) -> None:
        self.clients.add(ws)
        try:
            await self.send(ws, self.snapshot_events())
            async for message in ws:
                await self.on_client_message(message)
        finally:
            self.clients.discard(ws)

    async def send(self, ws: ServerConnection, events: list[dict[str, Any]]) -> None:
        for event in events:
            await ws.send(json.dumps(event, ensure_ascii=False))

    async def broadcast(self, events: list[dict[str, Any]]) -> None:
        if not events or not self.clients:
            return
        payload = [json.dumps(e, ensure_ascii=False) for e in events]
        dead: list[ServerConnection] = []
        for ws in self.clients:
            try:
                for raw in payload:
                    await ws.send(raw)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def agent_ids(self) -> list[str]:
        return list(SOURCE_TO_ID.values())

    def snapshot_events(self) -> list[dict[str, Any]]:
        """Yeni istemciye mevcut durum."""
        events: list[dict[str, Any]] = []
        ids = self.agent_ids()
        events.append(bus_event("agent.called", lead=ids[0] if ids else "", helpers=ids[1:]))
        try:
            conn = connect_db()
        except sqlite3.Error:
            return events
        try:
            runs = latest_runs(conn)
        finally:
            conn.close()
        for source, agent_id in SOURCE_TO_ID.items():
            run = runs.get(source)
            events.append(bus_event("agent.thinking", agentId=agent_id, state=THINK.get(agent_id, "thinking")))
            events.append(bus_event("agent.say", agentId=agent_id, text=status_line(agent_id, run)))
            events.append(bus_event("agent.done", agentId=agent_id))
        return events

    async def on_client_message(self, message: str | bytes) -> None:
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(data, dict) or data.get("type") != "user.message":
            return
        mentions = list(data.get("mentions") or [])
        text = str(data.get("text") or "")
        await self.broadcast(self.runtime.dispatch_user(text, mentions))

    def poll_events(self) -> list[dict[str, Any]]:
        """scrape_run değişimini BusEvent’e çevir."""
        events: list[dict[str, Any]] = []
        try:
            conn = connect_db()
        except sqlite3.Error:
            return events
        try:
            runs = latest_runs(conn)
        finally:
            conn.close()

        for source, agent_id in SOURCE_TO_ID.items():
            run = runs.get(source)
            if not run:
                continue
            fp = (
                run.get("id"),
                run.get("note"),
                run.get("pages_done"),
                run.get("finished_at"),
            )
            if self._seen.get(source) == fp:
                continue
            first = source not in self._seen
            self._seen[source] = fp

            if first and not run.get("finished_at"):
                events.append(bus_event("agent.called", lead=agent_id, helpers=[]))
                self._announced.add(source)

            events.append(
                bus_event("agent.thinking", agentId=agent_id, state=THINK.get(agent_id, "thinking"))
            )
            events.append(
                bus_event("agent.say", agentId=agent_id, text=status_line(agent_id, run))
            )
            if run.get("finished_at"):
                events.append(bus_event("agent.thinking", agentId=agent_id, state="idle"))
                events.append(bus_event("agent.done", agentId=agent_id))
        return events

    async def poll_loop(self) -> None:
        while True:
            await asyncio.sleep(0.6)
            await self.broadcast(self.poll_events())


async def main() -> None:
    bridge = Bridge()
    print(f"Agent Panel bridge → ws://{HOST}:{PORT}/bus  (db={DB_PATH})")
    async with serve(bridge.handler, HOST, PORT):
        await bridge.poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
