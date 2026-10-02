# Keşif Raporu: Continental DE

- **URL:** https://www.continental-reifen.de
- **Tip:** brand_site
- **Tarih:** 2026-10-02
- **Keşif yöntemi:** curl (ham dosyalar raw/continental_de/2026-10-02/ altında)

## 1. Mevcut Veriler
| Veri | Var mı? | Nerede? | Not |
|---|---|---|---|
| Model listesi | ✅ | Sitemap `/products/car/tires/<model>/` | ~50 binek model sayfası (tam liste tr/van dahil daha fazla) |
| Ebat varyantları | ✅ ama API üzerinden | ürün arama servisi | sayfada SSR yok, client-side |
| EAN | ❓ | API yanıtında muhtemel | keşifte doğrulanamadı |
| EU etiketi | ✅ | API + DAM ikonları (`eu-fuel-efficency.svg`, `eu-wet-grip.svg`, `eu-noise.svg`) | değerler API'den gelir |
| Teknolojiler | ✅ | `data-tire-search-config`: contiseal, ssr(runflat), contisilent, pmsf, ms, ev_compatible | |
| Görseller | ✅ | AEM DAM `/content/dam/...` | |
| Fiyat | ❌ | marka sitesi fiyat göstermiyor | |
| Kullanıcı yorumu | kısmen? | `application/ld+json` x3 mevcut | |

## 2. URL & Navigasyon Yapısı
- Sitemap: `/sitemap-de-de.xml` (~1482 URL; `products/` altında 1052 URL)
- Model sayfası: `/products/car/tires/<model-slug>/` (örn. `/products/car/tires/premiumcontact-7/`)
- Arama sayfaları: `/products/car/product-search/search-by-size/`, `search-by-vehicle/`
- Platform: **Adobe Experience Manager (AEM)** — içerik DAM + content fragment'larında

## 3. Teknik Tespitler
- **Robot politikası:** `User-agent: * | Allow: /` + sitemap. En rahat kaynak.
- **Rendering:** SSR statik içerik + ürün verisi **client-side API** çağrısıyla:
  - `https://api.productsearch.continental-tires.com/v1/continental/{alanKodu}/{locale}/sbs`
  - API anahtarı sayfada gömülü: `data-service-key` (public, frontend'in kullandığı)
  - Keşifte 403 döndü — doğru yol/parametre JS'ten (`clientlib-site` bundle'ında `apiCodeAsString`)
    tersine mühendislikle çıkarılacak. **Fallback:** tarayıcı (DevTools network) ile gerçek çağrıyı yakalayıp belgelemek gerek.
- **DAM görselleri + EU ikonları** aynı CDN'de, erişim açık.

## 4. Kazıma Stratejisi Önerisi (2026-10-02 güncellemesi)
**API kesinleşti.** Sayfadaki `data-service-url` + `data-service-key` ile:

```
GET https://api.productsearch.continental-tires.com/v1/continental/de/de/plt/sbs?articles=true
Header: x-api-key: <sayfadaki key>
```

- **Tek çağrı tüm DE binek kataloğu:** 74 ürün + 3016 article (SKU), tamamında **EAN** (~7 MB JSON; API S3'ye yönlendirip imzalı indirme veriyor, `curl -L` gerekli)
- Yön: `de/de` (apiCodeAsString = `${country}/${lang}`), alan kodu `plt` (PLT = passenger/light truck)
- Filtre parametreleri (`width=205...`) yalnızca `current_filters`'a yansıyor, veriyi süzmüyor

**API'den alınan (tam listeler):**
- Ürün: `zmi_mkt_text_long` (model), segment (`Van All Season`...), `season` (Summer/Winter/All Season), `ev_compatible` / `designedForEVs`, `oeManufacture` (örn. IVECO), `headline_approved`, `introText_approved`, `techHighlightsDescriptionsB2C1-3/B2B1-3_approved`, `bulletpointsIntern1-3`
- Article/SKU: **ean**, `artNo11Digit` (arti no = Michelin CAI muadili), **upc**, `productlinename`, `axlePosition`, `tyreType` (TL/TT), `seasonKey`, `mSMark` (M+S), `E2_3PMSF`, `EPREL_REG_E2`, `REG_REF_E2` (740/2020), `microsite_eulabel_link` (contimediacenter etiket sayfası!), `FUEL_EFFI_E2`, `WET_GRIP_E2`, `ROLL_NOISE_E2`, `NOISE_LEV_E2`, US `*_BR` (brutto) alanları, `widthMM`, `aspectRatio`, `rimDiameterInch`, `sizeDesignation`, `loadSpeedIndex`, `speed1`, `tireWeight`, `treadDepth`, `maxLoad`, `maxSpeed`, basınç alanları, `silent`, `sealant`, `ppmProdSince`, `modificationDate`, `pogSegment1/2`
- **EAN eksiksiz: 3016/3016**

**API'de OLMAYAN / ek kaynak gerektiren:**
- Görseller (PDP/DAM'de; API'de image alanı yok)
- Desen kodu (muhtemelen `microsite_eulabel_link` sayfasında / EPREL)
- Araç uyum (başka arama modu: `sbv` / `gts`)
- PDP'deki sayfa düzeni/SEO metinleri (opsiyonel; API metinleri yeterli)

**Üretim stratejisi:** PDP taramak zorunda değiliz — 1 API çağrısı katalog verisini verir. Görseller için PDP'leri ikinci aşamada (ya da sitemap'ten model sayfaları) çekmek yeterli. Sitemap ~1050 URL; API 74 ürün → modeller için temiz model listesi + tüm EAN'ler tek yerde.

## 5. Ham örnek
`raw/continental_de/2026-10-02/conti_all.json` (filtresiz tam katalog, 7.2 MB)
