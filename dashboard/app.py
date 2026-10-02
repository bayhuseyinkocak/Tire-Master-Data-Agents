"""Tires Master Data — izleme ve analiz paneli.

Çalıştır:  uv run streamlit run dashboard/app.py
Veri: proje kökündeki tires.db
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB = Path(__file__).resolve().parent.parent / "tires.db"

st.set_page_config(page_title="Tires Master Data", layout="wide")
st.title("Tires Master Data — Ajan & Veri Paneli")

if not DB.exists():
    st.warning("Henüz veritabanı yok. İlk ajan koşusundan sonra burada veri görünecek.")
    st.stop()

conn = sqlite3.connect(DB)

# --- Kenar çubuğu: filtreler ------------------------------------------------
sources = pd.read_sql("SELECT id, name FROM source", conn)
st.sidebar.header("Filtreler")
sel_sources = st.sidebar.multiselect(
    "Kaynak", options=sources["name"], default=list(sources["name"]))
ph = ",".join("?" for _ in sel_sources) or "NULL"

vehicle_types = pd.read_sql(
    "SELECT DISTINCT vehicle_type FROM tire_model WHERE vehicle_type IS NOT NULL ORDER BY 1", conn)
sel_vehicle = st.sidebar.multiselect(
    "Araç tipi", options=list(vehicle_types["vehicle_type"]), default=list(vehicle_types["vehicle_type"]))
vph = ",".join("?" for _ in sel_vehicle) or "NULL"

# --- Sekmeler ---------------------------------------------------------------
tab_genel, tab_model, tab_varyant, tab_etiket, tab_kosu = st.tabs(
    ["Genel Bakış", "Modeller", "Varyant Gezgini", "EU Etiket Analizi", "Ajan Koşuları"])

with tab_kosu:
    st.header("Ajan Koşuları")
    runs = pd.read_sql(
        f"""SELECT r.id, s.name AS kaynak, r.started_at, r.finished_at,
                  r.records_in AS kayit, r.errors AS hata, r.status
           FROM scrape_run r JOIN source s ON s.id = r.source_id
           WHERE s.name IN ({ph}) ORDER BY r.id DESC LIMIT 100""",
        conn, params=sel_sources)
    st.dataframe(runs, use_container_width=True, hide_index=True)
    if not runs.empty:
        st.subheader("Koşu başına kayıt")
        st.bar_chart(runs.set_index("id")[["kayit"]])

with tab_genel:
    st.header("Kapsama")
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, (label, q) in zip(
        (c1, c2, c3, c4, c5),
        [
            ("Marka", "SELECT COUNT(*) FROM brand"),
            ("Model", "SELECT COUNT(*) FROM tire_model"),
            ("Ebat varyantı", "SELECT COUNT(*) FROM size_variant"),
            ("EU Etiketi", "SELECT COUNT(*) FROM eu_label"),
            ("Offer", "SELECT COUNT(*) FROM offer"),
        ],
    ):
        col.metric(label, conn.execute(q).fetchone()[0])

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Marka × Mevsim")
        df = pd.read_sql(
            """SELECT b.name AS marka, COALESCE(m.season,'?') AS mevsim, COUNT(*) AS model_sayisi
               FROM tire_model m JOIN brand b ON b.id = m.brand_id
               GROUP BY b.name, m.season""", conn)
        st.dataframe(df, use_container_width=True, hide_index=True)
    with col_b:
        st.subheader("Varyant Doluluk Oranları")
        total = conn.execute("SELECT COUNT(*) FROM size_variant").fetchone()[0] or 1
        for colname in ("ean", "load_index", "speed_index"):
            missing = conn.execute(
                f"SELECT COUNT(*) FROM size_variant WHERE {colname} IS NULL").fetchone()[0]
            st.progress(1 - missing / total,
                        text=f"{colname}: %{100 * (1 - missing / total):.0f} dolu")

with tab_model:
    st.header("Model Kataloğu")
    dfm = pd.read_sql(
        f"""SELECT b.name AS marka, m.name AS model, m.season AS mevsim,
                  m.vehicle_type AS araç_tipi,
                  COUNT(v.id) AS varyant, SUM(CASE WHEN v.ean IS NOT NULL THEN 1 ELSE 0 END) AS ean_var,
                  SUM(CASE WHEN v.label_url IS NOT NULL THEN 1 ELSE 0 END) AS etiket_var,
                  COUNT(DISTINCT v.tread_pattern) AS desen
           FROM tire_model m
           JOIN brand b ON b.id = m.brand_id
           LEFT JOIN size_variant v ON v.model_id = m.id
           WHERE b.name IN ({ph}) AND (m.vehicle_type IN ({vph}) OR m.vehicle_type IS NULL)
           GROUP BY m.id ORDER BY varyant DESC""", conn, params=sel_sources + sel_vehicle)
    st.dataframe(dfm, use_container_width=True, hide_index=True,
                 column_config={"varyant": st.column_config.ProgressColumn(
                     "varyant", max_value=int(dfm["varyant"].max() or 1))})

with tab_varyant:
    st.header("Varyant Gezgini")
    q = st.text_input("Ara (model adı, EAN veya ebat)", placeholder="örn. 205/55 veya Primacy")
    dfv = pd.read_sql(
        f"""SELECT b.name AS marka, m.name AS model, m.vehicle_type AS araç_tipi,
                  v.width || '/' || v.aspect_ratio || ' R' || v.rim_diameter AS ebat,
                  v.load_index, v.speed_index, v.xl, v.runflat, v.ean, v.cai,
                  v.tread_pattern, v.position, v.label_url, v.eprel_reg_no,
                  v.tire_weight, v.tread_depth, v.max_load, v.oe_manufacture,
                  e.fuel_class, e.wet_grip_class, e.noise_db, e.noise_class,
                  e.snow_grip, e.m_s
           FROM size_variant v
           JOIN tire_model m ON m.id = v.model_id
           JOIN brand b ON b.id = m.brand_id
           LEFT JOIN eu_label e ON e.size_variant_id = v.id
           WHERE b.name IN ({ph}) AND (m.vehicle_type IN ({vph}) OR m.vehicle_type IS NULL)
           LIMIT 5000""", conn, params=sel_sources + sel_vehicle)
    dfv["ebat_str"] = dfv["ebat"].fillna("")
    if q:
        mask = (dfv["model"].str.contains(q, case=False, na=False)
                | dfv["ebat_str"].str.contains(q.replace(" ", ""), case=False, na=False)
                | dfv["ean"].astype(str).str.contains(q, na=False))
        dfv = dfv[mask]
    st.caption(f"{len(dfv)} kayıt")
    st.dataframe(dfv.drop(columns=["ebat_str"]), use_container_width=True, hide_index=True)

with tab_etiket:
    st.header("EU Etiket Analizi")
    e1, e2, e3 = st.columns(3)
    with e1:
        st.subheader("Yakıt sınıfı")
        d1 = pd.read_sql(
            "SELECT fuel_class, COUNT(*) AS n FROM eu_label GROUP BY fuel_class ORDER BY fuel_class", conn)
        st.bar_chart(d1.set_index("fuel_class") if not d1.empty else d1)
    with e2:
        st.subheader("Islak tutuş")
        d2 = pd.read_sql(
            "SELECT wet_grip_class, COUNT(*) AS n FROM eu_label GROUP BY wet_grip_class ORDER BY wet_grip_class", conn)
        st.bar_chart(d2.set_index("wet_grip_class") if not d2.empty else d2)
    with e3:
        st.subheader("Gürültü (dB)")
        d3 = pd.read_sql(
            "SELECT noise_db, COUNT(*) AS n FROM eu_label GROUP BY noise_db ORDER BY noise_db", conn)
        st.bar_chart(d3.set_index("noise_db") if not d3.empty else d3)
    st.subheader("Kış donanımı")
    d4 = pd.read_sql(
        """SELECT COALESCE(m.season,'?') AS mevsim,
                  SUM(e.snow_grip) AS '3PMSF', SUM(e.ice_grip) AS 'buz', COUNT(*) AS toplam
           FROM eu_label e JOIN size_variant v ON v.id = e.size_variant_id
           JOIN tire_model m ON m.id = v.model_id
           GROUP BY m.season""", conn)
    st.dataframe(d4, use_container_width=True, hide_index=True)

conn.close()
