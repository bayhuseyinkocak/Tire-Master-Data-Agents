# Tires Master Data — Proje Planı

## Amaç
Avrupa/Almanya pazarı için araba lastiği master verisi toplamak.
İki kaynak katmanı:

1. **Marka siteleri (canonical data)** — model, segment, desen, resmi görseller, teknik açıklamalar
2. **Online shoplar (market data)** — ebat varyantları, EAN, EU etiketi, fiyat, stok

Altın kural: **Ham veri asla silinmez.** Her sayfa `raw/` altında saklanır; parse mantığı
değişince yeniden kazımaya gerek kalmaz.

## Teknoloji
- Python 3.12+, `httpx` (statik sayfalar) + `playwright` (JS-render gereken siteler)
- `parsel` / BeautifulSoup ile parse
- SQLite (geliştirme) → PostgreSQL (production)
- Her kaynak `adapters/` altında kendi modülünde (kaynak başına 1 adapter)

## Klasör Yapısı
```
PLAN.md              ← bu dosya
docs/db/schema.sql   ← veritabanı şeması
scouts/              ← kaynak başına keşif raporu (md) + _TEMPLATE.md
adapters/            ← kaynak başına scraper adapter'ları (her site = 1 ajan)
  base.py            ← ortak protokol: fetch/parse/save, rate limit, raw kaydetme, scrape_run loglama
  <kaynak>/
    agent.py         ← siteye özgü akıl: URL keşfi, crawl akışı
    parse.py         ← siteye özgü parse mantığı
raw/                 ← ham HTML/JSON snapshot'ları (kaynak/tarih/... yapısında)
normalize/           ← normalizasyon + eşleştirme kodu
dashboard/           ← Streamlit panel: ajan koşuları, kapsama, veri analizi
```

## Ajan Mimarisi
Her kaynak site kendi yapısına sahip olduğu için **site başına ajan** prensibi:
- Her ajan `adapters/base.py` protokolünü uygular (fetch → raw kaydet → parse → DB), siteye özgü kısım `agent.py` + `parse.py` içindedir.
- Ortak altyapı (nazik tarama ≤1 istek/sn, raw saklama, scrape_run loglama, hata toplama, `report_progress`) base'den gelir.
- **Yeni ajan ritüeli:** `.mimocode/skills/tires-agent-ops/` skill'i (scouts → adapters → `agents_registry.yaml` → limit testi → `validate --json` → panel kartı).

## Dashboard (Streamlit)
- `uv run streamlit run dashboard/app.py`
- Gösterir: kaynak başına son koşular (zaman, kayıt, hata), kapsama (model/ebat/etiket/offer sayıları),
  veri analizi (marka × mevsim, EU etiket sınıf dağılımı, eksik alan oranları)
- Ajanlar DB'ye logladığı için panel canlı izleme sağlar.

## Fazlar

### Faz 0 — Keşif (şu an buradayız)
Her kaynak için `scouts/<kaynak>.md` raporu:
- Hangi veriler mevcut (model listesi, ebat, EAN, EU etiketi, görsel)
- URL yapısı, pagination, API endpoint'leri (çoğu site dahili JSON API kullanır)
- JS-render gerekiyor mu, rate limit / bot koruması (Cloudflare vb.)
- robots.txt ve kullanım şartları durumu

**Pilot marka:** Michelin DE (michelin.de)

### Faz 1 — Marka siteleri (DE)
Aday liste (keşifle kesinleşecek):
Michelin, Continental, Goodyear, Pirelli, Bridgestone, Hankook, Nokian,
Dunlop, Falken, Vredestein, Kumho, Semperit, Uniroyal, Fulda

### Faz 2 — Online shoplar (DE)
Aday liste: reifendirekt.de, tirendo.de, reifen.com, pneus-online, autodoc,
tires24, amazon.de (yuvarlanma direnci/ıslak tutuş/gürültü verileri shoplarda
genelde daha eksiksizdir)

### Faz 3 — Normalizasyon & eşleştirme
- Ebat normalizasyonu: "205/55 R16 91V" ↔ "205/55R16 91V" ↔ "205 55 16 91 V"
- **EAN birincil eşleştirme anahtarıdır** — shoplar (fiyat/stok) ve diğer kaynaklar (tyrelabelling.eu vb.) EAN üzerinden size_variant'a bağlanır
- Fallback: EAN yoksa (marka+model+ebat+hız/yük endeksi) > fuzzy match
- Çakışma çözümü: marka sitesi canonical kabul edilir, shop verisi `offer` olur

## Yasal / etik notlar
- robots.txt ve site şartlarına uyulur; kamuya açık ürün katalog verisi hedeflenir
- Nazik tarama: düşük istek hızı, cache, gerekirse resmi API/feed
- Kişisel veri toplanmaz; fiyat/stok gibi ticari veriler kaynak ve zaman damgasıyla saklanır
