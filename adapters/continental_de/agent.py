"""Continental DE ajanı: productsearch API tek çağrı → SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from adapters.base import BaseAgent
from adapters.continental_de.parse_api import parse

API_URL = "https://api.productsearch.continental-tires.com/v1/continental/de/de/plt/sbs?articles=true"
API_KEY = "eln1kj8v4j1GTfrTxIbnr4sbE52nfRSu9DMoltTp"  # sayfadan okunan public frontend anahtarı
SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "db" / "schema.sql"


class ContinentalDeAgent(BaseAgent):
    source_name = "continental_de"
    base_url = "https://www.continental-reifen.de"

    def discover_urls(self) -> list[str]:
        return [API_URL]

    def fetch(self, url: str) -> str:
        resp = self._client.get(
            url,
            headers={
                "x-api-key": API_KEY,
                "Content-Type": "application/json",
                "Origin": self.base_url,
                "Referer": self.base_url + "/",
            },
        )
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str, url: str):
        return parse(json.loads(html))

    def save_raw(self, url: str, html_text: str) -> None:
        (self.raw_dir / "productsearch_sbs_articles.json").write_text(html_text, encoding="utf-8")

    def _ensure_schema(self, cur: sqlite3.Cursor) -> None:
        def addcol(table: str, col: str, typedef: str) -> None:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
            if col not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")

        for col, typ in [
            ("upc", "TEXT"), ("axle_position", "TEXT"), ("tyre_type", "TEXT"),
            ("tire_weight", "REAL"), ("tread_depth", "REAL"), ("max_load", "REAL"),
            ("max_speed", "INTEGER"), ("silence", "BOOLEAN"), ("sealant", "BOOLEAN"),
            ("oe_manufacture", "TEXT"), ("eprel_reg_no", "TEXT"), ("label_url", "TEXT"),
        ]:
            addcol("size_variant", col, typ)
        addcol("variant_attributes", "is_ev_compatible", "BOOLEAN")
        addcol("eu_label", "m_s", "BOOLEAN")

    def run(self, limit: int | None = None) -> None:
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

        for url in self.discover_urls():
            payload = self.fetch(url)
            self.save_raw(url, payload)
            self.stats["pages"] += 1
            records = self.parse(payload, url)
            if limit:
                records = records[:limit]

            for r in records:
                cur.execute("INSERT OR IGNORE INTO brand (name, site_url) VALUES (?, ?)",
                            (r.brand, self.base_url))
                brand_id = cur.execute("SELECT id FROM brand WHERE name=?",
                                       (r.brand,)).fetchone()[0]
                cur.execute(
                    "INSERT OR IGNORE INTO tire_model (brand_id, name, season, source_url) VALUES (?,?,?,?)",
                    (brand_id, r.model, r.season, r.source_url),
                )
                cur.execute(
                    """UPDATE tire_model SET
                       description=COALESCE(?, description),
                       vehicle_type=COALESCE(?, vehicle_type)
                       WHERE brand_id=? AND name=?""",
                    (r.model_description, r.extra.get("pogProductGroupSegment"),
                     brand_id, r.model),
                )
                model_id = cur.execute(
                    "SELECT id FROM tire_model WHERE brand_id=? AND name=?",
                    (brand_id, r.model)).fetchone()[0]

                # Birincil eşleştirme: EAN
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
                    sv_id = row[0]
                    cur.execute(
                        """UPDATE size_variant SET
                           ean=COALESCE(?, ean), cai=COALESCE(?, cai), upc=COALESCE(?, upc),
                           structure=COALESCE(?, structure), position=COALESCE(?, position),
                           tread_pattern=COALESCE(?, tread_pattern),
                           start_date=COALESCE(?, start_date), end_date=COALESCE(?, end_date),
                           axle_position=COALESCE(?, axle_position), tyre_type=COALESCE(?, tyre_type),
                           tire_weight=COALESCE(?, tire_weight), tread_depth=COALESCE(?, tread_depth),
                           max_load=COALESCE(?, max_load), max_speed=COALESCE(?, max_speed),
                           silence=COALESCE(?, silence), sealant=COALESCE(?, sealant),
                           oe_manufacture=COALESCE(?, oe_manufacture),
                           eprel_reg_no=COALESCE(?, eprel_reg_no), label_url=COALESCE(?, label_url)
                           WHERE id=?""",
                        (r.ean, r.cai, r.upc, r.structure, r.position, r.tread_pattern,
                         r.start_date, r.end_date, r.axle_position, r.tyre_type,
                         r.tire_weight, r.tread_depth, r.max_load, r.max_speed,
                         r.silence, r.sealant, r.oe_manufacture, r.eprel_reg_no, r.label_url,
                         sv_id),
                    )
                else:
                    cur.execute(
                        """INSERT INTO size_variant
                           (model_id, width, aspect_ratio, rim_diameter,
                            load_index, speed_index, xl, runflat, ean, cai, upc,
                            position, axle_position, tyre_type, tire_weight, tread_depth,
                            max_load, max_speed, silence, sealant, oe_manufacture,
                            eprel_reg_no, label_url)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (model_id, r.width, r.aspect_ratio, r.rim_diameter,
                         r.load_index, r.speed_index, r.xl, r.runflat, r.ean, r.cai, r.upc,
                         r.position, r.axle_position, r.tyre_type, r.tire_weight, r.tread_depth,
                         r.max_load, r.max_speed, r.silence, r.sealant, r.oe_manufacture,
                         r.eprel_reg_no, r.label_url),
                    )
                    sv_id = cur.execute(
                        """SELECT id FROM size_variant WHERE model_id=?
                           AND IFNULL(width,-1)=IFNULL(?, -1)
                           AND IFNULL(load_index,'')=IFNULL(?, '')
                           AND IFNULL(speed_index,'')=IFNULL(?, '') AND xl=? AND runflat=?""",
                        (model_id, r.width, r.load_index, r.speed_index, r.xl, r.runflat)
                    ).fetchone()[0]

                cur.execute(
                    """INSERT OR IGNORE INTO eu_label
                       (size_variant_id, fuel_class, wet_grip_class, noise_db,
                        noise_class, snow_grip, ice_grip, m_s, source_id)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sv_id, r.fuel_class, r.wet_grip_class, r.noise_db,
                     r.noise_class, r.snow_grip, r.ice_grip, r.m_s, source_id),
                )
                cur.execute("UPDATE eu_label SET m_s=COALESCE(?, m_s) WHERE size_variant_id=?",
                            (r.m_s, sv_id))
                cur.execute(
                    """INSERT INTO variant_attributes
                       (size_variant_id, m_s, stud, type_tube, is_green, is_ev_compatible, regrooving, extra)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(size_variant_id) DO UPDATE SET
                         m_s=excluded.m_s, type_tube=excluded.type_tube,
                         is_ev_compatible=excluded.is_ev_compatible, extra=excluded.extra""",
                    (sv_id, r.m_s, r.stud, r.tyre_type, r.is_green, r.is_ev_compatible,
                     None, json.dumps(r.extra, ensure_ascii=False)),
                )
                self.stats["records"] += 1

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
    ContinentalDeAgent(root, root / "tires.db").run(limit=limit)
