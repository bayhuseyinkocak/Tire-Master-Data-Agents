# Keşif Raporu: Michelin DE (PİLOT)

- **URL:** https://www.michelin.de
- **Tip:** brand_site
- **Tarih:** 2026-10-02
- **Keşif yöntemi:** webfetch + curl (ham HTML raw/michelin_de/2026-10-02/ altında)

## 1. Mevcut Veriler
| Veri | Var mı? | Nerede? | Not |
|---|---|---|---|
| Model listesi | ✅ | Sitemap + `/auto/browse-tyres/by-category/...` | ~50 binek/PKU model sayfası |
| Ebat varyantları | ✅ | Ürün sayfası SSR JSON'u | `displaySize`, `ratio`, `diameters`, `loadIndex`, `speedIndex` |
| EAN | ✅ | Ürün sayfası, SKU başına | örn. `3528700541885` — eşleştirme anahtarı! |
| Michelin CAI kodu | ✅ | SKU başına (`cai`) | marka-içi makale no |
| EU etiketi | ✅ | SKU başına | `rollingResistanceClass`, `wetGripClass`, `exteriorNoiseValue/Class`, `euDirectiveNumber: 740/2020` |
| 3PMSF / M+S / Runflat / XL | ✅ | SKU başına boolean alanlar | `has3pmsf`, `hasmpluss`, `isRunflat`, `extraLoad` |
| Desen / yapı | ✅ | `treadPattern` (ASY), `structure` (R) | |
| Görseller | ✅ | `dxm.contentcenter.michelin.com` DAM | URL'de ebat kodu: `..._3528707773869_tire_michelin_primacy-4_205-slash-55-r16-91v_a_main...` |
| Fiyat | ⚠️ kısmen | `minPrice` alanı var, yönlendirme bayiye | marka sitesi satın alınabilir katalog gibi çalışıyor |
| Kullanıcı yorumları | ✅ | JSON-LD `aggregateRating` + tekil review'lar | örn. 4.8/5, 2206 yorum |
| Teknik özellikler / Eigenschaften | ✅ | Ürün sayfası island JSON | |

## 2. URL & Navigasyon Yapısı
- Sitemap: `https://www.michelin.de/sitemap.xml` (~4.7 MB, tüm ürün URL'leri içerir, hreflang ile ülke varyantları dahil)
- Model sayfası: `/auto/tyres/michelin-<model-slug>` (örn. `/auto/tyres/michelin-primacy-4-plus`)
- Kategori: `/auto/browse-tyres/by-category/...` (autoreifen, offroad-and-suv-reifen, ...)
- Ebat listesi: `/auto/browse-tyres/by-dimension/{width}/{ratio}/{rim}` — 333 ebat sayfası
- Tek site global CDN üzerinde; hreflang ile `.com`, `.at`, `.ch` varyantları — **aynı platform diğer ülke siteleri için de kullanılabilir**

## 3. Teknik Tespitler
- **Rendering:** Astro SSR (Svelte island'ları). Ürün verisi sayfada gömülü: `<astro-island props="...">`
  içinde Astro tuple formatı `[0, value]` — HTML-escape açılarak (`&quot;` → `"`) parse edilir. **Playwright gerekmez, httpx yeterli.**
- **Dahili API:** robots.txt `/api/`yı yasaklıyor; gömülü SSR JSON kullanılmalı, API'ye istek atılmamalı
- **Bot koruması:** belirgin bir engel görülmedi (curl 200); yine de nazik tarama
- **robots.txt:** katalog sayfaları açık; filtre parametreleri (`?tyreSize=`, `?currentPage=`...) ve `/api/` disallow. Sitemap'teki temiz URL'lerden kazımak uyumlu yol.
- **Sitemap:** var, ürün URL'leri içeriyor — ana crawl kaynağı budur
- Her SKU nesnesinde geçerlilik: `endDate` alanı var (örn. "2026-12-31")

## 4. Kazıma Stratejisi Önerisi
1. `sitemap.xml` → `/auto/tyres/michelin-*` URL listesi (~50 model)
2. Her model sayfasını indir → `raw/michelin_de/<tarih>/<model>.html`
3. `astro-island` props'tan SKU listesini parse et (.escape + tuple decode)
4. İstek hızı: ≤1 istek/sn, goroutine yok; tek seferde ~50 sayfa = zararsız
- Tahmini hacim: ~50 model × ort. 20-80 SKU
- **Veri zenginliği beklentinin üstünde:** EAN + tam EU etiketi marka sitesinden geliyor; shop eşleştirmesi için mükemmel temel.
- Açık sorular: `minPrice` güncel mi, geçerliliği ne?; ebat sayfalarındaki kartlar ek alan içeriyor mu (kontrol edildi: liste kartları görsel+link ağırlıklı).
