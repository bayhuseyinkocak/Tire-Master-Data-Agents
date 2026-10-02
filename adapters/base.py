"""Ortak ajan protokolü.

Her kaynak site kendi paketinde (adapters/<kaynak>/agent.py, parse.py) bu
protokolü uygular. BaseAgent: nazik tarama, ham sayfa saklama (asla silinmez),
scrape_run loglama ve SQLite'a yazım sağlar. Siteye özgü akıl alt sınıfta.
"""

from __future__ import annotations

import abc
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import httpx

RATE_LIMIT_SECONDS = 1.0
USER_AGENT = "TiresMasterData-Scout/0.1 (+contact: local research project)"


@dataclass
class SkuRecord:
    """Bir ebat varyantı için normalize edilmiş ortak kayıt."""
    brand: str
    model: str
    season: str | None = None           # summer / winter / allseason
    vehicle_type: str | None = None
    width: int | None = None
    aspect_ratio: int | None = None
    rim_diameter: int | None = None
    load_index: str | None = None
    speed_index: str | None = None
    xl: bool = False
    runflat: bool = False
    ean: str | None = None
    cai: str | None = None
    upc: str | None = None
    structure: str | None = None
    position: str | None = None
    tread_pattern: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    axle_position: str | None = None
    tyre_type: str | None = None
    tire_weight: float | None = None
    tread_depth: float | None = None
    max_load: float | None = None
    max_speed: int | None = None
    silence: bool | None = None
    sealant: bool | None = None
    oe_manufacture: str | None = None
    eprel_reg_no: str | None = None
    label_url: str | None = None
    fuel_class: str | None = None       # EU etiketi
    wet_grip_class: str | None = None
    noise_db: int | None = None
    noise_class: str | None = None
    snow_grip: bool = False             # 3PMSF
    ice_grip: bool = False
    m_s: bool = False                   # M+S
    stud: bool = False
    type_tube: str | None = None        # 'TL' / 'TT'
    is_green: bool = False
    is_ev_compatible: bool = False
    regrooving: dict | None = None
    price_eur: float | None = None
    source_url: str | None = None
    model_description: str | None = None
    model_headline: str | None = None
    image_urls: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class BaseAgent(abc.ABC):
    """Kaynak başına scraper ajanı."""

    source_name: str  # örn. 'michelin_de'

    def __init__(self, project_root: Path, db_path: Path, delay: float = RATE_LIMIT_SECONDS):
        if not self.source_name:
            raise ValueError("source_name tanımlanmalı")
        self.project_root = project_root
        self.raw_dir = project_root / "raw" / self.source_name / date.today().isoformat()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.delay = delay
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
        )
        self._last_request = 0.0
        self.stats = {"pages": 0, "records": 0, "errors": 0,
                      "skipped_404": 0, "skipped_empty": 0}

    # --- site-specific hooks -------------------------------------------------

    @abc.abstractmethod
    def discover_urls(self) -> list[str]:
        """Kazınacak sayfa URL listesi (tipik: sitemap'ten)."""

    @abc.abstractmethod
    def parse(self, html: str, url: str) -> list[SkuRecord]:
        """Ham sayfayı ortak SkuRecord listesine çevirir."""

    # --- shared plumbing -----------------------------------------------------

    def fetch(self, url: str) -> str:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        resp = self._client.get(url)
        resp.raise_for_status()
        self._last_request = time.monotonic()
        self.stats["pages"] += 1
        return resp.text

    def save_raw(self, url: str, html: str) -> Path:
        name = url.rstrip("/").rsplit("/", 1)[-1] or "index"
        path = self.raw_dir / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        return path

    def download_image(self, url: str, brand: str, model: str, source_name: str | None = None) -> str | None:
        """Görseli raw/images/<brand>/<model>/<source>/ altına indirir. Göreli yol döner."""
        src = source_name or self.source_name
        out_dir = (self.project_root / "raw" / "images" / brand.replace("/", "-")
                   / (model or "unknown").replace("/", "-") / src)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or "image"
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")):
            name = name + ".img"
        path = out_dir / name
        if not path.exists():
            resp = self._client.get(url)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        return str(path.relative_to(self.project_root))

    def run(self) -> None:
        run_id = self._start_run()
        try:
            for url in self.discover_urls():
                try:
                    html = self.fetch(url)
                    self.save_raw(url, html)
                    records = self.parse(html, url)
                    self._persist(records)
                    self.stats["records"] += len(records)
                except Exception:  # noqa: BLE001 - koşu durmamalı
                    self.stats["errors"] += 1
        finally:
            self._finish_run(run_id)

    def _start_run(self) -> int:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO scrape_run (source_id, status) "
                "VALUES ((SELECT id FROM source WHERE name = ?), 'running')",
                (self.source_name,),
            )
            return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _finish_run(self, run_id: int) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "UPDATE scrape_run SET finished_at = CURRENT_TIMESTAMP, "
                "records_in = ?, errors = ?, status = ? WHERE id = ?",
                (
                    self.stats["records"],
                    self.stats["errors"],
                    "ok" if self.stats["errors"] == 0 else "partial",
                    run_id,
                ),
            )

    def _persist(self, records: list[SkuRecord]) -> None:
        # Faz 1'de brand/model/size_variant/eu_label yazımı burada
        raise NotImplementedError("DB yazımı schema.sql uygulandığında gelecek")


def parse_astro_island_props(html: str) -> list[dict]:
    """Astro SSR sayfalarında gömülü island props JSON'unu çıkarır.

    Michelin tarzı siteler: &quot; escape'i ve [0, value] tuple formatı.
    """
    import html as html_mod

    from parsel import Selector

    sel = Selector(html_mod.unescape(html.replace("&quot;", '"')))
    props = sel.css("astro-island::attr(props)").getall()
    out = []
    for p in props:
        try:
            out.append(json.loads(p))
        except json.JSONDecodeError:
            continue
    return out
