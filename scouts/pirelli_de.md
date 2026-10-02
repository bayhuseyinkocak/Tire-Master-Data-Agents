# Keşif Raporu: Pirelli DE

- **URL:** https://www.pirelli.com/tyres/de-de
- **Tip:** brand_site
- **Tarih:** 2026-10-02
- **Keşif yöntemi:** curl (ham dosyalar raw/pirelli_de/2026-10-02/ altında)

## 1. Mevcut Veriler
| Veri | Var mı? | Nerede? | Not |
|---|---|---|---|
| Model listesi | ✅ | `sitemap_pkw_de-de.xml` | `.../reifenkatalog/produkt/<model>` |
| Ebat varyantları | ✅ **SKU seviyesinde URL!** | `.../produkt/<model>/<w>_<r>-r<rim>/<load><speed>-` | ~6544 PKW URL'si — model×ebat sayfaları ayrı |
| EU etiketi | ✅ | gömülü JSON `dynamicData` | `min/maxWetGrip`, `min/maxRollingResistance`, `min/maxRollingNoise(+Value)` |
| Kullanıcı yorumları | ✅ | gömülü JSON `tyreRatings` + tekil yorumlar | wetGrip/comfort/noise/mileage/performance puanları |
| Ürün Özellikleri | ✅ | gömülü JSON (tag/title/text) + FAQ JSON-LD | teknoloji, iş birliği markaları (TÜV, araç OEM) |
| Görseller | ✅ | `dynamic_engine/assets/...` CDN | |
| EAN | ❓ | görülmedi; SKU sayfalarında aranacak | adapter aşamasında doğrulanır |
| Fiyat | ❌ | yok | |
| Araç-montaj eşleşmesi | ✅ | sitemap `nach-automarke-suchen/...` | marka/model/yıl → lastik önerisi (bonus veri!) |

## 2. URL & Navigasyon Yapısı
- Sitemap indeksi: `https://www.pirelli.com/tyres/de-de/sitemap_index_tyres_de-de.xml`
  - `sitemap_pkw_de-de.xml` (6544 URL, ürün+SKU), `sitemap_pkw_brand_de-de_0.xml` (araç uyum), `sitemap_dealers_de-de.xml`
- Ürün: `/tyres/de-de/pkw/reifenkatalog/produkt/<model-slug>`
- SKU: `.../produkt/<model-slug>/<w>_<ratio>-r<rim>/<load><speed>-`
- Locale yapısı ortak: `/tyres/<ulke-dil>/...` (tr-tr, en-gb vs. aynı platform → diğer pazarlar bedava)

## 3. Teknik Tespitler
- **robots.txt:** katalog açık; sadece filtre parametreleri, `?product=`, `*/sheet/details/*` ve servis yolları disallow.
- **Rendering:** SSR (React), tüm veri **sayfa içinde `\u`-escape'li gömülü JSON** olarak geliyor
  (`dynamicData`, `tyreRatings`, ürün blokları) — httpx yeterli, playwright gerekmez.
- **LD+JSON:** Breadcrumb + FAQ blokları statik.
- **Bot koruması:** keşifte engel görülmedi (curl 200).

## 4. Kazıma Stratejisi Önerisi
1. `sitemap_pkw_de-de.xml` → model ve SKU URL listeleri (regex ile ayır: `/\d+_\d+-r\d+/`)
2. Model sayfaları: metin/teknoloji/rating aralıkları; SKU sayfaları: spesifik etiket + varyant verisi
3. İstek hızı ≤1 istek/sn; ~6544 URL ≈ 3-4 saat tek işçiyle — nazik tarama penceresi gerekli
- Risk: SKU sayfasında etiketin tam değeri (min/max yerine tek değer) doğrulanmalı — pilot adapter'da kontrol.
- **Bonus:** `nach-automarke-suchen` araç→lastik uyum verisi ayrı bir tablo için değerli kaynak.
