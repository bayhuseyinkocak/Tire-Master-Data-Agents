-- Tires Master Data — Şema Taslağı v0.1 (SQLite/PostgreSQL uyumlu)

-- Marka ve model: canonical katman (marka sitelerinden gelir)
CREATE TABLE IF NOT EXISTS brand (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,          -- 'Michelin'
    country     TEXT,                          -- menşei ülke
    site_url    TEXT,                          -- kaynak marka sitesi
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tire_model (
    id          INTEGER PRIMARY KEY,
    brand_id    INTEGER NOT NULL REFERENCES brand(id),
    name        TEXT NOT NULL,                 -- 'Primacy 4+'
    season      TEXT CHECK (season IN ('summer','winter','allseason')),
    vehicle_type TEXT,                         -- car / suv / van / ...
    description TEXT,                          -- resmi açıklama (kaynak dili + çeviri alanı eklenebilir)
    image_urls  TEXT,                          -- JSON array, resmi görseller
    source_url  TEXT,
    UNIQUE (brand_id, name)
);

-- Ebat varyantı: eşleştirmenin kalbi
CREATE TABLE IF NOT EXISTS size_variant (
    id            INTEGER PRIMARY KEY,
    model_id      INTEGER NOT NULL REFERENCES tire_model(id),
    width         INTEGER NOT NULL,            -- 205
    aspect_ratio  INTEGER NOT NULL,            -- 55
    rim_diameter  INTEGER NOT NULL,            -- 16
    load_index    TEXT,                        -- '91'
    speed_index   TEXT,                        -- 'V'
    xl            BOOLEAN DEFAULT 0,           -- Extra Load
    runflat       BOOLEAN DEFAULT 0,
    ean           TEXT,                        -- BİRİNCİL eşleştirme anahtarı (tüm kaynaklar için)
    cai           TEXT,                        -- Michelin artikelnr. / Continental artNo11Digit
    upc           TEXT,                        -- Universal Product Code (bazı kaynaklarda)
    structure     TEXT,                        -- 'R' (radial)
    position      TEXT,                        -- 'both' / 'front' / 'rear' / axle key
    tread_pattern TEXT,                        -- desen kodu (örn. 'DIR')
    start_date    TEXT,                        -- üretim başlangıç (DOT ile ilişkili)
    end_date      TEXT,                        -- üretim bitiş
    axle_position TEXT,
    tyre_type     TEXT,                        -- 'TL' / 'TT'
    tire_weight   REAL,
    tread_depth   REAL,
    max_load      REAL,
    max_speed     INTEGER,
    silence       BOOLEAN,                     -- Continental: ContiSilent vb.
    sealant       BOOLEAN,
    oe_manufacture TEXT,                       -- OEM üretici (örn. IVECO)
    eprel_reg_no  TEXT,                        -- EPREL kaydı (özellikle EU etiketi için)
    label_url     TEXT,                        -- resmi etiket sayfası (contimediacenter vb.)
    normalized    TEXT GENERATED ALWAYS AS
                  (width || '/' || aspect_ratio || ' R' || rim_diameter) STORED,
    UNIQUE (model_id, width, aspect_ratio, rim_diameter, load_index, speed_index, xl, runflat)
);

-- Varyant özellikleri: keşfedildikçe geliştirilebilir açık tablo
CREATE TABLE IF NOT EXISTS variant_attributes (
    id              INTEGER PRIMARY KEY,
    size_variant_id INTEGER NOT NULL UNIQUE REFERENCES size_variant(id),
    m_s             BOOLEAN,                   -- M+S (eu_label'e de yazılır)
    stud            BOOLEAN,
    type_tube       TEXT,                      -- 'TL' / 'TT'
    is_green        BOOLEAN,
    is_ev_compatible BOOLEAN,
    regrooving      TEXT,                      -- JSON
    extra           TEXT                       -- JSON, keşfedilen diğer alanlar
);

-- Görseller: model ve/veya varyant bazında; dosya raw/images/brand/model/source/ altında
CREATE TABLE IF NOT EXISTS source_image (
    id              INTEGER PRIMARY KEY,
    size_variant_id INTEGER REFERENCES size_variant(id),
    model_id        INTEGER REFERENCES tire_model(id),
    source_id       INTEGER REFERENCES source(id),
    url             TEXT NOT NULL,
    kind            TEXT,                      -- main / profile / ...
    local_path      TEXT,                      -- göreli: images/Michelin/Crossclimate+/michelin_de/....
    UNIQUE (url)
);

-- EU etiketi (varyant bazında)
CREATE TABLE IF NOT EXISTS eu_label (
    id              INTEGER PRIMARY KEY,
    size_variant_id INTEGER NOT NULL REFERENCES size_variant(id),
    fuel_class      TEXT,                      -- A-E
    wet_grip_class  TEXT,                      -- A-E
    noise_db        INTEGER,
    noise_class     TEXT,                      -- A/B/C
    snow_grip       BOOLEAN DEFAULT 0,         -- 3PMSF
    ice_grip        BOOLEAN DEFAULT 0,
    m_s             BOOLEAN,                   -- M+S
    source_id       INTEGER REFERENCES source(id),
    UNIQUE (size_variant_id, source_id)
);

-- Kaynaklar ve ticari veri
CREATE TABLE IF NOT EXISTS source (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    type      TEXT CHECK (type IN ('brand_site','shop')),
    base_url  TEXT NOT NULL UNIQUE,
    notes     TEXT                             -- scouts/ raporuna referans
);

CREATE TABLE IF NOT EXISTS offer (
    id              INTEGER PRIMARY KEY,
    size_variant_id INTEGER NOT NULL REFERENCES size_variant(id),
    source_id       INTEGER NOT NULL REFERENCES source(id),
    price_eur       NUMERIC(8,2),
    currency        TEXT DEFAULT 'EUR',
    in_stock        BOOLEAN,
    listing_url     TEXT,
    seen_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP   -- fiyat geçmişi: her gözlem yeni satır
);
CREATE INDEX IF NOT EXISTS idx_offer_variant_time ON offer (size_variant_id, seen_at);

-- İzlenebilirlik
CREATE TABLE IF NOT EXISTS scrape_run (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES source(id),
    started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    records_in  INTEGER,
    errors      INTEGER,
    status      TEXT,                            -- ok / partial / failed / running
    -- Canlı panel / Ajan Kontrol Paneli alanları (Faz 1)
    pages_done  INTEGER,                         -- işlenmiş sayfa/istek
    pages_total INTEGER,                         -- keşfedilen toplam URL
    note        TEXT,                            -- son log / konuşma balonu
    pid         INTEGER                          -- çalışan süreç id
);
CREATE INDEX IF NOT EXISTS idx_scrape_run_source ON scrape_run (source_id, id);
