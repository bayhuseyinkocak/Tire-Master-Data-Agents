"""Veri kalitesi kontrolü — kaynaklar arası doğrulama için.

Kullanım:
  uv run python -m normalize.validate
  uv run python -m normalize.validate --json
Çıktı: kural ihlali raporu + EAN kesişim özeti (çoklu kaynaklı EAN'ler)
--json: panel için makine-okur özet
"""

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "tires.db"

RULES = [
    ("hız endeksi tek harf değil", "v.speed_index IS NOT NULL AND v.speed_index NOT GLOB '[A-Z]'"),
    ("yük endeksi sayı değil", "v.load_index IS NOT NULL AND v.load_index NOT GLOB '[0-9]*'"),
    ("endeks parantezli", "v.load_index LIKE '%(%' OR v.speed_index LIKE '%(%'"),
    ("ean 13 hane değil", "v.ean IS NOT NULL AND LENGTH(v.ean) != 13"),
    ("ean rakam değil", "v.ean GLOB '*[^0-9]*'"),
    ("yakıt sınıfı A-E dışı",
     "e.fuel_class IS NOT NULL AND e.fuel_class NOT IN ('A','B','C','D','E')"),
    ("ıslak sınıfı A-E dışı",
     "e.wet_grip_class IS NOT NULL AND e.wet_grip_class NOT IN ('A','B','C','D','E')"),
    ("gürültü mantıksız", "e.noise_db IS NOT NULL AND (e.noise_db < 60 OR e.noise_db > 90)"),
    ("ebat yok", "v.width IS NULL OR v.aspect_ratio IS NULL OR v.rim_diameter IS NULL"),
]


def collect() -> dict:
    """Panel için makine-okur kalite özeti."""
    conn = sqlite3.connect(DB)
    rules_out = []
    total_issues = 0
    for label, where in RULES:
        n = conn.execute(
            f"""SELECT COUNT(*) FROM size_variant v
                LEFT JOIN eu_label e ON e.size_variant_id = v.id WHERE {where}"""
        ).fetchone()[0]
        total_issues += n
        rules_out.append({"label": label, "count": n, "ok": n == 0})

    coverage = []
    for row in conn.execute(
        """SELECT b.name, COUNT(DISTINCT v.ean),
                  SUM(CASE WHEN v.ean IS NULL THEN 1 ELSE 0 END)
           FROM size_variant v
           JOIN tire_model m ON m.id = v.model_id
           JOIN brand b ON b.id = m.brand_id
           GROUP BY b.name"""
    ):
        coverage.append({
            "brand": row[0],
            "ean_count": row[1],
            "ean_missing": row[2],
        })

    multi = []
    rows = conn.execute(
        """SELECT v.ean, GROUP_CONCAT(DISTINCT b.name) AS kaynaklar, COUNT(DISTINCT b.id) AS n
           FROM size_variant v
           JOIN tire_model m ON m.id = v.model_id
           JOIN brand b ON b.id = m.brand_id
           WHERE v.ean IS NOT NULL
           GROUP BY v.ean HAVING n > 1 ORDER BY n DESC LIMIT 20"""
    ).fetchall()
    for ean, brands, n in rows:
        multi.append({"ean": ean, "brands": brands, "sources": n})

    totals = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM size_variant),
             (SELECT COUNT(*) FROM size_variant WHERE ean IS NOT NULL),
             (SELECT COUNT(*) FROM brand),
             (SELECT COUNT(*) FROM tire_model),
             (SELECT COUNT(*) FROM eu_label)"""
    ).fetchone()
    conn.close()
    return {
        "total_issues": total_issues,
        "rules": rules_out,
        "ean_coverage": coverage,
        "multi_source_eans": multi,
        "counts": {
            "size_variant": totals[0],
            "ean_present": totals[1],
            "brand": totals[2],
            "tire_model": totals[3],
            "eu_label": totals[4],
        },
        "quality_score": None if totals[0] == 0 else round(
            1 - total_issues / max(totals[0], 1), 3
        ),
    }


def main() -> None:
    summary = collect()
    print("=== Veri kalitesi ===")
    for item in summary["rules"]:
        flag = "OK " if item["ok"] else "!! "
        print(f"{flag}{item['label']}: {item['count']}")

    print("\n=== Kaynaklara göre EAN kapsama ===")
    for row in summary["ean_coverage"]:
        print(f"  {row['brand']}: {row['ean_count']} EAN, {row['ean_missing']} EAN'siz kayıt")

    print("\n=== Çoklu kaynaklı EAN'ler (eşleştirme köprüsü) ===")
    if not summary["multi_source_eans"]:
        print("  (henüz yok — markalar tek markalı lastikler)")
    for row in summary["multi_source_eans"]:
        print(f"  EAN {row['ean']}: {row['brands']} ({row['sources']} kaynak)")

    print(f"\nToplam kural ihlali: {summary['total_issues']}")
    if summary["quality_score"] is not None:
        print(f"Kalite skoru: {summary['quality_score']}")


if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(collect(), ensure_ascii=False, indent=2))
    else:
        main()
