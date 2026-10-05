# Konuşma Katmanı (K1.5) — Veri + Niyet Planı

Durum: **uygulandı** (2026-10-05 — 4.1–4.5; dış kontrol bekliyor)
Tarih: 2026-10-05
Ana plan: `PLAN.md` · Panel planı: `docs/ajan-paneli-PLAN.md`
Graf bilgisi: `graphify-out/` (bu proje); bitişte `graphify update .`

---

## 1. Amaç

Kullanıcı panelden ajanlara doğal soru sorsun ve **doğru olgu** alsın (uydurma değil):

| Kullanıcı sorusu | Beklenen cevap özü |
|---|---|
| Kaç SKU / ürün topladın? | Toplam + marka kırılımı |
| Eksik veri var mı? | EAN/ebat/etiket vs. eksik sayıları (`validate`) |
| En son ne zaman çalıştın? | Okunur tarih + kayıt + hata + status |
| Şu an çalışıyor mu? | `pages_done/total` + note |
| Hata / kural ihlali? | `scrape_run.errors` + validate kuralları |
| Ne yapıyorsun / misyon? | Mevcut misyon (zaten var) |

**Öncelik:** veri araçları + niyet eşleme. **LLM şart değil** — anahtar yoksa fallback bu soruları doğru cevaplamalı. LLM sonradan cümleyi yazar.

### Kapsam dışı (şimdilik)

- `start_run` / panelden tarama başlatma (K2)
- Alt ajan → ayrı avatar (Agent Panel işi; transcript yeter)
- Jev / System One kararı (bkz. §6 — sonraki)
- Agent Panel UI değişikliği (bus sözleşmesi aynı kalır)

---

## 2. Mevcut durum (graf + kod)

God nodes: `BaseAgent`, `AgentRuntime`, `Bridge`, `LlmConfig`, `validate.collect`.

```
User text (WS) → bus_server.on_client_message
              → AgentRuntime.dispatch_user / reply_turn
              → Tools (scrape_status, count_skus) + [LLM | fallback]
              → agent.say / thinking / done / subspawn   → Agent Panel UI
```

Bugün Tools yetersiz: tarih yok, marka kırılımı yok, kalite yok. `_fallback_say` 3 kalıp biliyor.

Şemada ilgili alanlar (`docs/db/schema.sql`):

- `scrape_run`: `started_at`, `finished_at`, `records_in`, `errors`, `status`, `pages_done`, `pages_total`, `note`
- `size_variant` / `tire_model` / `brand` / `eu_label` — sayımlar
- `normalize/validate.collect()` — zaten makine-okur kalite özeti üretiyor (dashboard da kullanıyor)

---

## 3. Sözleşmeler (değiştirme)

### Bus (Agent Panel)

Yeni olay **ekleme**. Kullanılanlar:

`user.message`, `agent.called`, `agent.thinking`, `agent.say`, `agent.handoff`, `agent.pair`/`unpair`, `agent.task`, `agent.subspawn`, `agent.subdone`, `agent.done`

Mevcut WS: `ws://127.0.0.1:8787/bus` (gerçek) · `:8788/bus` (mock)
Panel pack: `Agent Panel/src/packs/tires-master-data.json` (`llm` + `persona` + agent id: `MICHELIN` / `CONTI` / `PIRELLI`)

### Registry

`agents_registry.yaml` — **zorunlu alan ekleme**. İleride isteğe bağlı `llm:` / `persona:` override (pack’te de olabilir; runtime zaten okuyor).

---

## 4. Teknik iş — sırayla

### 4.1 Araçlar (`bridge/agent_runtime.py` → `Tools`)

Hepsi **salt okuna** DB. DB yok / şema yok → kısa Türkçe hata metni (bugünkü gibi), exception fırlatma.

1. **`scrape_status(source)`** — bugüne ek olarak `started_at` / `finished_at`’i okunur ver (örn. `2026-10-04 14:32` veya `3 gün önce`). Bitmişse: `bitti · X kayıt · Y hata · status=… · 2026-10-04 14:32`. Çalışıyorsa sayfa ilerleme + note.
2. **`count_skus(source|None)`** — `None` ise 3 marka dökümü + toplam; `source` verilirse o markanın SKU’su + yine toplam.
   - Eşleme: `SOURCE_TO_ID` / `brand.name` (michelin_de→Michelin …). `brand` tablosunda ad yoksa `size_variant` join’i kırılmaz; kırılım `brand.name` üzerinden.
3. **`run_history(source, limit=3)`** — son N `scrape_run`: tarih · kayıt · hata · status.
4. **`data_quality()`** — `normalize.validate.collect()` sar (import yolu: `normalize.validate`; DB yolu tutarlı olsun — `collect()` kendi `tires.db` yolunu kullanıyorsa gerekirse `db_path` parametresi ekle **veya** araçta aynı SQL’i tekrar yazma; `collect()`’ü genişletip `db_path` alması temiz).

Önerilen **metin çıktı formatı** (fallback ve LLM context aynı dili konuşsun):

```
count_skus → "toplam 12345 | Michelin 4000 · Continental 3500 · Pirelli 4845"
data_quality → "eksik EAN 12 · eksik ebat 3 · kural ihlali 5 (yük endeksi: 2, ean 13 hane: 3)"
run_history → "2026-10-04 14:32 bitti 148 kayıt 0 hata ok | …"
```

### 4.2 Niyet eşleme (`_fallback_say` veya küçük `route_intent`)

Önce kalıp, sonra anlam. Sıra önemli: daha spesifik önce.

| Intent | Tetik (TR, küçük harf) | Araç(lar) |
|---|---|---|
| `count` | kaç, adet, sku, ürün, topladın, kayıt sayısı | `count_skus` |
| `quality` | eksik, boş, kalite, validate, kural, ihlal | `data_quality` |
| `history` | ne zaman, en son, son koşu, kaç kez, history | `run_history` + `scrape_status` |
| `status` | durum, çalışıyor, ilerleme, ne yapıyorsun, misyon, görev | `scrape_status` + `mission_lines` |
| `error` | hata, error, patladı | `scrape_status` + `data_quality` |
| `hello` | merhaba, selam, nasılsın, naber | seed + kısa status |
| `other` | — | seed + status (bugünki gibi) |

Çok intent tek cümlede ise önce gelen kazansın (ör. “kaç kayıt ve eksik var mı” → `count` + ikinci cümlecik için `quality` — v1: **tek intent**, ikinciye “istersen eksik veriye de bakayım” demek yeterli).

`dispatch_user`: mention yoksa ilk persona (bugünki davranış). Çoklu mention’a dokunma.

### 4.3 LLM context (anahtar varsa)

`reply_turn` içinde her tur **tüm** araç özetlerini mesaja göm (bugün 2 satır):

```
[araçlar]
scrape_status: …
count_skus: …
data_quality: …
run_history: …
[soru]
…
```

`system_prompt`: “Sayı ve tarihleri araç çıktısından aynen kullan; uydurma. Bilmiyorsan ‘kayıtta yok’ de. 1–3 cümle.”

Fallback hâlâ anahtar yoksa veya `chat_completion` None dönerse devrede.

### 4.4 Çoklu LLM sağlayıcı (bu turda **iskelet** yeter — UI değil)

`bridge/llm.py` zaten OpenAI-uyumlu. `LlmConfig.from_dict` provider preset’ini desteklesin:

| `provider` | varsayılan `baseUrl` | varsayılan `apiKeyEnv` | örnek model |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `deepseek` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `mimo` | (kullanıcı doldurur) | `MIMO_API_KEY` | (kullanıcı) |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | (kullanıcı) |
| `custom` / yok | mevcut alanlar | mevcut `apiKeyEnv` | mevcut `model` |

Kural: `baseUrl` / `model` / `apiKeyEnv` her zaman override edilebilir; provider sadece şablon açar. **Bu turda panelde seçim UI’ı yok**; pack / registry `llm.provider` alanıyla kullanılır. Anahtar yoksa fallback.

> Jev bu listeye **girmez** — o chat değil, ayrı karar API’si (§6).

### 4.5 Testler

`bridge/test_agent_runtime.py` genişlet:

1. Eski smoke (fallback, subspawn, task) — kırılmasın
2. Intent: “kaç SKU” → say text’inde sayı/marka; “eksik veri” → quality anahtarları; “ne zaman çalıştın” → tarih/status
3. Boş `:memory:` DB → araçlar kırılmaz, “henüz … yok” döner
4. `from_dict` provider şablonu (env sahte key ile)

Çalıştırma:

```bash
uv run python bridge/test_agent_runtime.py
uv run python bridge/smoke_ws_e2e.py          # varsa mock ile
uv run python -m normalize.validate --json    # araçlarla tutarlı mı
graphify update .
```

---

## 5. Dosya haritası

| Dosya | Ne |
|---|---|
| `bridge/agent_runtime.py` | Tools (count/run_history/data_quality), intent, system_prompt, context |
| `bridge/llm.py` | `provider` preset şablonları |
| `bridge/test_agent_runtime.py` | yeni intent + araç testleri |
| `normalize/validate.py` | gerekirse `collect(db_path=…)` (eski çağrılar bozulmasın) |
| `docs/konusma-katmani-PLAN.md` | bu dosya — uygulamada saparsan güncelle |
| `PLAN.md` | faz notu (bir madde) |

**Dokunma:** adapters scrape döngüsü, schema (zorunlu değil), Agent Panel, `mock_bus_server` (istersen intent senaryosu ekle — zorunlu değil).

---

## 6. Jev (System One) — sonraki tur, doğru yer

Karar: **cevap yazmakta değil; niyet/routing’te** kullanılabilir.

Uygun sorular (ilgide kal):

- `choice`: hangi araç / hangi ajan cevaplasın / intent sınıfı  
- `boolean`: bu mesaj K2 `start_run` istiyor mu · riskli mi  
- `score`: aciliyet (opsiyonel)

Uygun **olmayan**: “123 SKU var” cümlesi, özet, serbest sohbet → LLM/şablon.

Geçiş: 4.2 kalıpları belirli sorularda kırılınca `bridge/jev.py` (HTTP `POST /v1/systemone` veya TypeSafe SDK) + eşik kodda (`confidence < 0.6` → fallback/insan). Anahtar: `TYPESAFE_API_KEY` (veya Vercel AI Gateway). **OpenAI chat endpoint’i Jev’i açmaz.**

---

## 7. Agent Panel / frontend notu (graphify + panel)

Uygulama Tires’ta; paneli bozma. Bilinmesi gereken:

- Panel **UI metni üretmez**; `src/bus/` olaylarını dinler. Cevap kalitesi tamamen `agent.say` `text`’inde — Tools/niyet doğruysa panel doğru görünür.
- Transport: pack’te `local` | `ws`. Gerçek konuşma için `bus_server.py` + pack `ws://127.0.0.1:8787/bus`.
- Agent id’ler: `MICHELIN`, `CONTI`, `PIRELLI` (`SOURCE_TO_ID` ile aynı kalmalı).
- Konuşma girişi: `user.message`; cevap: `agent.say` (+ `to` alanı mention varsa). thinking/idle parıltısı için `agent.thinking`.
- Pack `llm` alanı zaten parse ediliyor; provider eklense panel pack JSON’u yeterli (UI sonra).

---

## 8. Kabul (sen uygula, ben kontrol)

- [ ] “kaç SKU” → toplam + 3 marka, DB’den gerçek sayı
- [ ] “eksik veri var mı” → validate özet (EAN/ebat/ihlal)
- [ ] “en son ne zaman çalıştın” → tarih + kayıt + hata (çalışıyorsa ilerleme)
- [ ] Anahtar **yokken** yukarı üçü fallback ile doğru
- [ ] Boş DB / şemasız DB çökmez
- [ ] LLM anahtarı varsa sayılar hâlâ araçtan (uydurma yok)
- [ ] `start_run` yok; yazma aracı yok
- [ ] `uv run python bridge/test_agent_runtime.py` OK
- [ ] `graphify update .` çalıştırıldı
- [ ] Agent Panel `ws` + tires pack ile en az bir uçtan uca konuşma (istersen ben yaparım)

### Kontrol listesi (bana “hazır” deyince)

1. `test_agent_runtime.py` çıktısı  
2. `normalize/validate.py --json` ile `data_quality` tutarlılığı  
3. Kodda yalnız salt-okuma SQL (`INSERT/UPDATE/DELETE` yok — `scrape_run` progress yazan adapter’lar hariç)  
4. Intent tablosu ile kodun aynı 6 sınıfı kapsaması  
5. Gerekirse mock `ws://…:8788` ile canlı bir tur

---

## 9. Örnek diyalog (beklenen)

```
sen:  @PIRELLI kaç SKU topladın?
PIRELLI: toplam 12345 · Michelin 4000 · Continental 3500 · Pirelli 4845. Şu an: bitti · …

sen:  @MICHELIN eksik veri var mı?
MICHELIN: eksik EAN 12 · eksik ebat 3 · kural ihlali 5 (…).

sen:  @CONTI en son ne zaman çalıştın?
CONTI: 2026-10-04 14:32’de bitti · 210 kayıt · 1 hata · status=partial.
```
