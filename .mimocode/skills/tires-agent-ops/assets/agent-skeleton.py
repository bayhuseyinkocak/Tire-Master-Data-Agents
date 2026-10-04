"""<KAYNAK> ajanı — BaseAgent alt sınıfı iskeleti.

Kullanım:
  ~/.local/bin/uv run python -m adapters.<kaynak>.agent [limit]
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from adapters.base import BaseAgent, ensure_progress_columns
from adapters.<kaynak>.parse import parse

SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "db" / "schema.sql"


class <KlasAdi>Agent(BaseAgent):
    source_name = "<kaynak>"
    base_url = "https://..."

    def discover_urls(self) -> list[str]:
        """Sitemap/API/listeden URL listesi."""
        raise NotImplementedError

    def parse(self, html: str, url: str):
        return parse(html, url)

    def save_raw(self, url: str, html_text: str) -> Path:
        slug = url.rstrip("/").rsplit("/", 1)[-1] or "index"
        path = self.raw_dir / f"{slug}.html"
        path.write_text(html_text, encoding="utf-8")
        return path

    def _ensure_schema(self, cur: sqlite3.Cursor) -> None:
        # Kaynağa özel ek kolonlar burada addcol() ile...
        ensure_progress_columns(cur.connection)

    def run(self, limit: int | None = None) -> None:
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
            "SELECT id FROM source WHERE base_url=?", (self.base_url,)
        ).fetchone()[0]
        cur.execute("INSERT INTO scrape_run (source_id) VALUES (?)", (source_id,))
        run_id = cur.lastrowid
        self._run_id = run_id
        ensure_progress_columns(conn)
        conn.commit()

        self.report_progress(0, 0, "keşif...")
        urls = self.discover_urls()
        if limit:
            urls = urls[:limit]
        total = len(urls)
        self.report_progress(0, total, f"{total} URL keşfedildi")

        for i, url in enumerate(urls, 1):
            self.report_progress(i - 1, total, f"{i}/{total}")
            try:
                payload = self.fetch(url)
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                self.report_progress(i, total, f"hata: {e}")
                continue
            self.save_raw(url, payload)
            self.stats["pages"] += 1
            records = self.parse(payload, url)
            # TODO: brand / tire_model / size_variant / eu_label yazımı
            # EAN ile upsert; yoksa ebat kompoziti (bkz. adapters/michelin_de/agent.py)
            self.stats["records"] += len(records)
            self.report_progress(i, total, f"{i}/{total} — {len(records)} kayıt")

        cur.execute(
            "UPDATE scrape_run SET finished_at=?, records_in=?, errors=?, status=? WHERE id=?",
            (
                __import__("datetime").datetime.now().isoformat(),
                self.stats["records"],
                self.stats["errors"],
                "ok" if self.stats["errors"] == 0 else "partial",
                run_id,
            ),
        )
        conn.commit()
        conn.close()
        print(f"bitti: {self.stats}")


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parents[2]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    <KlasAdi>Agent(root, root / "tires.db").run(limit=limit)
