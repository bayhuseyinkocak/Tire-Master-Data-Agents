"""Pirelli DE ajanı: sitemap'ten SKU sayfaları → SQLite."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

from adapters.base import BaseAgent, ensure_progress_columns
from adapters.pirelli_de.parse_pirelli import parse

SITEMAP_INDEX = "https://www.pirelli.com/tyres/de-de/sitemap_index_tyres_de-de.xml"
SITEMAP_PKW = "https://www.pirelli.com/tyres/de-de/sitemap_pkw_de-de.xml"
SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "db" / "schema.sql"


class PirelliDeAgent(BaseAgent):
    source_name = "pirelli_de"
    base_url = "https://www.pirelli.com"

    def discover_urls(self) -> list[str]:
        idx = self.fetch(SITEMAP_INDEX)
        urls = []
        for child in re.findall(r"<loc>([^<]+sitemap_pkw_de-de[^<]*\.xml)</loc>", idx):
            txt = self.fetch(child)
            urls.extend(re.findall(r"<loc>(https://www\.pirelli\.com/tyres/de-de/pkw/reifenkatalog/produkt/[^<]+)</loc>", txt))
        return sorted(set(urls))

    def parse(self, html: str, url: str):
        return parse(html, url)

    def save_raw(self, url: str, html_text: str) -> None:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        (self.raw_dir / f"{slug}.html").write_text(html_text, encoding="utf-8")

    def _ensure_schema(self, cur: sqlite3.Cursor) -> None:
        def addcol(table: str, col: str, typedef: str) -> None:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
            if col not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")

        addcol("eu_label", "m_s", "BOOLEAN")
        ensure_progress_columns(cur.connection)
        cur.execute("""CREATE TABLE IF NOT EXISTS variant_attributes (
            id INTEGER PRIMARY KEY,
            size_variant_id INTEGER NOT NULL UNIQUE REFERENCES size_variant(id),
            m_s BOOLEAN, stud BOOLEAN, type_tube TEXT,
            is_green BOOLEAN, is_ev_compatible BOOLEAN,
            regrooving TEXT, extra TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS source_image (
            id INTEGER PRIMARY KEY,
            size_variant_id INTEGER REFERENCES size_variant(id),
            model_id INTEGER REFERENCES tire_model(id),
            source_id INTEGER REFERENCES source(id),
            url TEXT NOT NULL, kind TEXT, local_path TEXT,
            UNIQUE (url))""")

    def run(self, limit: int | None = None) -> None:
        self.stats.setdefault("skipped_404", 0)
        self.stats.setdefault("skipped_empty", 0)
        conn = sqlite3.connect(self.db_path, timeout=30)
        cur = conn.cursor()
        with open(SCHEMA, encoding="utf-8") as f:
            conn.executescript(f.read())
        self._ensure_schema(cur)
        cur.execute(
            "INSERT OR IGNORE INTO source (name, type, base_url) VALUES (?, 'brand_site', ?)",
            (self.source_name, self.base_url),
        )
        source_id = cur.execute(
            "SELECT id FROM source WHERE base_url=?", (self.base_url,)).fetchone()[0]
        cur.execute("INSERT INTO scrape_run (source_id) VALUES (?)", (source_id,))
        run_id = cur.lastrowid
        self._run_id = run_id
        ensure_progress_columns(conn)
        conn.commit()

        self.report_progress(0, 0, "sitemap keşfi...")
        urls = self.discover_urls()
        print(f"{len(urls)} SKU URL'si bulundu")
        if limit:
            urls = urls[:limit]
        total = len(urls)
        self.report_progress(0, total, f"{total} SKU URL'si keşfedildi")

        for i, url in enumerate(urls, 1):
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            self.report_progress(i - 1, total, f"{i}/{total} — {slug}")
            try:
                html = self.fetch(url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    self.stats["skipped_404"] += 1
                else:
                    print(f"HATA {url}: {e}")
                    self.stats["errors"] += 1
                self.report_progress(i, total, f"404: {slug}")
                continue
            except Exception as e:  # noqa: BLE001
                print(f"HATA {url}: {e}")
                self.stats["errors"] += 1
                self.report_progress(i, total, f"hata: {slug}")
                continue
            self.save_raw(url, html)
            self.stats["pages"] += 1

            records = [r for r in self.parse(html, url) if r.ean]
            if not records:
                self.stats["skipped_empty"] += 1
                self.report_progress(i, total, f"{i}/{total} boş sayfa: {slug}")
                continue

            for r in records:
                cur.execute("INSERT OR IGNORE INTO brand (name, site_url) VALUES (?, ?)",
                            (r.brand, self.base_url))
                brand_id = cur.execute("SELECT id FROM brand WHERE name=?",
                                       (r.brand,)).fetchone()[0]
                cur.execute(
                    "INSERT OR IGNORE INTO tire_model (brand_id, name, season, source_url) VALUES (?,?,?,?)",
                    (brand_id, r.model, r.season, url),
                )
                model_id = cur.execute(
                    "SELECT id FROM tire_model WHERE brand_id=? AND name=?",
                    (brand_id, r.model)).fetchone()[0]
                row = cur.execute(
                    "SELECT id FROM size_variant WHERE ean=?", (r.ean,)).fetchone()
                if row:
                    sv_id = row[0]
                    cur.execute(
                        """UPDATE size_variant SET
                           cai=COALESCE(?, cai), structure=COALESCE(?, structure),
                           position=COALESCE(?, position), tread_pattern=COALESCE(?, tread_pattern),
                           ean=COALESCE(?, ean)
                           WHERE id=?""",
                        (r.cai, r.structure, r.position, r.tread_pattern, r.ean, sv_id),
                    )
                else:
                    cur.execute(
                        """INSERT INTO size_variant
                           (model_id, width, aspect_ratio, rim_diameter,
                            load_index, speed_index, xl, runflat, ean, cai)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (model_id, r.width, r.aspect_ratio, r.rim_diameter,
                         r.load_index, r.speed_index, r.xl, r.runflat, r.ean, r.cai),
                    )
                    sv_id = cur.execute(
                        "SELECT id FROM size_variant WHERE ean=?", (r.ean,)).fetchone()[0]
                cur.execute(
                    """INSERT OR IGNORE INTO eu_label
                       (size_variant_id, fuel_class, wet_grip_class, noise_db,
                        noise_class, snow_grip, ice_grip, source_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (sv_id, r.fuel_class, r.wet_grip_class, r.noise_db,
                     r.noise_class, r.snow_grip, r.ice_grip, source_id),
                )
                cur.execute(
                    """INSERT INTO variant_attributes
                       (size_variant_id, extra) VALUES (?,?)
                       ON CONFLICT(size_variant_id) DO UPDATE SET extra=excluded.extra""",
                    (sv_id, None),
                )
                self.stats["records"] += 1

            self.report_progress(
                i, total, f"{i}/{total} — {slug}: {len(records)} varyant"
            )

        cur.execute(
            "UPDATE scrape_run SET finished_at=?, records_in=?, errors=?, status=? WHERE id=?",
            (datetime.now().isoformat(), self.stats["records"], self.stats["errors"],
             "ok" if self.stats["errors"] == 0 else "partial", run_id),
        )
        conn.commit()
        conn.close()
        print(f"bitti: {self.stats}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    PirelliDeAgent(root, root / "tires.db").run(limit=limit)