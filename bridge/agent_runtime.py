"""Konuşan ajan çalışma zamanı — persona + araçlar + alt ajan transcript.

K1: sadece konuşur (status/DB okur). start_run K2.
Alt ajanlar şimdilik transcript; ileride ayrı avatar.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from llm import LlmConfig, chat_completion

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

# Niyet → tetik kelimeleri (TR, küçük harf). Tablo sırası = öncelik (count → quality).
INTENT_TRIGGERS: list[tuple[str, tuple[str, ...]]] = [
    ("count", ("kaç", "adet", "sku", "ürün", "topladın", "kayıt sayısı", "kac", "urun")),
    ("quality", ("eksik", "boş", "kalite", "validate", "kural", "ihlal", "bosluk")),
    ("history", ("ne zaman", "en son", "son koşu", "kaç kez", "kaç kere", "history", "geçmiş")),
    ("status", ("durum", "çalışıyor", "ilerleme", "ne yapıyorsun", "misyon", "görev", "calisiyor")),
    ("error", ("hata", "error", "patladı", "patladi")),
    ("hello", ("merhaba", "selam", "nasılsın", "naber", "nasilsin")),
]

# Daha spesifik çok-kelime kalıplar — kısa "kaç" gibi kelimelerden önce.
INTENT_SPECIFIC: list[tuple[str, tuple[str, ...]]] = [
    ("history", ("kaç kez", "kaç kere", "ne zaman", "en son", "son koşu")),
    ("quality", ("eksik veri", "kural ihlal")),
    ("status", ("ne yapıyorsun", "ne yapiyorsun")),
]


def route_intent(text: str) -> str:
    """Tek intent: spesifik kalıp, sonra tablo sırası (count → quality → …)."""
    t = (text or "").lower()
    for intent, words in INTENT_SPECIFIC:
        if any(w in t for w in words):
            return intent
    for intent, words in INTENT_TRIGGERS:
        if any(w in t for w in words):
            return intent
    return "other"


def secondary_hint(text: str, primary: str) -> str:
    """Çok intent tek cümlede: ilk kazanır, ikincisine davet."""
    t = (text or "").lower()
    if primary != "quality" and any(w in t for w in ("eksik", "kalite", "kural", "ihlal")):
        return " İstersen eksik veriye de bakayım."
    if primary != "count" and any(w in t for w in ("adet", "sku", "ürün", "topladın", "kayıt sayısı")):
        return " İstersen SKU sayısına da bakayım."
    if primary != "history" and any(w in t for w in ("ne zaman", "en son", "kaç kez")):
        return " İstersen koşu geçmişine de bakayım."
    return ""


def _clip_sentence(text: str) -> str:
    """Araç metninde çift nokta olmasın."""
    return (text or "").strip().rstrip(".")

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


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip().replace("T", " ")
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:26] if "." in s else s[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _fmt_ts(value: Any) -> str:
    dt = _parse_ts(value)
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M")
    s = str(value or "").strip()
    return s[:16] if s else "-"


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
    """K1.5 araçları — salt okuma DB. start_run / yazma bilerek yok."""

    def __init__(self, db_path, registry: dict[str, Any]) -> None:
        self.db_path = db_path
        self.registry = registry

    def _connect(self) -> sqlite3.Connection | None:
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    def _brand_name(self, source: str | None) -> str | None:
        if not source:
            return None
        meta = self.registry.get(source) or {}
        name = str(meta.get("marka") or "").strip()
        if name:
            return name
        # michelin_de → Michelin
        slug = source.split("_")[0]
        return slug[:1].upper() + slug[1:] if slug else source

    def scrape_status(self, source: str) -> str:
        conn = self._connect()
        if conn is None:
            return "db hatası: bağlanılamadı."
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
        except sqlite3.OperationalError:
            return "henüz scrape_run yok."
        except sqlite3.Error:
            return "scrape_run okunamadı."
        finally:
            conn.close()
        if not row:
            return "henüz scrape_run yok."
        d = dict(row)
        records = d.get("records_in")
        errors = d.get("errors")
        status = d.get("status") or "-"
        if d.get("finished_at"):
            return (
                f"bitti · {records if records is not None else 0} kayıt · "
                f"{errors if errors is not None else 0} hata · status={status} · "
                f"{_fmt_ts(d.get('finished_at'))}"
            )
        done, total = d.get("pages_done") or 0, d.get("pages_total") or 0
        progress = f"{done}/{total} sayfa" if total else (f"{done} sayfa" if done else "koşu açık")
        return f"çalışıyor · {progress} · note={d.get('note') or '-'} · başladı {_fmt_ts(d.get('started_at'))}"

    def count_skus(self, source: str | None = None) -> str:
        conn = self._connect()
        if conn is None:
            return "db hatası: bağlanılamadı."
        try:
            total = conn.execute("SELECT COUNT(*) FROM size_variant").fetchone()[0]
            rows = conn.execute(
                """
                SELECT b.name AS brand, COUNT(*) AS n
                FROM size_variant v
                JOIN tire_model m ON m.id = v.model_id
                JOIN brand b ON b.id = m.brand_id
                GROUP BY b.name
                ORDER BY n DESC, b.name
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return "henüz SKU yok."
        except sqlite3.Error:
            return "SKU sayılamadı."
        finally:
            conn.close()

        by_brand = [(str(r["brand"]), int(r["n"])) for r in rows]
        if source:
            brand = self._brand_name(source)
            n = next((c for b, c in by_brand if b.lower() == (brand or "").lower()), 0)
            label = brand or source
            return f"{label} {n} · toplam {total}"
        if not by_brand:
            return f"toplam {total} | (marka kırılımı yok)"
        parts = " · ".join(f"{b} {c}" for b, c in by_brand)
        return f"toplam {total} | {parts}"

    def run_history(self, source: str, limit: int = 3) -> str:
        conn = self._connect()
        if conn is None:
            return "db hatası: bağlanılamadı."
        try:
            rows = conn.execute(
                """
                SELECT r.started_at, r.finished_at, r.records_in, r.errors, r.status
                FROM scrape_run r JOIN source s ON s.id = r.source_id
                WHERE s.name = ?
                ORDER BY r.id DESC LIMIT ?
                """,
                (source, max(1, int(limit))),
            ).fetchall()
        except sqlite3.OperationalError:
            return "henüz koşu yok."
        except sqlite3.Error:
            return "koşu geçmişi okunamadı."
        finally:
            conn.close()
        if not rows:
            return "henüz koşu yok."
        parts = []
        for r in rows:
            d = dict(r)
            when = _fmt_ts(d.get("finished_at") or d.get("started_at"))
            state = "bitti" if d.get("finished_at") else "açık"
            records = d.get("records_in")
            errors = d.get("errors")
            status = d.get("status") or "-"
            parts.append(
                f"{when} {state} {records if records is not None else 0} kayıt "
                f"{errors if errors is not None else 0} hata {status}"
            )
        return " | ".join(parts)

    def data_quality(self) -> str:
        try:
            from normalize import validate
        except ImportError:
            return "validate modülü bulunamadı."
        try:
            summary = validate.collect(self.db_path)
        except Exception:
            return "kalite özeti okunamadı (şema henüz olmayabilir)."
        missing = summary.get("missing") or {}
        counts = summary.get("counts") or {}
        if not counts.get("size_variant"):
            return "henüz kayıt yok; kalite özeti için veri gerek."
        issues = summary.get("total_issues") or 0
        bad = [r for r in (summary.get("rules") or []) if not r.get("ok") and r.get("count")]
        top = ", ".join(f"{r['label']}: {r['count']}" for r in bad[:3])
        tail = f" ({top})" if top else ""
        return (
            f"eksik EAN {missing.get('ean') or 0} · "
            f"eksik ebat {missing.get('size') or 0} · "
            f"eksik etiket {missing.get('label') or 0} · "
            f"kural ihlali {issues}{tail}"
        )

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
            "Araç özetlerindeki sayı ve tarihleri aynen kullan; uydurma. "
            "Bilmiyorsan 'kayıtta yok' de.\n"
            "Yanıtın 1-3 cümle olsun. start_run başlatamazsın (K2); yazma aracı yok."
        )

    def _tool_context(self, p: AgentPersona) -> str:
        """Her turda tüm araç özetleri — LLM ve fallback aynı veriyi görsün."""
        return (
            f"scrape_status({p.source}): {self.tools.scrape_status(p.source)}\n"
            f"count_skus: {self.tools.count_skus()}\n"
            f"count_skus({p.source}): {self.tools.count_skus(p.source)}\n"
            f"data_quality: {self.tools.data_quality()}\n"
            f"run_history({p.source}): {self.tools.run_history(p.source)}"
        )

    def _llm_for(self, p: AgentPersona) -> LlmConfig:
        if p.llm:
            return LlmConfig.from_dict(p.llm, fallback=self.central_llm)
        return self.central_llm

    def _fallback_say(self, p: AgentPersona, user_text: str) -> str:
        status = _clip_sentence(self.tools.scrape_status(p.source))
        skus = _clip_sentence(self.tools.count_skus())
        quality = _clip_sentence(self.tools.data_quality())
        history = _clip_sentence(self.tools.run_history(p.source, limit=3))
        seed = p.last_message or f"{p.brand} hattı açık."
        intent = route_intent(user_text)
        hint = secondary_hint(user_text, intent)

        if intent == "count":
            mine = _clip_sentence(self.tools.count_skus(p.source))
            return f"{p.brand}: {skus} · bende {mine}.{hint}"
        if intent == "quality":
            return f"{p.brand}: {quality}.{hint}"
        if intent == "history":
            return f"{p.brand}: {history} · şu an: {status}.{hint}"
        if intent == "status":
            return f"{p.brand}: {status} · {skus}. Misyon: {self.tools.mission_lines(p)}.{hint}"
        if intent == "error":
            return f"{p.brand}: {status} · {quality}.{hint}"
        if intent == "hello":
            return f"Buradayım — {p.brand}. {seed} Şu an: {status}.{hint}"
        return f"{p.brand}: {seed} ({status} · {skus}){hint}"

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

        context = self._tool_context(p)
        messages = [
            *hist[:-1],
            {"role": "user", "content": f"[araçlar]\n{context}\n[soru]\n{user_text}"},
        ]
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
