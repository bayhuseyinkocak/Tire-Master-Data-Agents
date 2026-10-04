"""Ajan kartları için bloub avatarları (bloub-for-python).

Gözü olan durumlar → `export.svg.animated_svg` (CSS keyframe göz matrisleri;
idle döngüsünde göz kırpma matrix içinde scaleY olarak gelir).
Gözü olmayan durumlar (sleep/alert/thinking/…) → donmuş `Bot.svg` karesi.

Panel durumu → bloub state:
  hazır     → idle      (animasyonlu + göz kırpma)
  çalışıyor → orbit     (animasyonlu göz + hafif nabız)
  kısmi     → notify    (animasyonlu)
  kesildi   → sleep     (donmuş — engine'de göz yok)
  yarım     → sleep
  hata      → alert     (donmuş — engine'de göz yok)
  pasif     → egg       (animasyonlu)
"""

from __future__ import annotations

from functools import lru_cache

try:
    from bloub import Bot
    from bloub.export.svg import animated_svg
    from bloub.states import STATE_BY_ID
    BLOUB_AVAILABLE = True
except ImportError:  # pragma: no cover
    Bot = None  # type: ignore
    animated_svg = None  # type: ignore
    STATE_BY_ID = {}  # type: ignore
    BLOUB_AVAILABLE = False

AGENT_SKIN: dict[str, tuple[str, str, str]] = {
    "michelin_de": ("cercle", "bleu", "neutre"),
    "continental_de": ("galet", "orange", "attentif"),
    "pirelli_de": ("goutte", "rouge", "curieux"),
    "default": ("squircle", "gris", "neutre"),
}

STATE_TO_BLOUB = {
    "hazır": "idle",
    "çalışıyor": "orbit",
    "kısmi": "notify",
    "kesildi": "sleep",
    "yarım": "sleep",
    "hata": "alert",
    "pasif": "egg",
}

# Göz keyframe'i olmayan (pose gövdede) durumlar — donuk render
FROZEN_STATES = {"sleep", "alert", "thinking", "exclaim", "burst", "comet"}

# CSS wrapper nabzı (gövde animasyonu bloub'un animated_svg'inde yok)
WRAP_CSS = """
<style>
@keyframes bl-bob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-3px)} }
@keyframes bl-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.04)} }
.bl-wrap-orbit { animation: bl-bob 1.1s ease-in-out infinite; display:inline-block }
.bl-wrap-idle  { animation: bl-pulse 3.2s ease-in-out infinite; display:inline-block }
.bl-wrap-notify{ animation: bl-bob 1.6s ease-in-out infinite; display:inline-block }
</style>
"""


def colors_for(source: str) -> tuple[str, str, str]:
    return AGENT_SKIN.get(source, AGENT_SKIN["default"])


def motion_for(state_label: str) -> str:
    return STATE_TO_BLOUB.get(state_label, "idle")


def _expression_for(bloub_state: str, default: str) -> str:
    return {
        "sleep": "somnolent",
        "alert": "colere",
        "notify": "surpris",
        "orbit": "curieux",
        "idle": default,
        "egg": "blase",
    }.get(bloub_state, default)


def _state_duration(bloub_state: str) -> float:
    d = STATE_BY_ID.get(bloub_state) or {}
    return float(d.get("duration") or 2.4)


def _eye_matrices(
    bot, bloub_state: str, duration: float, samples: int = 28
) -> tuple[list[list[str]], float | None]:
    """Göz matris keyframe'leri — idle'da göz kırpma scaleY olarak matrix'te.

    Orbit gibi bazı karelerde tek göz kalabilir; animated_svg sabit göz
    sayısı ister. Yalnızca 2 gözlü kareleri topla; yoksa animasyon yok.
    """
    bot.engine.set_state(bloub_state, 0.0)
    out: list[list[str]] = []
    t_ok: float | None = None
    n_eyes: int | None = None
    for i in range(samples):
        t = duration * i / max(samples - 1, 1)
        frame = bot.engine.sample(t)
        if len(frame.eyes) != 2:
            continue
        if n_eyes is None:
            n_eyes = 2
            t_ok = t
        out.append([e.matrix for e in frame.eyes])
    return out, t_ok


def avatar_svg(
    source: str,
    state_label: str = "hazır",
    size: int = 88,
    title: str | None = None,
    animated: bool = True,
) -> str:
    """Bloub SVG — tercihen animated (göz keyframe + blink)."""
    if not BLOUB_AVAILABLE:
        return (
            f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
            f'background:#ccc;line-height:{size}px;text-align:center">?</div>'
        )

    shape, color, expression = colors_for(source)
    bloub_state = motion_for(state_label)
    expression = _expression_for(bloub_state, expression)
    label = title or f"{source} · {state_label}"
    uid = f"av-{source}-{bloub_state}-{'a' if animated else 's'}"

    bot = Bot(shape=shape, color=color, expression=expression, paper="#ffffff")
    duration = _state_duration(bloub_state)

    use_anim = animated and bloub_state not in FROZEN_STATES
    matrices: list[list[str]] = []
    t_body = duration * 0.5
    if use_anim:
        matrices, t_ok = _eye_matrices(bot, bloub_state, duration)
        if t_ok is not None:
            t_body = t_ok
        if len(matrices) < 2:
            use_anim = False

    bot.engine.set_state(bloub_state, 0.0)
    base = bot.svg(t=t_body, size=size, uid=uid, aria_label=label)

    if use_anim and matrices and len(matrices) >= 2:
        svg = animated_svg(base, matrices, duration)
    else:
        svg = base

    wrap_cls = {
        "idle": "bl-wrap-idle",
        "orbit": "bl-wrap-orbit",
        "notify": "bl-wrap-notify",
    }.get(bloub_state, "")
    wrap_open = f'<div class="{wrap_cls}" style="width:{size}px;height:{size}px">' if wrap_cls \
        else f'<div style="width:{size}px;height:{size}px">'
    return f"{WRAP_CSS}{wrap_open}{svg}</div>"


@lru_cache(maxsize=256)
def avatar_svg_cached(
    source: str,
    state_label: str = "hazır",
    size: int = 88,
    animated: bool = True,
) -> str:
    return avatar_svg(source, state_label, size=size, animated=animated)


def render_in_streamlit(st, source: str, state_label: str, size: int = 88) -> None:
    html = avatar_svg_cached(source, state_label, size=size, animated=True)
    st.markdown(html, unsafe_allow_html=True)
