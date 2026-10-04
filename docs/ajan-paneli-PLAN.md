# Ajan Kontrol Paneli — Proje Planı

Durum: Faz 1+2 uygulandı (2026-10-03); Faz 3+ opsiyonel
Tarih: 2026-10-03
Ana proje: `Tires Master Data` (bkz. `PLAN.md`)

## 1. Amaç
Scraper ajanlarını (michelin_de, continental_de, pirelli_de ve ileridekileri) panelde
"çalışanlar" gibi izlemek: hangi ajan çalışıyor, görevi ne, ne topladı, ne kaldı, hatası var mı.
Her ajan kartı kendi misyonunu (görev listesi) ve durumunu taşır.

## 2. Kapsam
1. **Ajan kartları** — kaynak başına: durum rozeti (hazır / çalışıyor / hata / pasif),
   son koşu zamanı, toplanan varyant sayısı, hata oranı, kalite skoru (validate.py).
2. **Canlı ilerleme** — ajan her N sayfada ilerleme yazar; panelde %X çubuk + "şu an şu sayfada".
3. **Misyon panosu** — her ajanın görev listesi (keşif → kazı → doğrulama → teslim),
   hangi adım tamam/sırada/bloklu. "Düşünen çalışan" etkisi: ajanın son log satırı
   ("205/55R16 SKU'ları ayrıştırılıyor...") kartta konuşma balonu gibi görünür.
4. **Keşif durumu** — `scouts/*.md` var/yok haritası; keşfedilmemiş marka/shop uyarıları.
5. **Komut kısayolu** — her ajan için kopyalanabilir çalıştırma komutu
   (`uv run python -m adapters.<kaynak>.agent`). Panel süreç başlatmaz (güvenlik).
6. **Kalite kartı** — `normalize/validate.py` özeti (kural ihlali: N/9) ajan altında rozet.

Kapsam dışı: ajanları panelden başlat/durdur (Streamlit'ten süreç yönetimi riskli; faz 2'ye ertelenir).

## 3. Mimari
```
adapters/base.py        → report_progress(pages_done, pages_total, note)  (yeni)
adapters/*/agent.py     → döngüde report_progress çağrısı                 (küçük dokunuş)
docs/db/schema.sql      → scrape_run: pages_done, pages_total, note, pid  (ALTER)
agents_registry.yaml    → ajan künyesi: ad, kaynak, misyon adımları, komut, sahip
dashboard/app.py        → yeni sekme "Ajanlar"; kart ızgarası + misyon listesi
normalize/validate.py   → --json çıktısı (panel için makine-okur özet)
```

İlerleme yazımı: SQLite'a minik UPDATE (aynı tires.db, WAL açık tutulmalı —
çoklu süreç çakışmasında `database is locked` hatasını önler; `busy_timeout=30` zaten var).

## 4. "Düşünen çalışanlar" konsepti (mini misyon)
Her ajan bir **rol** taşır (keşifçi / toplayıcı / doğrulayıcı) ve bir **misyon** listesi:

```yaml
# agents_registry.yaml (örnek)
pirelli_de:
  rol: toplayici
  komut: uv run python -m adapters.pirelli_de.agent
  misyon:
    - Sitemap keşfi                      # tamam
    - SKU sayfalarını indir (5071)       # çalışıyor  → ilerleme çubuğu
    - Parse + DB yazımı                  # sırada
    - validate.py kontrolü               # sırada
  son_mesaj: "950/5071 sayfa indirildi"
```

Panel bu YAML + DB ilerleme alanlarını birleştirip gösterir. İleride (opsiyonel, faz 3)
ajanlar gerçek LLM misyon yürütebilir (sub-agent ile keşif/dogrulama görevleri);
şimdilik kavramsal kabuk + veri katmanı yeterli.

## 5. Görsel kimlik — bloub (github.com/jeremy-prt/bloub) değerlendirmesi
- Ne: x.ai bot avatarının SVG rekreasyonu; tek şekil 14 durum arasında morph eder,
  gözler bağımsız morph. Vue 3 + TS, MIT lisanslı. `engine.sample(t)` saf fonksiyon —
  DOM'suz test edilebilir, dondurulmuş kare (frozenAt) üretilebilir.
- Kullanım: her ajan kartına **avatar** olarak uyarlanabilir (farklı renk/şekil = farklı ajan;
  idle/wink/orbit = çalışıyor/hata/boşta durumları). "Düşünen çalışan" hissi için birebir.
- Teknik not: Vue component'i Streamlit'e gömülmez; SVG/PNG export veya `#planche`
  durum panosu gibi statik varlıklar olarak alınır (bloub export destekliyor).
  Alternatif: aynı yaklaşımı saf SVG/React ile panelde yeniden üretmek.
- Karar: **opsiyonel güzel-olur katmanı** (faz 2). Çekirdek veri/panel işlevi bloub'suz biter.
- **Uygulama (2026-10-03, Faz 3):** Vue yerine `dashboard/avatars.py` — saf SVG + CSS keyframe.
  Marka rengi × durum motion (`idle`/`orbit`/`tilt`/`sleep`/`shake`/`faded`). MIT bloub kodu
  kopyalanmadı; aynı görsel dil (tek gövde + bağımsız gözler).

## 6. Skill / agent gereksinimleri
| İhtiyaç | Öneri |
|---|---|
| Proje içi tekrarlanan ajan-ops işleyişi | Yeni skill: `tires-agent-ops` (`.mimocode/skills/tires-agent-ops/SKILL.md`) — ajan ekleme, registry güncelleme, misyon şablonu, validate bağlama adımları. `skill-creator` + `mimo-skill-authoring` skill'leriyle yazılır |
| Keşif (yeni site incelemesi) | Zaten var: `websearch` + Browser Use (IAB) |
| Panel veri kontrolü | `data-analytics` (istatistik/rapor) opsiyonel |
| Aşağıdakiler gerekmez | playwright (şimdilik), threejs/imagegen |

Yeni ajan ekleme ritüeli (skill bunu standartlaştırır):
`scouts/<kaynak>.md` → `adapters/<kaynak>/{agent,parse}.py` → registry'ye satır →
test koşusu → validate → panel kartı otomatik görünür.

## 7. Fazlar ve kabul kriterleri
- **Faz 1 — İlerleme altyapısı:** base.py `report_progress` + schema ALTER + registry YAML.
  Kabul: Pirelli koşusu sırasında panel çubuğu ilerler, `pages_done` artar.
- **Faz 2 — Ajanlar sekmesi:** kart ızgarası + misyon listesi + son_mesaj + komut kopyala.
  Kabul: 3 ajanın 3'ü de kart olarak görünür, misyon adımları doğru işaretli.
- **Faz 3 (opsiyonel):** bloub avatarları — **tamam** (saf SVG, `dashboard/avatars.py`); faz 4 (opsiyonel): LLM'li gerçek misyon sub-agent'ları.

## 8. Yeni sohbeti başlatma metni
Yeni sohbet şunla başlasın:

> Tires Master Data projesinde "Ajan Kontrol Paneli" uygulanacak.
> Önce `docs/ajan-paneli-PLAN.md`, `PLAN.md` ve `MEMORY.md`'yi oku.
> Faz 1'den başla: adapters/base.py'ye report_progress ekle, schema'ya ilerleme
> alanlarını aç, agents_registry.yaml oluştur. Faz 2'de dashboard'a "Ajanlar"
> sekmesini ekle. Kod yazmadan önce bu planı onaylat.
