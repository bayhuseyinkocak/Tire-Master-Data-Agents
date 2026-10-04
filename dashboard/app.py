"""Tires Master Data — izleme ve analiz paneli.

Çalıştır:  uv run streamlit run dashboard/app.py
Veri: proje kökündeki tires.db
Ajan künyesi: agents_registry.yaml + normalize/validate.py --json
"""

import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# streamlit run dashboard/app.py → script dizini yolda; yan modül importu
_DASH_DIR = Path(__file__).resolve().parent
if str(_DASH_DIR) not in sys.path:
    sys.path.insert(0, str(_DASH_DIR))
_ROOT_DIR = _DASH_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from avatars import render_in_streamlit  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "tires.db"
REGISTRY = Path(__file__).resolve().parent.parent / "agents_registry.yaml"
ROOT = Path(__file__).resolve().parent.parent
REFRESH_SECONDS = 5
# Yarım/kesik koşu eşiği (dakika) — pid ölüyse hemen "kesildi"
STALE_MINUTES = 15

BRAND_TO_SRC = {
    "Michelin": "michelin_de",
    "Continental": "continental_de",
    "Pirelli": "pirelli_de",
}

st.set_page_config(page_title="Tires Master Data", layout="wide")
st.title("Tires Master Data — Ajan & Veri Paneli")


def connect_db(read_only: bool = False) -> sqlite3.Connection:
    if read_only and DB.exists():
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    conn = sqlite3.connect(DB, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return conn


def scrape_run_columns(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(scrape_run)")}


def ensure_progress(conn: sqlite3.Connection) -> None:
    try:
        from adapters.base import ensure_progress_columns
        ensure_progress_columns(conn)
    except Exception:
        pass


def load_registry() -> dict:
    if not REGISTRY.exists():
        return {}
    with open(REGISTRY, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def quality_summary() -> dict | None:
    try:
        from normalize.validate import collect
        return collect()
    except Exception:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def run_age_minutes(started_at: str | None) -> float | None:
    started = parse_ts(started_at)
    if not started:
        return None
    if started.tzinfo is not None:
        return (datetime.now(started.tzinfo) - started).total_seconds() / 60
    return (datetime.now() - started).total_seconds() / 60


def agent_state(run: dict | None) -> tuple[str, str, str]:
    """(durum_rozeti, renk, açıklama)."""
    if not run:
        return "pasif", "gray", "Henüz scrape_run yok"
    finished = run.get("finished_at")
    errors = int(run.get("errors") or 0)
    records = int(run.get("records_in") or 0)
    status = run.get("status") or ""
    if finished:
        if errors > 0:
            detail = f"{records} kayıt, {errors} hata"
            return "kısmi" if records else "hata", "orange", detail
        return "hazır", "green", f"{records} kayıt, 0 hata"
    # bitmemiş koşu
    age = run_age_minutes(run.get("started_at"))
    pid = run.get("pid")
    if status == "running" and pid and pid_alive(pid):
        return "çalışıyor", "blue", f"pid {pid} canlı"
    if pid and pid_alive(pid):
        return "çalışıyor", "blue", f"pid {pid} canlı"
    if age is None:
        return "yarım", "orange", "bitiş yok"
    if age >= STALE_MINUTES:
        return "kesildi", "orange", f"~{int(age)} dk önce başlamış, süreç yok"
    return "çalışıyor", "blue", f"~{int(age)} dk"


def latest_run_for(conn: sqlite3.Connection, source: str) -> dict | None:
    cols = scrape_run_columns(conn)
    prog = ""
    extra_keys: list[str] = []
    if {"pages_done", "pages_total", "note", "pid"} <= cols:
        prog = ", r.pages_done, r.pages_total, r.note, r.pid"
        extra_keys = ["pages_done", "pages_total", "note", "pid"]
    q = f"""SELECT r.id, s.name AS kaynak, r.started_at, r.finished_at,
                   r.records_in, r.errors, r.status{prog}
            FROM scrape_run r JOIN source s ON s.id = r.source_id
            WHERE s.name = ? ORDER BY r.id DESC LIMIT 1"""
    row = conn.execute(q, (source,)).fetchone()
    if not row:
        return None
    keys = ["id", "kaynak", "started_at", "finished_at", "records_in", "errors", "status"]
    keys.extend(extra_keys)
    return dict(zip(keys, row))


def mission_status(source: str, run: dict | None, quality: dict | None,
                   agent_state_name: str) -> list[dict]:
    reg = load_registry().get(source, {})
    steps = reg.get("misyon") or []
    finished = bool(run and run.get("finished_at"))
    errors = int((run.get("errors") or 0) if run else 0)
    records = int((run.get("records_in") or 0) if run else 0)
    status = (run.get("status") or "") if run else ""
    total_issues = quality.get("total_issues") if quality else None
    working = agent_state_name in ("çalışıyor", "kesildi", "yarım") and not finished

    out = []
    for step in steps:
        sid = str(step.get("id") or step.get("ad") or "")
        label = step.get("ad") or sid
        ipucu = step.get("ipucu") or ""
        if sid in ("kesif", "keşif"):
            state = "tamam" if (finished or records > 0) else ("çalışıyor" if working else "sırada")
        elif sid in ("kazi", "kazı", "parse"):
            if working:
                state = "çalışıyor"
            elif finished and errors == 0:
                state = "tamam"
            elif finished and errors > 0 and records > 0:
                state = "kısmi"
            elif finished and errors > 0:
                state = "hata"
            elif run and status == "running":
                state = "çalışıyor"
            else:
                state = "sırada"
        elif sid in ("dogrulama", "doğrulama"):
            if total_issues is None:
                state = "sırada"
            elif total_issues == 0:
                state = "tamam"
            else:
                state = "uyarı"
        elif sid == "teslim":
            if finished and (records or True):
                state = "tamam"
            elif working:
                state = "sırada"
            else:
                state = "sırada"
        else:
            state = "tamam" if finished else "sırada"
        out.append({"id": sid, "ad": label, "ipucu": ipucu, "state": state})
    return out


def progress_ui(run: dict | None) -> None:
    """İlerleme çubuğu / yoksa açıklama."""
    if not run:
        st.caption("İlerleme yok — koşu kaydı bulunamadı.")
        return
    pd_one = run.get("pages_done")
    pt_one = run.get("pages_total")
    if pd_one is not None and pt_one:
        frac = max(0.0, min(1.0, float(pd_one) / float(pt_one)))
        st.progress(frac, text=f"{pd_one}/{pt_one} sayfa · %{100 * frac:.0f}")
    elif pd_one is not None and pt_one in (0, None):
        st.progress(min(1.0, float(pd_one) / max(float(pd_one), 1.0)),
                    text=f"{pd_one} sayfa (toplam bilinmiyor)")
    else:
        if run.get("finished_at"):
            st.caption("Bu koşu ilerleme kolonlarıyla yazılmadı (eski ajan / migration öncesi).")
        else:
            st.caption("İlerleme yazımı bekleniyor…")


def render_agent_card(meta: dict, run: dict | None, quality: dict | None,
                      state_label: str, state_color: str, state_detail: str) -> None:
    source = meta.get("source_name") or meta.get("source") or "ajan"
    badge = {"green": "🟢", "blue": "🔵", "red": "🔴", "orange": "🟠", "gray": "⚪"}.get(state_color, "⚪")

    # Faz 3: bloub tarzı avatar (durum animasyonlu)
    a_col, t_col = st.columns([1, 2])
    with a_col:
        render_in_streamlit(
            st, source, state_label,
            size=88,
        )
    with t_col:
        st.subheader(f"{meta.get('marka') or source}")
        st.caption(f"{source} · rol: {meta.get('rol', '—')}")
        st.markdown(f"**{badge} {state_label}** · {state_detail}")

    if run:
        st.markdown(f"Koşu `#{run['id']}` · `{run.get('status') or '—'}`")
        if run.get("pid"):
            st.caption(f"pid: `{run['pid']}` · canlı: {pid_alive(run['pid'])}")
        if run.get("started_at"):
            st.caption(f"başlangıç: {run['started_at']}")
        if run.get("finished_at"):
            st.caption(f"bitiş: {run['finished_at']}")
        m1, m2 = st.columns(2)
        m1.metric("Kayıt", run.get("records_in") or 0)
        m2.metric("Hata", run.get("errors") or 0)
        progress_ui(run)
        note = run.get("note") or (meta.get("son_mesaj") or None)
        if note:
            st.info(note, icon="💬" if run.get("note") else "📌")
    else:
        st.caption("Henüz scrape_run yok.")
        if meta.get("son_mesaj"):
            st.caption(f"registry notu: {meta['son_mesaj']}")

    with st.expander("Misyon", expanded=bool(run)):
        steps = mission_status(meta.get("source_name") or source, run, quality, state_label)
        if not steps:
            st.caption("misyon tanımsız")
        for step in steps:
            mark = {
                "tamam": "✅",
                "çalışıyor": "▶️",
                "hata": "❌",
                "kısmi": "🟡",
                "uyarı": "⚠️",
                "sırada": "○",
            }.get(step["state"], "○")
            hint = f" — {step['ipucu']}" if step["ipucu"] else ""
            st.markdown(f"- {mark} **{step['ad']}** ({step['state']}){hint}")

    cmd = meta.get("komut") or f"uv run python -m adapters.{meta.get('source_name', source)}.agent"
    st.caption("Komut (kopyala):")
    st.code(cmd, language="bash")

    scout = meta.get("scout")
    if scout:
        scout_path = ROOT / scout
        if scout_path.exists():
            st.caption(f"📖 {scout} mevcut")
        else:
            st.warning(f"Keşif raporu yok: {scout}")
    else:
        st.caption("scout: —")


@st.fragment(run_every=REFRESH_SECONDS)
def render_agents_tab() -> None:
    """Ajan kartları — her REFRESH_SECONDS sn'de DB'yi taze okur."""
    st.header("Ajan Kontrol Paneli")
    st.caption(
        "Kartlar: agents_registry.yaml (künye/misyon) + scrape_run (canlı ilerleme). "
        f"Otomatik yenileme: {REFRESH_SECONDS} sn. Panel süreç başlatmaz — yalnızca izler."
    )

    registry = load_registry()
    if not registry:
        st.warning("agents_registry.yaml okunamadı.")
        return

    quality = quality_summary()
    try:
        conn = connect_db()
        ensure_progress(conn)
    except sqlite3.Error as e:
        st.error(f"Veritabanı açılamadı: {e}")
        return

    try:
        sources_all = list(registry)
        opts = []
        for s in sources_all:
            meta = registry[s] or {}
            label = f"{meta.get('marka') or s} ({s})"
            opts.append((label, s))

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            sel_agents = st.multiselect(
                "Ajan",
                options=[s for _, s in opts],
                default=sources_all,
                format_func=lambda x: f"{(registry.get(x) or {}).get('marka') or x} ({x})",
            )
        with c2:
            only_running = st.checkbox("Yalnızca canlı/kesik", value=False)
        with c3:
            show_quality = st.checkbox("Kalite özeti", value=True)

        wanted = sel_agents or sources_all
        sources = []
        for s in wanted:
            if only_running:
                run = latest_run_for(conn, s)
                if not agent_state(run)[0] in ("çalışıyor", "kesildi", "yarım"):
                    continue
            sources.append(s)

        if not sources:
            st.info("Filtreye uyan ajan yok.")
            return

        n_cols = 3
        rows = [sources[i:i + n_cols] for i in range(0, len(sources), n_cols)]
        for row in rows:
            cards = st.columns(len(row))
            for col, source in zip(cards, row):
                meta = dict(registry[source] or {})
                meta["source_name"] = source
                run = latest_run_for(conn, source)
                state_label, state_color, state_detail = agent_state(run)
                with col.container(border=True):
                    render_agent_card(meta, run, quality, state_label, state_color, state_detail)

        if show_quality and quality is not None:
            st.subheader("Kalite özeti (tüm kaynaklar)")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Kural ihlali", quality.get("total_issues", 0))
            counts = quality.get("counts") or {}
            m2.metric("size_variant", counts.get("size_variant", 0))
            m3.metric("EAN dolu", counts.get("ean_present", 0))
            m4.metric("EU label", counts.get("eu_label", 0))
            score = quality.get("quality_score")
            m5.metric("Kalite skoru", "—" if score is None else f"{score:.3f}")
            with st.expander("Kural detayı"):
                st.dataframe(quality.get("rules") or [], use_container_width=True, hide_index=True)

        st.caption(f"Son güncelleme: {datetime.now().strftime('%H:%M:%S')}")
    finally:
        conn.close()


def build_where() -> tuple[str, list]:
    """Filtrelerden SQL WHERE parçası üretir. Boş seçim = filtre yok."""
    parts: list[str] = []
    params: list = []
    if sel_sources:
        parts.append(f"b.name IN ({','.join('?' for _ in sel_sources)})")
        params.extend(sel_sources)
    vt_parts: list[str] = []
    if "(bilinmiyor)" in sel_vehicle:
        vt_parts.append("m.vehicle_type IS NULL")
    real = [v for v in sel_vehicle if v != "(bilinmiyor)"]
    if real:
        vt_parts.append(f"m.vehicle_type IN ({','.join('?' for _ in real)})")
        params.extend(real)
    if vt_parts:
        parts.append("(" + " OR ".join(vt_parts) + ")")
    return ("WHERE " + " AND ".join(parts)) if parts else "", params


if not DB.exists():
    st.warning("Henüz veritabanı yok. İlk ajan koşusundan sonra burada veri görünecek.")
    st.stop()

conn = connect_db()
ensure_progress(conn)

# --- Kenar çubuğu: filtreler ------------------------------------------------
brands = pd.read_sql("SELECT name FROM brand ORDER BY name", conn)
st.sidebar.header("Filtreler")
sel_sources = st.sidebar.multiselect(
    "Marka", options=list(brands["name"]), default=list(brands["name"]))

vehicle_types = pd.read_sql(
    "SELECT DISTINCT vehicle_type FROM tire_model WHERE vehicle_type IS NOT NULL ORDER BY 1", conn)
vt_opts = list(vehicle_types["vehicle_type"]) + ["(bilinmiyor)"]
sel_vehicle = st.sidebar.multiselect(
    "Araç tipi", options=vt_opts, default=vt_opts)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Canlı ilerleme Ajanlar sekmesinde otomatik yenilenir. "
    "Ajan başlatma terminalden yapılır."
)

# --- Sekmeler ---------------------------------------------------------------
tab_ajan, tab_genel, tab_model, tab_varyant, tab_etiket, tab_kosu = st.tabs(
    ["Ajanlar", "Genel Bakış", "Modeller", "Varyant Gezgini", "EU Etiket Analizi", "Ajan Koşuları"])

with tab_ajan:
    render_agents_tab()

with tab_kosu:
    st.header("Ajan Koşuları")
    where_runs = ""
    params_runs: list = []
    if sel_sources:
        src_names = [BRAND_TO_SRC[b] for b in sel_sources if b in BRAND_TO_SRC]
        if src_names:
            where_runs = f"WHERE s.name IN ({','.join('?' for _ in src_names)})"
            params_runs = src_names
    cols = scrape_run_columns(conn)
    prog_cols = ""
    if {"pages_done", "pages_total", "note", "pid"} <= cols:
        prog_cols = ", r.pages_done, r.pages_total, r.note, r.pid"
    runs = pd.read_sql(
        f"""SELECT r.id, s.name AS kaynak, r.started_at, r.finished_at,
                  r.records_in AS kayit, r.errors AS hata, r.status{prog_cols}
           FROM scrape_run r JOIN source s ON s.id = r.source_id
           {where_runs} ORDER BY r.id DESC LIMIT 100""",
        conn, params=params_runs)
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
    where_m, params_m = build_where()
    dfm = pd.read_sql(
        f"""SELECT b.name AS marka, m.name AS model, m.season AS mevsim,
                  m.vehicle_type AS araç_tipi,
                  COUNT(v.id) AS varyant, SUM(CASE WHEN v.ean IS NOT NULL THEN 1 ELSE 0 END) AS ean_var,
                  SUM(CASE WHEN v.label_url IS NOT NULL THEN 1 ELSE 0 END) AS etiket_var,
                  COUNT(DISTINCT v.tread_pattern) AS desen
           FROM tire_model m
           JOIN brand b ON b.id = m.brand_id
           LEFT JOIN size_variant v ON v.model_id = m.id
           {where_m}
           GROUP BY m.id ORDER BY varyant DESC""", conn, params=params_m)
    vmax = 1
    if not dfm.empty:
        cand = dfm["varyant"].fillna(0).max()
        if not pd.isna(cand) and cand > 0:
            vmax = int(cand)
    st.dataframe(dfm, use_container_width=True, hide_index=True,
                 column_config={"varyant": st.column_config.ProgressColumn(
                     "varyant", max_value=vmax)})

with tab_varyant:
    st.header("Varyant Gezgini")
    q = st.text_input("Ara (model adı, EAN veya ebat)", placeholder="örn. 205/55 veya Primacy")
    where_v, params_v = build_where()
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
           {where_v}
           LIMIT 5000""", conn, params=params_v)
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
