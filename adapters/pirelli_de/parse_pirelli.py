"""Pirelli DE SKU sayfası parse.

Veri sayfada kaçışlı JSON içinde `"ean_code"` alanıyla gelir.
regex ile ana alanları çıkarıyoruz.
"""

from __future__ import annotations

import re
from html import unescape as _u

from adapters.base import SkuRecord

BRAND = "Pirelli"
SOURCE = "pirelli_de"
_SEASON = {"sommer": "summer", "winter": "winter", "all season": "allseason",
           "ganzjahres": "allseason", "all-season": "allseason", "cinturato all season sf3": "allseason"}


def _get(text: str, key: str) -> str | None:
    m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else None


def _get_bool(text: str, key: str) -> bool:
    m = re.search(rf'"{key}"\s*:\s*(true|false)', text)
    return m.group(1) == "true" if m else False


def _get_int(text: str, key: str) -> int | None:
    m = re.search(rf'"{key}"\s*:\s*(\d+)', text)
    return int(m.group(1)) if m else None


def parse(html: str, url: str) -> list[SkuRecord]:
    text = _u(html.replace('\\"', '"').replace("&quot;", '"'))
    ean = _get(text, "ean_code")
    if not ean:
        return []
    load_speed = _get(text, "load_speed_rating") or ""
    m = re.match(r"(\d+/\d+|\d+)([A-Z]+)", load_speed)
    load_index = m.group(1) if m else None
    speed_index = m.group(2) if m else None
    sd = _get(text, "search-description") or ""  # "205/55R16"
    mi = re.match(r"(\d+)/(\d+)R(\d+)", sd)
    width = int(mi.group(1)) if mi else None
    ratio = int(mi.group(2)) if mi else None
    rim = int(mi.group(3)) if mi else None

    # etiket: ecoLabelPrints içinde
    grading = {}
    gm = re.search(r'"ecoLabelPrints"\s*:\s*\[([^\]]+)\]', text)
    if gm:
        for k, gkey in [("noise_class", "ZGradingRn"), ("fuel_class", "ZGradingRr"),
                        ("wet_grip_class", "ZGradingWg")]:
            val = re.search(rf'"{gkey}"\s*:\s*"([^"]+)"', gm.group(1))
            if val:
                grading[k] = val.group(1)
        ndb = re.search(r'"ZGradingRnVal"\s*:\s*"?(\d+)"?', gm.group(1))
        if ndb:
            grading["noise_db"] = int(ndb.group(1))

    product_name = url.rstrip("/").rsplit("/", 1)[-1]  # .../cinturato-p7
    model = ""
    if "/produkt/" in url:
        model = url.split("/produkt/")[1].split("/")[0].replace("-", " ").title()
    extra={"search_desc": sd, "ecolabel": _get(text, "ecolabel")}

    rec = SkuRecord(
        brand=BRAND,
        model=model,
        width=width,
        aspect_ratio=ratio,
        rim_diameter=rim,
        load_index=load_index,
        speed_index=speed_index,
        xl=_get_bool(text, "is-xl"),
        runflat=_get_bool(text, "run_flat"),
        ean=ean,
        cai=_get(text, "matnr"),
        fuel_class=grading.get("fuel_class"),
        wet_grip_class=grading.get("wet_grip_class"),
        noise_db=grading.get("noise_db"),
        noise_class=grading.get("noise_class"),
        source_url=url,
        extra={"search_desc": sd, "ecolabel": _get(text, "ecolabel")},
    )
    return [rec]