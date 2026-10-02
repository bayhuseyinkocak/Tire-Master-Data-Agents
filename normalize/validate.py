"""Veri kalitesi kontrolü — kaynaklar arası doğrulama için.

Kullanım:  uv run python -m normalize.validate
Çıktı: kural ihlali raporu + EAN kesişim özeti (çoklu kaynaklı EAN'ler)
"""

import sqlite3
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


def main() -> None:
    conn = sqlite3.connect(DB)
    print("=== Veri kalitesi ===")
    total_issues = 0
    for label, where in RULES:
        n = conn.execute(
            f"""SELECT COUNT(*) FROM size_variant v
                LEFT JOIN eu_label e ON e.size_variant_id = v.id WHERE {where}"""
        ).fetchone()[0]
        total_issues += n
        flag = "OK " if n == 0 else "!! "
        print(f"{flag}{label}: {n}")

    print("\n=== Kaynaklara göre EAN kapsama ===")
    for row in conn.execute(
        """SELECT b.name, COUNT(DISTINCT v.ean),
                  SUM(CASE WHEN v.ean IS NULL THEN 1 ELSE 0 END)
           FROM size_variant v
           JOIN tire_model m ON m.id = v.model_id
           JOIN brand b ON b.id = m.brand_id
           GROUP BY b.name"""
    ):
        print(f"  {row[0]}: {row[1]} EAN, {row[2]} EAN'siz kayıt")

    print("\n=== Çoklu kaynaklı EAN'ler (eşleştirme köprüsü) ===")
    rows = conn.execute(
        """SELECT v.ean, GROUP_CONCAT(DISTINCT b.name) AS kaynaklar, COUNT(DISTINCT b.id) AS n
           FROM size_variant v
           JOIN tire_model m ON m.id = v.model_id
           JOIN brand b ON b.id = m.brand_id
           WHERE v.ean IS NOT NULL
           GROUP BY v.ean HAVING n > 1 ORDER BY n DESC LIMIT 20"""
    ).fetchall()
    if not rows:
        print("  (henüz yok — markalar tek markalı lastikler)")
    for ean, brands, n in rows:
        print(f"  EAN {ean}: {brands} ({n} kaynak)")

    print(f"\nToplam kural ihlali: {total_issues}")
    conn.close()


if __name__ == "__main__":
    main()
