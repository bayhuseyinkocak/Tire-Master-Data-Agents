"""Konuşan ajan çalışma zamanı — persona + araçlar + alt ajan transcript.

K1: sadece konuşur (status/DB okur). start_run K2.
Alt ajanlar şimdilik transcript; ileride ayrı avatar.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from llm import LlmConfig, chat_completion

SOURCE_TO_ID = {
    "michelin_de": "MICHELIN",
    "continental_de": "CONTI",
    "pirelli_de": "PIRELLI",
}
ID_TO_SOURCE = {v: k for k, v in SOURCE_TO_ID.items()}

THINK = {
    "MICHELIN": "thinking",
    "CONTI": "alert",
    "PIRELLI": "swirl",
}

# misyon adımı = alt ajan kimliği (şimdilik transcript)
STEP_SLUG = {
    "kesif": "KESIF",
    "kazi": "KAZI",
    "parse": "PARSE",
    "dogrulama": "VALIDATE",
    "teslim": "TESLIM",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def bus_event(type_: str, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "ts": now_ms(), **payload}


@dataclass
class AgentPersona:
    id: str
    source: str
    role: str
    brand: str
    mission: list[dict[str, Any]] = field(default_factory=list)
    last_message: str = ""
    llm: dict[str, Any] | None = None
    persona: str = ""


class Tools:
    """K1 araçları — salt okuma. start_run bilerek yok."""

    def __init__(self, db_path, registry: dict[str, Any]) -> None:
        self.db_path = db_path
        self.registry = registry

    def scrape_status(self, source: str) -> str:
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            return f"db hatası: {e}"
        try:
            row = conn.execute(
                """
                SELECT r.id, r.started_at, r.finished_at, r.records_in, r.errors, r.status,
                       r.pages_done, r.pages_total, r.note
                FROM scrape_run r JOIN source s ON s.id = r.source_id
                WHERE s.name = ? ORDER BY r.id DESC LIMIT 1
                """,
                (source,),
            ).fetchone()
        except sqlite3.Error:
            return "scrape_run okunamadı (şema henüz olmayabilir)."
        finally:
            conn.close()
        if not row:
            return "henüz scrape_run yok."
        d = dict(row)
        done, total = d.get("pages_done") or 0, d.get("pages_total") or 0
        if d.get("finished_at"):
            return f"bitti · {d.get('records_in') or 0} kayıt · {d.get('errors') or 0} hata · status={d.get('status')}"
        return f"çalışıyor · {done}/{total} · note={d.get('note') or '-'}"

    def count_skus(self) -> str:
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            n = conn.execute("SELECT COUNT(*) FROM size_variant").fetchone()[0]
            conn.close()
            return f"size_variant: {n}"
        except sqlite3.Error:
            return "size_variant sayılamadı."

    def mission_lines(self, persona: AgentPersona) -> str:
        parts = []
        for step in persona.mission:
            slug = STEP_SLUG.get(str(step.get("id")), str(step.get("id")))
            parts.append(f"{slug} — {step.get('ad', '')}")
        return " | ".join(parts) if parts else "(misyon yok)"


class AgentRuntime:
    def __init__(self, db_path, registry: dict[str, Any], central_llm: LlmConfig | None = None) -> None:
        self.tools = Tools(db_path, registry)
        self.registry = registry
        self.central_llm = central_llm or LlmConfig()
        self.history: dict[str, list[dict[str, str]]] = {}
        self.personas = self._load_personas()

    def _load_personas(self) -> dict[str, AgentPersona]:
        out: dict[str, AgentPersona] = {}
        for source, meta in self.registry.items():
            agent_id = SOURCE_TO_ID.get(source)
            if not agent_id:
                continue
            out[agent_id] = AgentPersona(
                id=agent_id,
                source=source,
                role=str(meta.get("rol", "toplayıcı")),
                brand=str(meta.get("marka", source)),
                mission=list(meta.get("misyon") or []),
                last_message=str(meta.get("son_mesaj") or ""),
                llm=meta.get("llm"),
                persona=str(meta.get("persona") or ""),
            )
        return out

    def think_state(self, agent_id: str) -> str:
        return THINK.get(agent_id, "thinking")

    def system_prompt(self, p: AgentPersona) -> str:
        custom = p.persona or (
            f"Sen {p.brand} lastik master verisi toplayan {p.id} ajanısın. "
            f"Rolün: {p.role}. Kısa, net Türkçe konuş; abartma."
        )
        return (
            f"{custom}\n"
            f"Kaynak: {p.source}. Misyon: {self.tools.mission_lines(p)}.\n"
            f"Bugün şunları biliyorsun (araçlarla tazele):\n"
            f"- scrape_status({p.source})\n"
            f"- count_skus()\n"
            "Yanıtın 1-3 cümle olsun. start_run başlatamazsın (K2)."
        )

    def _llm_for(self, p: AgentPersona) -> LlmConfig:
        if p.llm:
            return LlmConfig.from_dict(p.llm, fallback=self.central_llm)
        return self.central_llm

    def _fallback_say(self, p: AgentPersona, user_text: str) -> str:
        status = self.tools.scrape_status(p.source)
        skus = self.tools.count_skus()
        seed = p.last_message or f"{p.brand} hattı açık."
        text = user_text.lower()
        if any(w in text for w in ("merhaba", "selam", "nasıl", "naber")):
            return f"Buradayım — {p.brand}. {seed} Şu an: {status}."
        if any(w in text for w in ("görev", "ne yapıyorsun", "durum", "ilerleme")):
            return f"{p.brand}: {status} · {skus}. Misyon: {self.tools.mission_lines(p)}."
        return f"{p.brand}: {seed} ({status})"

    def _maybe_subagents(self, p: AgentPersona, user_text: str) -> list[dict[str, Any]]:
        """Konuşmada adım geçiyorsa alt ajan transcript'i (K1)."""
        events: list[dict[str, Any]] = []
        text = user_text.lower()
        for step in p.mission:
            sid = str(step.get("id") or "")
            ad = str(step.get("ad") or "")
            slug = STEP_SLUG.get(sid, sid.upper())
            if not slug:
                continue
            hit = sid.lower() in text or (bool(ad) and ad.lower()[:6] in text)
            if not hit and not any(k in text for k in ("misyon", "adım", "tümü", "hepsi")):
                continue
            child = f"{p.id}.{slug}"
            events.append(bus_event("agent.subspawn", parent=p.id, child=child, step=ad or slug))
            events.append(
                bus_event(
                    "agent.say",
                    agentId=child,
                    text=f"{ad or slug}: {step.get('ipucu', '…')} — {self.tools.scrape_status(p.source)}",
                )
            )
            events.append(
                bus_event(
                    "agent.subdone",
                    parent=p.id,
                    child=child,
                    step=ad or slug,
                    summary=self.tools.scrape_status(p.source),
                )
            )
            # K1: ilk 2 adım yeterli
            if len(events) >= 9:
                break
        return events

    def reply_turn(
        self,
        agent_id: str,
        user_text: str,
        task: str | None = None,
        from_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Bir konuşma turu → BusEvent listesi."""
        p = self.personas.get(agent_id) or self.personas.get(agent_id.upper())
        if not p:
            return [
                bus_event("agent.say", agentId=agent_id, text="Bu ajan pakette tanımlı değil."),
                bus_event("agent.done", agentId=agent_id),
            ]

        events: list[dict[str, Any]] = []
        if task and from_id:
            events.append(bus_event("agent.task", **{"from": from_id, "to": p.id, "goal": task}))

        events.append(bus_event("agent.thinking", agentId=p.id, state=self.think_state(p.id)))

        if from_id:
            user_text = f"{from_id} sordu: {user_text}"

        hist = self.history.setdefault(p.id, [])
        hist.append({"role": "user", "content": user_text})
        if len(hist) > 12:
            del hist[:-12]

        context = (
            f"scrape_status: {self.tools.scrape_status(p.source)}\n"
            f"count_skus: {self.tools.count_skus()}"
        )
        messages = [*hist[:-1], {"role": "user", "content": f"[araçlar]\n{context}\n[soru]\n{user_text}"}]
        text = chat_completion(self._llm_for(p), self.system_prompt(p), messages)
        if not text:
            text = self._fallback_say(p, user_text)

        hist.append({"role": "assistant", "content": text})
        say_extra = {"to": from_id} if from_id else {}
        events.append(bus_event("agent.say", agentId=p.id, text=text.strip(), **say_extra))
        events.append(bus_event("agent.thinking", agentId=p.id, state="idle"))
        events.append(bus_event("agent.done", agentId=p.id))
        events.extend(self._maybe_subagents(p, user_text))
        return events

    def dispatch_user(self, text: str, mentions: list[str]) -> list[dict[str, Any]]:
        ids = [m for m in mentions if m in self.personas]
        if not ids:
            ids = list(self.personas.keys())[:1]
        lead, helpers = ids[0], ids[1:]
        events: list[dict[str, Any]] = [bus_event("agent.called", lead=lead, helpers=helpers)]
        for i, agent_id in enumerate(ids):
            events.extend(self.reply_turn(agent_id, text))
            _ = i
        return events
