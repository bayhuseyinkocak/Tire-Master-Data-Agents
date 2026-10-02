"""Continental etiket görsellerini indirir ve source_image'e kaydeder.

Her EAN için Continental label sayfasından PNG linki: /eulabel-download-png/{cai}/
Dosya: raw/images/Continental/<model>/continental_de/<cai>_<ean>.png
DB: source_image(model_id, source_id, url, kind='label', local_path)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx

DB = Path(__file__).resolve().parents[2] / "tires.db"
RAW = Path(__file__).resolve().parents[2] / "raw" / "images"
BASE = "https://www.contimediacenter.com"
UA = "TiresMasterData/0.1"


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    source_id = cur.execute("SELECT id FROM source WHERE base_url LIKE '%continental%'").fetchone()[0]
    model_names: dict[int, str] = dict(cur.execute("SELECT id, name FROM tire_model").fetchall())

    rows = cur.execute(
        """SELECT v.id, v.model_id, v.cai, v.ean
           FROM size_variant v
           JOIN tire_model m ON m.id = v.model_id
           JOIN brand b ON b.id = m.brand_id
           WHERE b.name = 'Continental' AND v.cai IS NOT NULL"""
    ).fetchall()
    print(f"{len(rows)} Continental cai bulundu, etiket indiriliyor...")

    client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
    ok, err = 0, 0
    for sv_id, model_id, cai, ean in rows:
        url = f"{BASE}/eulabel-download-png/{cai}/"
        model = (model_names.get(model_id) or "unknown").replace("/", "-")
        out_dir = RAW / "Continental" / model / "continental_de"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{cai}_{ean}.png"
        path = out_dir / name
        if path.exists():
            ok += 1
            continue
        try:
            resp = client.get(url)
            if resp.status_code == 404:
                err += 1
                continue
            resp.raise_for_status()
            path.write_bytes(resp.content)
            cur.execute(
                "INSERT OR IGNORE INTO source_image (size_variant_id, model_id, source_id, url, kind, local_path) VALUES (?,?,?,?,'label',?)",
                (sv_id, model_id, source_id, url, str(path.relative_to(Path(__file__).resolve().parents[2]))),
            )
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"HATA {cai}: {e}")
            err += 1

    conn.commit()
    conn.close()
    print(f"bitti: {ok} indirildi, {err} hata")


if __name__ == "__main__":
    main()
