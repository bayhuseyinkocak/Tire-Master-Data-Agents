"""Continental DE productsearch API yanıtı → SkuRecord listesi.

Kaynak: .../v1/continental/de/de/plt/sbs?articles=true
Yanıt: {num_articles, num_products, products: [{article metni..., articles: [SKU...]}]}
"""

from __future__ import annotations

from adapters.base import SkuRecord

BRAND = "Continental"
SOURCE = "continental_de"

_SEASON = {"Summer": "summer", "Winter": "winter", "All Season": "allseason"}


def _num(v):
    if v is None or v == "" or v == 0:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def _bool(v) -> bool:
    return str(v).lower() in {"x", "true", "yes", "1"}


def _load_speed(ls: str | None):
    """'91V' → ('91','V'); '(100Y)' → ('100','Y'); '121/120R' → ('121/120','R')."""
    if not ls:
        return None, None
    s = str(ls).strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    if "/" in s:
        left, right = s.split("/", 1)
        i = 0
        while i < len(right) and right[i].isdigit():
            i += 1
        idx = right[:i]
        speed = right[i:] or None
        return (f"{left}/{idx}" if idx else left, speed)
    i = 0
    while i < len(s) and s[i].isdigit():
        i += 1
    return (s[:i] or None, s[i:] or None)


def parse(payload: dict) -> list[SkuRecord]:
    records: list[SkuRecord] = []
    for product in payload.get("products") or []:
        model = product.get("zmi_mkt_text_long") or product.get("exportName_approved") or ""
        if not model:
            continue
        season = _SEASON.get(product.get("season") or "", None)
        desc_parts = [product.get("headline_approved"), product.get("introText_approved")]
        tech = [
            product.get("techHighlightsDescriptionsB2C1_approved"),
            product.get("techHighlightsDescriptionsB2C2_approved"),
            product.get("techHighlightsDescriptionsB2C3_approved"),
        ]
        description = " ".join(p for p in desc_parts + tech if p) or None
        for art in product.get("articles") or []:
            load_index, speed_index = _load_speed(art.get("loadSpeedIndex") or art.get("loadSpeedIndex2_Dtacs"))
            width = _num(art.get("widthMM"))
            ratio = _num(art.get("aspectRatio"))
            rim = _num(art.get("rimDiameterInch"))
            mkt = art.get("marketingText") or ""
            rec = SkuRecord(
                brand=BRAND,
                model=model,
                season=season or _SEASON.get(art.get("season") or "", None),
                width=width,
                aspect_ratio=ratio,
                rim_diameter=rim,
                load_index=load_index,
                speed_index=speed_index,
                xl=("XL" in mkt.upper()),
                runflat=False,  # Continental SSR/runflat kodu ayrı; sonradan eklenebilir
                ean=str(art.get("ean")) if art.get("ean") else None,
                cai=str(art.get("artNo11Digit")) if art.get("artNo11Digit") else None,
                upc=str(art.get("upc")) if art.get("upc") else None,
                position=art.get("axlePosition") or art.get("axlePositionKey"),
                axle_position=art.get("axlePosition") or art.get("axlePositionKey"),
                tyre_type=art.get("tyreType") or art.get("tyreTypeKey"),
                tire_weight=_num(art.get("tireWeight")),
                tread_depth=_num(art.get("treadDepth")),
                max_load=_num(art.get("maxLoad")),
                max_speed=_num(art.get("maxSpeed")),
                silence=_bool(art.get("silent")) if art.get("silent") is not None else None,
                sealant=_bool(art.get("sealant")) if art.get("sealant") is not None else None,
                oe_manufacture=art.get("oeManufacture"),
                eprel_reg_no=str(art.get("EPREL_REG_E2")) if art.get("EPREL_REG_E2") not in (None, 0) else None,
                label_url=art.get("microsite_eulabel_link"),
                fuel_class=art.get("FUEL_EFFI_E2") or art.get("FUEL_EFFI_BR"),
                wet_grip_class=art.get("WET_GRIP_E2") or art.get("WET_GRIP_BR"),
                noise_db=_num(art.get("ROLL_NOISE_E2") or art.get("ROLL_NOISE_BR")),
                noise_class=art.get("NOISE_LEV_E2") or art.get("NOISE_LEV_BR"),
                snow_grip=_bool(art.get("E2_3PMSF")) or _bool(art.get("seasonAllSeason3PMSF")),
                m_s=_bool(art.get("mSMark")),
                is_ev_compatible=_bool(art.get("ev_compatible")) or _bool(art.get("designedForEVs")),
                source_url=f"https://www.continental-reifen.de/products/car/tires/{model.lower().replace(' ', '-')}/",
                model_description=description,
                model_headline=product.get("headline_approved"),
                extra={
                    "pogSegment1": art.get("pogSegment1"),
                    "pogSegment2": art.get("pogSegment2"),
                    "sizeDesignation": art.get("sizeDesignation"),
                    "loadSpeedIndex": art.get("loadSpeedIndex"),
                    "speed1": art.get("speed1"),
                    "ppmProdSince": art.get("ppmProdSince"),
                    "modificationDate": art.get("modificationDate"),
                    "suffix": art.get("suffix"),
                    "season": art.get("season"),
                    "ev_compatible": art.get("ev_compatible"),
                    "designedForEVs": art.get("designedForEVs"),
                    "product_group": product.get("product_group"),
                    "pogProductGroupSegment": product.get("pogProductGroupSegment"),
                },
            )
            if rec.width:
                records.append(rec)
    return records
