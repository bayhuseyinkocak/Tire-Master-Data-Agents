"""Michelin DE ajanı: sitemap → model sayfaları → SKU kayıtları → SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

from adapters.base import BaseAgent
from adapters.michelin_de.parse import parse

SITEMAP = "https://www.michelin.de/sitemap.xml"
SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "db" / "schema.sql"


class MichelinDeAgent(BaseAgent):
    source_name = "michelin_de"
    base_url = "https://www.michelin.de"

    def discover_urls(self) -> list[str]:
        text = self.fetch(SITEMAP)
        return sorted(set(re.findall(
            r"https://www\.michelin\.de/auto/tyres/michelin-[a-z0-9-]+", text)))

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

        addcol("size_variant", "cai", "TEXT")
        addcol("size_variant", "structure", "TEXT")
        addcol("size_variant", "position", "TEXT")
        addcol("size_variant", "tread_pattern", "TEXT")
        addcol("size_variant", "start_date", "TEXT")
        addcol("size_variant", "end_date", "TEXT")
        addcol("eu_label", "m_s", "BOOLEAN")
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
        conn = sqlite3.connect(self.db_path)
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

        urls = self.discover_urls()
        if limit:
            urls = urls[:limit]
        print(f"{len(urls)} model sayfası bulundu")

        for url in urls:
            try:
                html_text = self.fetch(url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    self.stats["skipped_404"] += 1
                else:
                    print(f"HATA {url}: {e}")
                    self.stats["errors"] += 1
                continue
            except Exception as e:  # noqa: BLE001
                print(f"HATA {url}: {e}")
                self.stats["errors"] += 1
                continue
            self.save_raw(url, html_text)
            self.stats["pages"] += 1
            try:
                records = [r for r in self.parse(html_text, url) if r.model and r.width]
                if not records:
                    self.stats["skipped_empty"] += 1
                    continue

                # --- kayıt yazımı ---
                r0 = records[0]
                cur.execute("INSERT OR IGNORE INTO brand (name, site_url) VALUES (?, ?)",
                            (r0.brand, self.base_url))
                brand_id = cur.execute("SELECT id FROM brand WHERE name=?",
                                       (r0.brand,)).fetchone()[0]
                cur.execute(
                    "INSERT OR IGNORE INTO tire_model (brand_id, name, season, source_url) VALUES (?,?,?,?)",
                    (brand_id, r0.model, r0.season, url),
                )
                cur.execute(
                    "UPDATE tire_model SET description=COALESCE(?, description) WHERE brand_id=? AND name=?",
                    (r0.model_description, brand_id, r0.model),
                )
                model_id = cur.execute(
                    "SELECT id FROM tire_model WHERE brand_id=? AND name=?",
                    (brand_id, r0.model)).fetchone()[0]

                for r in records:
                    # Birincil eşleştirme: EAN; yoksa ebat+endeks kompoziti
                    row = None
                    if r.ean:
                        row = cur.execute(
                            "SELECT id FROM size_variant WHERE ean=?", (r.ean,)).fetchone()
                    if not row:
                        row = cur.execute(
                            """SELECT id FROM size_variant WHERE model_id=?
                               AND IFNULL(width,-1)=IFNULL(?, -1)
                               AND IFNULL(aspect_ratio,-1)=IFNULL(?, -1)
                               AND IFNULL(rim_diameter,-1)=IFNULL(?, -1)
                               AND IFNULL(load_index,'')=IFNULL(?, '')
                               AND IFNULL(speed_index,'')=IFNULL(?, '')
                               AND xl=? AND runflat=?""",
                            (model_id, r.width, r.aspect_ratio, r.rim_diameter,
                             r.load_index, r.speed_index, r.xl, r.runflat)).fetchone()
                    if row:
                        cur.execute(
                            """UPDATE size_variant SET
                               ean=COALESCE(?, ean), cai=COALESCE(?, cai),
                               structure=COALESCE(?, structure), position=COALESCE(?, position),
                               tread_pattern=COALESCE(?, tread_pattern),
                               start_date=COALESCE(?, start_date), end_date=COALESCE(?, end_date),
                               label_url=COALESCE(?, label_url)
                               WHERE id=?""",
                            (r.ean, r.cai, r.structure, r.position, r.tread_pattern,
                             r.start_date, r.end_date, r.label_url, row[0]),
                        )
                        sv_id = row[0]
                    else:
                        cur.execute(
                            """INSERT INTO size_variant
                               (model_id, width, aspect_ratio, rim_diameter,
                                load_index, speed_index, xl, runflat, ean, cai,
                                structure, position, tread_pattern, start_date, end_date,
                                label_url)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (model_id, r.width, r.aspect_ratio, r.rim_diameter,
                             r.load_index, r.speed_index, r.xl, r.runflat, r.ean, r.cai,
                             r.structure, r.position, r.tread_pattern,
                             r.start_date, r.end_date, r.label_url),
                        )
                        sv_id = cur.execute(
                            """SELECT id FROM size_variant WHERE model_id=?
                               AND IFNULL(width,-1)=IFNULL(?, -1)
                               AND IFNULL(load_index,'')=IFNULL(?, '')
                               AND IFNULL(speed_index,'')=IFNULL(?, '')
                               AND xl=? AND runflat=?""",
                            (model_id, r.width, r.load_index, r.speed_index,
                             r.xl, r.runflat)).fetchone()[0]

                    cur.execute(
                        """INSERT OR IGNORE INTO eu_label
                           (size_variant_id, fuel_class, wet_grip_class, noise_db,
                            noise_class, snow_grip, ice_grip, m_s, source_id)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (sv_id, r.fuel_class, r.wet_grip_class, r.noise_db,
                         r.noise_class, r.snow_grip, r.ice_grip, r.m_s, source_id),
                    )
                    cur.execute("UPDATE eu_label SET m_s=? WHERE size_variant_id=?",
                                (r.m_s, sv_id))
                    cur.execute(
                        """INSERT INTO variant_attributes
                           (size_variant_id, m_s, stud, type_tube, is_green, is_ev_compatible, regrooving)
                           VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(size_variant_id) DO UPDATE SET
                             m_s=excluded.m_s, stud=excluded.stud, type_tube=excluded.type_tube,
                             is_green=excluded.is_green, regrooving=excluded.regrooving""",
                        (sv_id, r.m_s, r.stud, r.type_tube, r.is_green,
                         None,  # EV uyumluluğu henüz bu kaynaktan keşfedilmedi
                         None if r.regrooving is None else json.dumps(r.regrooving)),
                    )
                    self.stats["records"] += 1

                # --- görseller: brand/model/source klasörüne + source_image ---
                ean_to_sv = {
                    r.ean: cur.execute("SELECT id FROM size_variant WHERE ean=?",
                                       (r.ean,)).fetchone()
                    for r in records if r.ean
                }
                for img_url in r0.image_urls:
                    try:
                        local = self.download_image(img_url, r0.brand, r0.model, self.source_name)
                        matched_id = None
                        for ean, row in ean_to_sv.items():
                            if ean and ean in img_url and row:
                                matched_id = row[0]
                                break
                        cur.execute(
                            """INSERT OR IGNORE INTO source_image
                               (size_variant_id, model_id, source_id, url, kind, local_path)
                               VALUES (?,?,?,?,'product',?)""",
                            (matched_id, model_id, source_id, img_url, local),
                        )
                    except Exception as e:  # noqa: BLE001 — görsel hatası koşuyu durdurmasın
                        print(f"görsel hatası {img_url}: {e}")
                        self.stats["errors"] += 1

            except Exception as e:  # noqa: BLE001
                print(f"HATA {url}: {e}")
                self.stats["errors"] += 1

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
    MichelinDeAgent(root, root / "tires.db").run(limit=limit)
