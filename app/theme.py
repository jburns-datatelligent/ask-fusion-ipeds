"""Datatelligent brand for the public app: tokens, page CSS, chart styling, logo.

Tokens match the Fusion dashboard (streamlit_app.py) so the public demo and the product read
as one brand. The orange used for TEXT is the AA-safe #b83b16; the brighter #ff7540 is only
ever a fill or accent, where it does not need 4.5:1 against white.
"""

from __future__ import annotations

import base64
import copy
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"

PRIMARY = "#4a6471"      # slate: headings, primary series
DARK = "#364853"         # body text
ORANGE = "#ff7540"       # accent fills only
ORANGE_TEXT = "#b83b16"  # AA on white
BROWN = "#3b1d17"        # from the mark
SURFACE = "#f5f7f8"
BORDER = "#dde2e6"
MUTED = "#566a79"
WHITE = "#ffffff"

# Categorical order for charts: adjacent series are far apart in hue and lightness.
CHART_SEQ = [PRIMARY, ORANGE, "#9fb3be", BROWN, "#d9a38a", "#2f7d6d", "#c6c7c9", "#7a5c99"]


@lru_cache(maxsize=None)
def svg_data_uri(name: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode((ASSETS / name).read_bytes()).decode()


def brand_chart(spec: dict) -> dict:
    """Restyle the agent's Vega-Lite spec in DT colours without changing what it plots."""
    spec = copy.deepcopy(spec)
    spec.pop("$schema", None)
    spec["width"] = "container"
    spec.setdefault("height", 300)
    spec["background"] = "transparent"
    # Fit the container INCLUDING axis titles; otherwise the y-axis title is clipped at the left.
    spec["autosize"] = {"type": "fit-x", "contains": "padding"}
    spec["padding"] = {"left": 6, "right": 6, "top": 4, "bottom": 4}
    title = spec.get("title")
    if isinstance(title, str):
        spec["title"] = {"text": title}
    if isinstance(spec.get("title"), dict) and isinstance(spec["title"].get("text"), str):
        spec["title"]["text"] = wrap(spec["title"]["text"], 40)  # Vega never wraps; a phone clipped it
    mark = spec.get("mark")
    mark_type = mark.get("type") if isinstance(mark, dict) else mark
    encoding = spec.get("encoding") or {}
    # The agent hard-codes matplotlib blue on single-series marks; DT slate instead. A chart that
    # colours by a field keeps its encoding and gets CHART_SEQ from config.
    if isinstance(mark, dict) and "color" in mark and "color" not in encoding:
        mark["color"] = PRIMARY
    if mark_type == "bar":
        # Seen live: domain [94, 99] plus x2 = {"datum": 94}, so every bar started at 94 and a
        # 98% vs 94% ranking read as a 5x difference. A constant baseline goes; a field-driven
        # x2/y2 (a genuine range bar) stays.
        for ch in ("x2", "y2"):
            if isinstance(encoding.get(ch), dict) and "datum" in encoding[ch]:
                del encoding[ch]
    for ch, enc in encoding.items():
        if not isinstance(enc, dict) or enc.get("type") != "quantitative":
            continue
        axis = enc.get("axis")
        # SI formats ("~s") collapse 261,000 and 261,487 into two ticks both reading "261k".
        if isinstance(axis, dict) and "s" in str(axis.get("format", "")):
            axis["format"] = ",.12~g"
        # A bar's length is the value: a bar axis that does not start at zero misstates it.
        if mark_type == "bar" and ch in ("x", "y") and isinstance(enc.get("scale"), dict):
            enc["scale"].pop("zero", None)
            enc["scale"].pop("domain", None)
    cfg = spec.setdefault("config", {})
    cfg.update({
        "font": "Inter, -apple-system, Segoe UI, Arial, sans-serif",
        "range": {"category": CHART_SEQ},
        "view": {"stroke": None},
        "title": {"color": DARK, "fontSize": 14, "fontWeight": 600, "anchor": "start", "frame": "group", "offset": 12},
        "axis": {"labelColor": MUTED, "titleColor": MUTED, "gridColor": "#edf0f2", "domainColor": BORDER,
                 "tickColor": BORDER, "labelFontSize": 12, "titleFontSize": 12, "titleFontWeight": 500,
                 "labelLimit": 220},
        "legend": {"labelColor": DARK, "titleColor": MUTED, "labelFontSize": 12, "titleFontSize": 12,
                   "orient": "bottom", "symbolType": "circle", "labelLimit": 320},
        # Counts read as 200,000 and rates as 80. A bare "," lets Vega fill in a precision from
        # the tick step, which printed "8e+1" and "2e+5"; an explicit one is left alone. An axis
        # format the agent set in the encoding still wins over config.
        "axisQuantitative": {"format": ",.12~g"},
        "line": {"color": PRIMARY, "strokeWidth": 3},
        "point": {"color": PRIMARY, "filled": True, "size": 60},
        "bar": {**cfg.get("bar", {}), "color": PRIMARY, "cornerRadiusEnd": 3},
        "arc": {"stroke": WHITE},
    })
    return spec


def wrap(text: str, width: int) -> str | list[str]:
    """Split a chart title into lines of at most `width` characters (Vega takes a list)."""
    if len(text) <= width:
        return text
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
  --dt-primary: {PRIMARY}; --dt-dark: {DARK}; --dt-orange: {ORANGE}; --dt-orange-text: {ORANGE_TEXT};
  --dt-surface: {SURFACE}; --dt-border: {BORDER}; --dt-muted: {MUTED};
  --dt-radius: 14px; --dt-shadow: 0 1px 2px rgba(54,72,83,.06), 0 8px 24px rgba(54,72,83,.06);
}}
html, body, [class*="st-"], .stMarkdown, button, input, textarea, select {{
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}}
/* ...but never on icon glyphs: they are ligatures in Material Symbols and read as words otherwise. */
[data-testid="stIconMaterial"], span[class*="material-symbols"], .material-symbols-rounded {{
  font-family: "Material Symbols Rounded" !important; }}
/* Streamlit chrome off: this is a web page, not a notebook. */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stAppDeployButton"] {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
[data-testid="stAppViewContainer"] {{ background: linear-gradient(180deg, #fbfcfc 0%, {SURFACE} 100%); }}
[data-testid="stMainBlockContainer"], .block-container {{
  max-width: 980px; padding-top: 1.25rem; padding-bottom: 7rem;
}}
h1, h2, h3, h4 {{ color: var(--dt-dark); letter-spacing: -0.015em; }}
p, li {{ color: var(--dt-dark); }}
a {{ color: var(--dt-orange-text); }}

/* ---------- top bar */
.af-topbar {{ display:flex; align-items:center; justify-content:space-between; gap:1rem;
  padding: .25rem 0 1rem; border-bottom: 1px solid var(--dt-border); margin-bottom: 1.5rem; }}
.af-brand {{ display:flex; align-items:center; gap:.9rem; text-decoration:none; }}
.af-brand img {{ height: 54px; width:auto; }}
.af-divider {{ width:1px; height:30px; background: var(--dt-border); }}
.af-product {{ display:flex; flex-direction:column; line-height:1.15; }}
.af-product b {{ font-size: 1.05rem; color: var(--dt-dark); font-weight:700; white-space:nowrap; }}
.af-cta .short {{ display:none; }}
.af-product span {{ font-size: .78rem; color: var(--dt-muted); font-weight:500; }}
.af-cta {{ display:inline-flex; align-items:center; gap:.4rem; padding:.5rem .95rem; border-radius:999px;
  border:1.5px solid var(--dt-orange); color: var(--dt-orange-text) !important; font-weight:600;
  font-size:.85rem; text-decoration:none !important; white-space:nowrap; background:#fff; }}
.af-cta:hover {{ background: #fff4ef; }}

/* ---------- hero (gate) */
.af-eyebrow {{ display:inline-block; font-size:.75rem; font-weight:700; letter-spacing:.08em;
  text-transform:uppercase; color: var(--dt-orange-text); background:#fff1ea; padding:.3rem .65rem;
  border-radius:999px; margin-bottom: .9rem; }}
.af-hero h1 {{ font-size: clamp(1.9rem, 3.6vw, 2.6rem); line-height:1.12; margin: 0 0 .9rem; font-weight:700; }}
.af-hero h1 em {{ font-style:normal; color: var(--dt-primary);
  background: linear-gradient(180deg, transparent 62%, rgba(255,117,64,.28) 62%); }}
.af-hero p.lead {{ font-size: 1.05rem; line-height:1.6; color: var(--dt-muted); margin-bottom: 1.25rem; }}
.af-proof {{ list-style:none; padding:0; margin: 0 0 1.5rem; display:grid; gap:.65rem; }}
.af-proof li {{ display:flex; gap:.7rem; align-items:flex-start; font-size:.95rem; line-height:1.45; }}
.af-proof li::before {{ content:""; flex:0 0 9px; height:9px; margin-top:.45rem; border-radius:50%;
  background: var(--dt-orange); box-shadow: 0 0 0 4px rgba(255,117,64,.15); }}
.af-sample {{ background:#fff; border:1px solid var(--dt-border); border-radius: var(--dt-radius);
  padding: 1rem 1.1rem; box-shadow: var(--dt-shadow); }}
.af-sample .q {{ font-weight:600; color: var(--dt-dark); font-size:.92rem; margin-bottom:.45rem; }}
.af-sample .a {{ font-size:.9rem; color: var(--dt-muted); line-height:1.55; }}
.af-sample .a b {{ color: var(--dt-dark); }}
.af-sample .src {{ font-size:.75rem; color: var(--dt-muted); margin-top:.6rem; }}

/* the contact card is the form itself */
[data-testid="stForm"] {{ background:#fff; border:1px solid var(--dt-border) !important;
  border-radius: var(--dt-radius); padding: 1.4rem 1.4rem .6rem !important; box-shadow: var(--dt-shadow); }}
.af-form-title {{ font-size:1.15rem; font-weight:700; color: var(--dt-dark); margin:0 0 .2rem; }}
.af-form-sub {{ font-size:.85rem; color: var(--dt-muted); margin:0 0 .9rem; }}
.af-fineprint {{ font-size:.75rem; color: var(--dt-muted); line-height:1.5; }}

/* ---------- inputs: visible fields on a white card */
[data-testid="stForm"] [data-baseweb="input"], [data-testid="stForm"] [data-baseweb="select"] > div,
[data-testid="stTextInput"] [data-baseweb="input"] {{
  border: 1.5px solid #cfd6db !important; border-radius: 10px !important; background: #fff !important; }}
[data-testid="stForm"] [data-baseweb="input"]:focus-within, [data-testid="stForm"] [data-baseweb="select"] > div:focus-within,
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{
  border-color: var(--dt-primary) !important; box-shadow: 0 0 0 3px rgba(74,100,113,.12); }}
[data-testid="stForm"] input {{ background: #fff !important; }}
[data-testid="stWidgetLabel"] p {{ font-size: .84rem !important; font-weight: 600 !important; color: var(--dt-dark) !important; }}
[data-testid="stCheckbox"] p {{ font-size: .84rem !important; line-height: 1.45; font-weight: 400 !important; color: var(--dt-muted) !important; }}

/* ---------- buttons */
button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--dt-primary) !important; border-color: var(--dt-primary) !important; color:#fff !important;
  border-radius: 10px !important; font-weight:600 !important; min-height: 2.75rem; }}
button[kind="primary"] p, [data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {{
  color: #fff !important; font-weight: 600 !important; font-size: .95rem !important; }}
button[kind="primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  background: var(--dt-dark) !important; border-color: var(--dt-dark) !important; }}
/* question chips */
[data-testid="stBaseButton-secondary"] {{
  border-radius: 12px !important; border:1px solid var(--dt-border) !important; background:#fff !important;
  color: var(--dt-dark) !important; text-align:left !important; justify-content:flex-start !important;
  min-height: 3.1rem; padding: .55rem .9rem !important; line-height:1.35 !important; font-weight:500 !important;
  box-shadow: 0 1px 2px rgba(54,72,83,.04); transition: border-color .15s, box-shadow .15s, transform .15s; }}
[data-testid="stBaseButton-secondary"] > div, [data-testid="stBaseButton-secondary"] [data-testid="stMarkdownContainer"] {{
  justify-content:flex-start !important; text-align:left !important; width:100%; }}
[data-testid="stBaseButton-secondary"] p {{ font-size:.9rem !important; white-space: normal !important; text-align:left; }}
[data-testid="stBaseButton-secondary"]:hover {{ border-color: var(--dt-orange) !important;
  box-shadow: 0 4px 14px rgba(255,117,64,.14); transform: translateY(-1px); }}
[data-testid="stBaseButton-tertiary"] {{ color: var(--dt-muted) !important; font-weight:500 !important; }}
[data-testid="stBaseButton-tertiary"]:hover {{ color: var(--dt-orange-text) !important; }}

/* ---------- empty state */
.af-welcome h2 {{ font-size: 1.6rem; margin: 0 0 .35rem; font-weight:700; }}
.af-welcome p {{ color: var(--dt-muted); margin:0 0 1.1rem; font-size:1rem; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: .25rem; border-bottom:1px solid var(--dt-border); }}
[data-testid="stTabs"] button[role="tab"] {{ padding: .5rem .9rem; }}
[data-testid="stTabs"] button[role="tab"] p {{ font-weight:600; font-size:.9rem; color: var(--dt-muted); }}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p {{ color: var(--dt-dark); }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background: var(--dt-orange); }}

.af-scope {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:.8rem; }}
.af-scope div {{ background:#fff; border:1px solid var(--dt-border); border-radius:12px; padding:.85rem 1rem; }}
.af-scope b {{ display:block; font-size:.85rem; color: var(--dt-dark); margin-bottom:.3rem; }}
.af-scope span {{ font-size:.82rem; color: var(--dt-muted); line-height:1.5; }}

/* ---------- conversation */
[data-testid="stChatMessage"] {{ background: transparent; padding: .25rem 0; gap: .9rem; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ flex-direction: row-reverse; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {{
  flex: 0 1 auto; max-width: 80%; margin-left: auto !important; margin-right: 0 !important; background: var(--dt-primary); border-radius: 16px 16px 4px 16px;
  padding: .7rem 1rem; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p {{ color:#fff; font-weight:500; }}
[data-testid="stChatMessageAvatarUser"] {{ display:none; }}
[data-testid="stChatMessage"]:has(img) [data-testid="stChatMessageContent"] {{
  background:#fff; border:1px solid var(--dt-border); border-radius: 4px 16px 16px 16px;
  padding: 1rem 1.2rem .6rem; box-shadow: var(--dt-shadow); min-width: 0; }}
[data-testid="stChatMessage"] img {{ width: 34px; height: 34px; }}
[data-testid="stChatMessageContent"] table {{ font-size:.88rem; }}

.af-progress {{ display:flex; flex-direction:column; gap:.5rem; padding:.2rem 0 .4rem; }}
.af-step {{ display:flex; align-items:center; gap:.6rem; font-size:.9rem; color: #9aa7b0; }}
.af-step i {{ width:18px; height:18px; border-radius:50%; border:2px solid #cfd6db; flex:0 0 18px;
  display:inline-flex; align-items:center; justify-content:center; font-style:normal; font-size:.7rem; }}
.af-step.done {{ color: var(--dt-muted); }}
.af-step.done i {{ background: var(--dt-primary); border-color: var(--dt-primary); color:#fff; }}
.af-step.now {{ color: var(--dt-dark); font-weight:600; }}
.af-step.now i {{ border-color: var(--dt-orange); border-top-color: transparent; animation: af-spin .8s linear infinite; }}
@keyframes af-spin {{ to {{ transform: rotate(360deg); }} }}
.af-wait {{ font-size:.8rem; color: var(--dt-muted); margin-top:.35rem; }}

.af-source {{ display:inline-flex; align-items:center; gap:.4rem; font-size:.78rem; color: var(--dt-muted);
  background: var(--dt-surface); border:1px solid var(--dt-border); border-radius:999px; padding:.25rem .7rem;
  margin:.2rem 0 .5rem; }}
.af-source::before {{ content:""; width:7px; height:7px; border-radius:50%; background: var(--dt-orange); }}
.af-followups-label {{ font-size:.78rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
  color: var(--dt-muted); margin: .9rem 0 .4rem; }}
.af-error {{ border-left: 3px solid var(--dt-orange); padding: .4rem .8rem; background:#fff7f3; border-radius: 6px;
  color: var(--dt-dark); font-size: .92rem; }}
[data-testid="stExpander"] details {{ border:1px solid var(--dt-border); border-radius: 10px; background: #fbfcfc; }}
[data-testid="stExpander"] summary p {{ font-size:.85rem; font-weight:600; color: var(--dt-muted); }}

/* ---------- composer: a docked bar, not another card on the page */
[data-testid="stBottom"] > div {{
  background: #e9eef1 !important; border-top: 1px solid #d3dbe0;
  box-shadow: 0 -10px 30px rgba(54,72,83,.10); }}
[data-testid="stBottomBlockContainer"] {{ padding-top: 1rem !important; padding-bottom: .6rem !important; }}
[data-testid="stChatInput"] {{
  border: 2px solid var(--dt-primary) !important; border-radius: 18px !important; background:#fff !important;
  box-shadow: 0 6px 20px rgba(54,72,83,.16); min-height: 3.6rem; padding-left: .35rem;
  transition: border-color .15s, box-shadow .15s; }}
[data-testid="stChatInput"] > div, [data-testid="stChatInput"] [data-baseweb] {{ background: transparent !important; border: 0 !important; }}
[data-testid="stChatInput"]:hover {{ box-shadow: 0 8px 26px rgba(54,72,83,.22); }}
[data-testid="stChatInput"]:focus-within {{
  border-color: var(--dt-orange) !important; box-shadow: 0 0 0 4px rgba(255,117,64,.18), 0 8px 26px rgba(54,72,83,.18); }}
[data-testid="stChatInputTextArea"] {{ font-size: 1rem !important; color: var(--dt-dark) !important; }}
[data-testid="stChatInputTextArea"]::placeholder {{ color: #5f707b !important; opacity: 1; }}
[data-testid="stChatInputSubmitButton"] {{ background: var(--dt-orange) !important; border-radius: 12px !important;
  width: 2.5rem !important; height: 2.5rem !important; }}
[data-testid="stChatInputSubmitButton"]:disabled {{ background: #c9d2d8 !important; }}
[data-testid="stChatInputSubmitButton"] svg {{ fill: #fff !important; color:#fff !important; }}
.af-bottom-note .hint {{ font-weight: 600; color: var(--dt-dark); }}
.af-quota {{ font-size:.78rem; color: var(--dt-muted); text-align:right; }}
.af-bottom-note {{ font-size:.72rem; color: var(--dt-muted); text-align:center; line-height:1.4;
  padding: .1rem .5rem .15rem; }}
.af-bottom-note a {{ color: var(--dt-muted); }}
[data-testid="stBottom"] [data-testid="stVerticalBlock"] {{ gap: .35rem; }}
.st-key-signout {{ display:flex; justify-content:flex-end; }}
.st-key-signout button {{ min-height:0 !important; padding: 0 !important; }}
.st-key-signout button p {{ font-size:.78rem !important; color: var(--dt-orange-text) !important; text-decoration: underline; }}

.af-footer {{ margin-top: 3rem; padding-top: 1.1rem; border-top:1px solid var(--dt-border);
  display:flex; flex-wrap:wrap; justify-content:space-between; gap:.6rem; font-size:.78rem; color: var(--dt-muted); }}
.af-footer a {{ color: var(--dt-muted); }}

@media (max-width: 640px) {{
  .af-brand img {{ height: 34px; }}
  .af-divider, .af-product span {{ display:none; }}
  .af-cta {{ padding:.4rem .7rem; font-size:.78rem; }}
  .af-cta .long {{ display:none; }} .af-cta .short {{ display:inline; }}
  .af-bottom-note {{ font-size:.66rem; }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {{ max-width: 92%; }}
}}
</style>
"""
