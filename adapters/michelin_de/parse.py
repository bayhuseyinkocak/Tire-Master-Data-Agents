"""Michelin DE ürün sayfası parse.

Veri, Astro SSR sayfasındaki <astro-island props="..."> içinde gömülü.
Format: HTML-escape'li, Astro/devalue tuple serilizasyonu `[index, value]`.
SKU nesneleri `cai` + `ean` alanlarıyla tanınır; alanlar regex ile pencereden çıkarılır.
"""

from __future__ import annotations

import html
import json
import re

from adapters.base import SkuRecord

BRAND = "Michelin"
SOURCE = "michelin_de"


def _unwrap(html_text: str) -> str:
    """HTML entitelerini açar; tuple `[0, v]` sarmalını `[0,v]` serde bırakır."""
    return html.unescape(html_text)


def _field(obj_text: str, key: str):
    m = re.search(
        rf'"{key}"\s*:\s*\[\s*\d+\s*,\s*("[^"]*"|\d+|true|false|null)\s*\]',
        obj_text,
    )
    if not m:
        return None
    raw = m.group(1)
    if raw == "null":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith('"'):
        return raw[1:-1]
    return int(raw)


def _kv(obj_text: str, key: str) -> str | None:
    """labelling dizisindeki {"key":[0,k],"value":[0,"v"]} çiftlerinden değer alır."""
    m = re.search(
        rf'"key"\s*:\s*\[\s*\d+\s*,\s*"{key}"\s*\]\s*,\s*"value"'
        rf'\s*:\s*\[\s*\d+\s*,\s*"([^"]+)"\s*\]',
        obj_text,
    )
    return m.group(1) if m else None


def _kv_int(obj_text: str, key: str) -> int | None:
    v = _kv(obj_text, key)
    return int(v) if v and v.isdigit() else None


def _sku_blocks(text: str) -> list[str]:
    """`"cai"` içeren nesne pencerelerini bulur (SKU başına ~1200 karakter)."""
    blocks = []
    for m in re.finditer(r'"cai"\s*:', text):
        start = max(0, m.start() - 3500)
        blocks.append(text[start:m.start() + 700])
    return blocks


def _json_object_after(text: str, key: str) -> dict | None:
    """`"key":[0,{...}]` nesnesini dengeli süslü parantezle çıkarır."""
    m = re.search(rf'"{key}"\s*:\s*\[\s*\d+\s*,\s*\{{', text)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    import json as _json
                    return _json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def parse(html_text: str, url: str) -> list[SkuRecord]:
    text = _unwrap(html_text)

    model = None
    m = re.search(r'"productlinename"\s*:\s*\[\s*\d+\s*,\s*"([^"]+)"', text)
    if m:
        model = m.group(1).title()
    season = None
    m = re.search(r'"productlineseason"\s*:\s*\[\s*\d+\s*,\s*"([^"]+)"', text)
    if m:
        raw_season = m.group(1).lower().replace("-", "").replace(" ", "")
        season = {"allseason": "allseason", "summer": "summer", "winter": "winter"}.get(raw_season)

    description = None
    m = re.search(r'<meta name="description" content="([^"]+)"', html_text)
    if m:
        description = m.group(1)

    model_slug = url.rstrip("/").rsplit("/", 1)[-1]
    core = model_slug.removeprefix("michelin-")
    image_urls = sorted(set(
        u for u in re.findall(
            r"https://dxm\.contentcenter\.michelin\.com/\S+?\.(?:webp|png|jpe?g|gif|avif)",
            text,
        )
        if core in u
    ))

    records = []
    for blk in _sku_blocks(text):
        size = _field(blk, "displaySize") or ""
        m = re.match(r"(\d+)/(\d+)R(\d+)\s*(\d+)?([A-Z]+)?", size)
        width, ratio, rim = (int(m.group(i)) for i in (1, 2, 3)) if m else (None, None, None)
        rec = SkuRecord(
            brand=BRAND,
            model=model or "",
            season=season,
            width=width,
            aspect_ratio=ratio,
            rim_diameter=rim,
            load_index=(str(_field(blk, "loadIndex")) if _field(blk, "loadIndex") is not None else None),
            speed_index=_field(blk, "speedIndex"),
            xl=bool(_field(blk, "extraLoad")) or bool(re.search(r"\bXL\b", size, re.I)),
            runflat=bool(_field(blk, "isRunflat")),
            ean=_field(blk, "ean"),
            cai=_field(blk, "cai"),
            label_url=(
                f"https://www.tyrelabelling.eu/EU/2020-740/de/{_field(blk,'cai')}_fcs_de.pdf"
                if _field(blk, "cai") else None
            ),
            structure=_field(blk, "structure"),
            position=_field(blk, "position"),
            tread_pattern=_field(blk, "treadPattern"),
            start_date=_field(blk, "startDate"),
            end_date=_field(blk, "endDate"),
            fuel_class=_kv(blk, "rollingResistanceClass"),
            wet_grip_class=_kv(blk, "wetGripClass"),
            noise_db=_kv_int(blk, "exteriorNoiseValue"),
            noise_class=_kv(blk, "exteriorNoiseClass"),
            snow_grip=bool(_field(blk, "has3pmsf")),
            ice_grip=bool(_field(blk, "isIceGrip")),
            m_s=bool(_field(blk, "hasmpluss")),
            stud=bool(_field(blk, "stud")) if _field(blk, "stud") is not None else False,
            type_tube=_field(blk, "typeTube"),
            is_green=bool(_field(blk, "isGreen")),
            regrooving=_json_object_after(blk, "regrooving"),
            source_url=url,
            model_description=description,
            image_urls=image_urls,
        )
        if rec.width:
            records.append(rec)
    return records
