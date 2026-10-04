---
name: tires-agent-ops
description: Tires Master Data projesinde scraper ajanı ekleme/güncelleme ritüeli: scouts keşif raporu, adapters altına agent+parse, agents_registry.yaml misyon kaydı, report_progress entegrasyonu, validate --json ve Ajan Kontrol Paneli kartı. Use when the user says "yeni ajan ekle", "yeni kaynak adapter", "ajan registry güncelle", "misyon şablonu", "tires-agent-ops", "ajan kontrol paneline ajan", or wants to onboard a tire shop/brand site scraper in this project. Do NOT use for generic scrapers outside Tires Master Data, dashboard UI polish without agent onboarding, or non-agent data analysis.
---

# Tires Master Data — Ajan Ops

Her kaynak site = 1 ajan. Panel süreci **başlatmaz**; yalnızca `scrape_run` + `agents_registry.yaml` üzerinden izler.

## Important (vazgeçilmez kurallar)

1. **Ham veri asla silinmez** — her yanıt `raw/<kaynak>/<YYYY-MM-DD>/` altına yazılır.
2. **EAN birincil eşleştirme anahtarı** — yoksa marka+model+ebat+endeks fallback.
3. **Nazik tarama** — `BaseAgent.delay` (varsayılan 1 sn/istek); robots.txt ve site şartlarına uy.
4. **Canlı ilerleme zorunlu** — döngüde `self.report_progress(pages_done, pages_total, note)` çağrılır; yoksa panel çubuğu boş kalır.
5. **`ensure_progress_columns`** — her ajanın `_ensure_schema` veya `run` başlangıcında çağrılır (eski `tires.db` uyumu).
6. **Komut formatı** — registry `komut` alanı: `uv run python -m adapters.<kaynak>.agent` (PATH'te `~/.local/bin/uv`).
7. Panel **süreç başlatmaz / kill etmez** — komut terminalde çalıştırılır.

## Ritüel: yeni ajan ekleme (sırayla)

### 1. Keşif — `scouts/<kaynak>.md`
Şablon: `scouts/_TEMPLATE.md` veya skill içindeki `assets/scout-template.md`.
Zorunlu başlıklar: Mevcut veriler (EAN/EU etiketi/görsel var mı), URL & API yapısı, robots.txt, rendering (httpx mı Playwright mı), kazıma stratejisi + riskler.

### 2. Adapter — `adapters/<kaynak>/`
```
adapters/<kaynak>/
  __init__.py
  agent.py          # BaseAgent alt sınıfı: discover_urls + run döngüsü
  parse.py          # (veya parse_*.py) ham → list[SkuRecord]
```
Şablon: `assets/agent-skeleton.py`.

`agent.py` checklist:
- [ ] `source_name = "<kaynak>"` (DB `source.name` ile birebir)
- [ ] `discover_urls()` → `list[str]`
- [ ] `parse(html|payload, url)` → `list[SkuRecord]`
- [ ] `run()` içinde `self._run_id = run_id` + `ensure_progress_columns(conn)`
- [ ] Döngüde `report_progress` (keşif sonrası `0,total`, her adımda `i,total,note`)
- [ ] `INSERT OR IGNORE` / `COALESCE` upsert (idempotent koşu)
- [ ] `__main__` → `~/.local/bin/uv run python -m adapters.<kaynak>.agent [limit]`

### 3. Registry — `agents_registry.yaml`
Şablon: `assets/registry-entry.yaml`.
Alanlar: `rol`, `marka`, `base_url`, `komut`, `scout`, `misyon` (id/ad/ipucu), `son_mesaj`.
Misyon id'leri standart: `kesif`, `kazi` (veya `parse`), `dogrulama`, `teslim`.
Panel bu adımları DB + validate özetinden etiketler (`tamam` / `çalışıyor` / `kısmi` / `hata` / `uyarı` / `sırada`).

### 4. Kısa test koşusu
```bash
cd "<proje kökü>"
~/.local/bin/uv run python -m adapters.<kaynak>.agent 5
```
Kontrol:
- [ ] `scrape_run` yeni satır + `pages_done/pages_total/note/pid` dolu
- [ ] `raw/<kaynak>/<bugün>/` dosyaları var
- [ ] DB'ye en az 1 `size_variant` / `tire_model` yazıldı (veya scout'ta "kaynakta yok" notu var)
- [ ] Dashboard → **Ajanlar** sekmesinde kart + ilerleme çubuğu canlı

### 5. Doğrulama
```bash
~/.local/bin/uv run python -m normalize.validate --json
```
`total_issues` kabul edilebilir olmalı; yeni kural gerekiyorsa `normalize/validate.py` `RULES` listesine ekle.

### 6. Panel kartı (otomatik)
Registry satırı + `scouts/<kaynak>.md` + DB `source` kaydı yeterli. Kart açılmazsa:
- `source.name` = registry anahtarı mı?
- `source` tablosunda satır var mı? (`INSERT OR IGNORE INTO source`)
- `load_registry()` — YAML sözlük mü?

## Hata giderme

| Belirti | Neden | Çözüm |
|---|---|---|
| Panel çubuğu boş | `report_progress` yok / kolonlar migration öncesi | Döngüye ekle; `ensure_progress_columns` |
| "database is locked" | eşzamanlı write (DB Browser, ikinci ajan) | WAL + `timeout=30`; GUI'yi kapat; tek yazar |
| Koşu hep "çalışıyor" / "kesildi" | `finished_at` yazılmadı (kill) | Yeni koşu aç; yarım satır idempotent yazım nedeniyle güvenli |
| Kart görünmüyor | registry anahtarı ≠ `source.name` | İkisini birebir eşitle |
| `validate` hata | parse format kirliliği | `RULES` + parse regex düzelt; ham veri zaten `raw/`'da |

## Örnek tetikler

- "Yeni bir ajan ekle: reifendirekt.de" → keşif raporu → adapter iskeleti → registry → limit testi → validate.
- "Pirelli misyonunu güncelle" → sadece `agents_registry.yaml` misyon bloğu.
- "Ajan neden panelde yok?" → yukarıdaki hata tablosu.
