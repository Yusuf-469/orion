"""Synthetic UI generator (research instrument, plan section 5; background track Weeks 4 to 7).

Produces seeded HTML pages from a few layout *families* plus grounding
instructions with ground truth taken from the generator itself (every element
carries data-orion-id). Bounding boxes are added later by rendering the HTML
(Playwright, Stage 4); this module is pure Python and deterministic.

Each randomization factor can be switched off for the synthetic-to-real
leave-one-factor-out experiment; off means a fixed default value.
"""

from __future__ import annotations

import html
import random
from typing import Literal

from pydantic import BaseModel, ConfigDict

FAMILIES = ("toolbar_form", "settings_list", "dialog", "table_actions", "sidebar_nav", "wizard")
ROLES = ("button", "link", "checkbox", "textbox", "tab", "menuitem")

LABELS = {
    "en": ["Save", "Export", "Cancel", "Delete", "Open", "Settings", "Search", "Print", "Share", "Next",
           "Back", "Apply", "Refresh", "Download", "Upload", "Help", "Edit", "Close", "Add", "Filter"],
    "hi": ["सहेजें", "निर्यात", "रद्द करें", "हटाएं", "खोलें", "सेटिंग्स", "खोजें", "प्रिंट", "साझा करें", "आगे",
           "पीछे", "लागू करें", "रीफ़्रेश", "डाउनलोड", "अपलोड", "सहायता", "संपादित करें", "बंद करें", "जोड़ें", "फ़िल्टर"],
    "fr": ["Enregistrer", "Exporter", "Annuler", "Supprimer", "Ouvrir", "Paramètres", "Rechercher", "Imprimer",
           "Partager", "Suivant", "Retour", "Appliquer", "Actualiser", "Télécharger", "Téléverser", "Aide",
           "Modifier", "Fermer", "Ajouter", "Filtrer"],
}
# Icon glyph per English label index (icon-only buttons keep the label only in aria-label).
ICONS = ["💾", "⤴", "✕", "🗑", "📂", "⚙", "🔍", "⎙", "⇪", "→", "←", "✔", "⟳", "⤓", "⤒", "?", "✎", "✖", "➕", "⧩"]
CONTAINERS = {
    "toolbar_form": ["toolbar", "form", "footer"],
    "settings_list": ["header", "settings list", "footer"],
    "dialog": ["dialog body", "dialog buttons"],
    "table_actions": ["toolbar", "table", "row actions"],
    "sidebar_nav": ["sidebar", "main panel", "header"],
    "wizard": ["steps bar", "wizard body", "wizard buttons"],
}
FONTS = ["Segoe UI", "Arial", "Verdana", "Georgia", "Tahoma", "Consolas"]


class Factors(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    layout: bool = True          # random order/columns/spacing vs fixed grid
    theme: bool = True           # light/dark vs light
    font: bool = True            # family and size vs Segoe UI 14px
    scaling: bool = True         # 100/125/150% vs 100%
    label_language: bool = True  # en/hi/fr vs en
    icon_style: bool = True      # some icon-only buttons vs text everywhere


class Element(BaseModel):
    id: str
    role: Literal["button", "link", "checkbox", "textbox", "tab", "menuitem"]
    label: str                   # accessible name (always present)
    visible_text: str            # what is drawn ("" for icon-only); OCR can only find this
    container: str
    disabled: bool = False
    hidden: bool = False


class Instruction(BaseModel):
    text: str
    target_id: str | None        # None = correct answer is to abstain
    flags: list[Literal["duplicate_label", "disabled", "hidden", "missing", "ambiguous", "icon_only",
                        "non_english"]] = []


class Sample(BaseModel):
    sample_id: str
    family: str
    seed: int
    factors: Factors
    theme: Literal["light", "dark"]
    font: str
    font_px: int
    scale: float
    language: Literal["en", "hi", "fr"]
    viewport: tuple[int, int]
    elements: list[Element]
    instructions: list[Instruction]
    html: str


def _pick_style(rng: random.Random, f: Factors):
    theme = rng.choice(["light", "dark"]) if f.theme else "light"
    font = rng.choice(FONTS) if f.font else "Segoe UI"
    font_px = rng.choice([12, 13, 14, 15, 16]) if f.font else 14
    scale = rng.choice([1.0, 1.25, 1.5]) if f.scaling else 1.0
    lang = rng.choice(["en", "en", "hi", "fr"]) if f.label_language else "en"
    return theme, font, font_px, scale, lang


def _elements(rng: random.Random, family: str, lang: str, f: Factors) -> list[Element]:
    containers = CONTAINERS[family]
    n = rng.randint(8, 16)
    idxs = [rng.randrange(len(LABELS["en"])) for _ in range(n)]
    # Force at least one duplicate label in a different container.
    idxs.append(idxs[0])
    out: list[Element] = []
    for k, li in enumerate(idxs):
        role = "button" if k == len(idxs) - 1 else rng.choice(ROLES)
        label = LABELS[lang][li]
        icon_only = f.icon_style and role == "button" and rng.random() < 0.25
        container = containers[k % len(containers)] if not f.layout else rng.choice(containers)
        if k == len(idxs) - 1:
            container = next((c for c in containers if c != out[0].container), containers[-1]) \
                if out else containers[0]
        out.append(Element(id=f"e{k}", role=role, label=label,
                           visible_text="" if icon_only else label, container=container,
                           disabled=rng.random() < 0.12, hidden=rng.random() < 0.08))
    out[0] = out[0].model_copy(update={"hidden": False})
    return out


def _render(s_elements: list[Element], rng: random.Random, family: str, theme: str, font: str, font_px: int,
            scale: float, f: Factors, lang: str) -> str:
    bg, fg, btn = ("#1e1e1e", "#e6e6e6", "#2d2d30") if theme == "dark" else ("#ffffff", "#1b1b1b", "#f0f0f0")
    gap = rng.choice([4, 8, 12, 16]) if f.layout else 8
    cols = rng.choice([1, 2, 3]) if f.layout else 2
    groups: dict[str, list[Element]] = {}
    for e in s_elements:
        groups.setdefault(e.container, []).append(e)
    order = list(groups)
    if f.layout:
        rng.shuffle(order)
    parts = []
    for cname in order:
        items = []
        for e in groups[cname]:
            attrs = (f'data-orion-id="{e.id}" aria-label="{html.escape(e.label, quote=True)}"'
                     + (" disabled" if e.disabled else "") + (' style="display:none"' if e.hidden else ""))
            text = html.escape(e.visible_text) if e.visible_text else ICONS[LABELS[lang].index(e.label)]
            items.append({
                "button": f"<button {attrs}>{text}</button>",
                "link": f'<a href="#" role="link" {attrs}>{text}</a>',
                "checkbox": f'<label {attrs}><input type="checkbox"{" disabled" if e.disabled else ""}> {text}</label>',
                "textbox": f'<label>{text} <input type="text" {attrs}></label>',
                "tab": f'<div role="tab" tabindex="0" {attrs}>{text}</div>',
                "menuitem": f'<div role="menuitem" tabindex="0" {attrs}>{text}</div>',
            }[e.role])
        parts.append(f'<section aria-label="{html.escape(cname)}" class="c"><h2>{html.escape(cname)}</h2>'
                     f'<div class="g">{"".join(items)}</div></section>')
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{family}</title><style>'
        f"html{{zoom:{scale}}}body{{background:{bg};color:{fg};font-family:'{font}';font-size:{font_px}px;"
        f"margin:{gap}px}}.c{{margin-bottom:{gap * 2}px}}.g{{display:grid;grid-template-columns:repeat({cols},max-content);"
        f"gap:{gap}px}}button,[role=tab],[role=menuitem]{{background:{btn};color:{fg};border:1px solid #888;"
        f"padding:{gap // 2 + 2}px {gap}px}}h2{{font-size:{font_px + 2}px}}</style></head>"
        f'<body data-family="{family}">{"".join(parts)}</body></html>'
    )


def _instructions(rng: random.Random, elements: list[Element], lang: str) -> list[Instruction]:
    out: list[Instruction] = []
    by_label: dict[str, list[Element]] = {}
    for e in elements:
        by_label.setdefault(e.label, []).append(e)
    non_en = [] if lang == "en" else ["non_english"]
    for e in rng.sample(elements, k=min(len(elements), rng.randint(4, 7))) + [elements[0], elements[-1]]:
        dupes = [x for x in by_label[e.label] if x.id != e.id]
        flags = list(non_en)
        if e.visible_text == "":
            flags.append("icon_only")
        if e.disabled:
            flags.append("disabled")
        if dupes:
            flags.append("duplicate_label")
        text = f"the {e.label} {e.role} in the {e.container}"
        if e.hidden:
            # Not visible: the correct answer is to abstain.
            out.append(Instruction(text=text, target_id=None, flags=flags + ["hidden"]))
            continue
        twins = [x for x in dupes if x.role == e.role and x.container == e.container and not x.hidden]
        if twins:
            # Same label, role and container: even the full description cannot pick one.
            out.append(Instruction(text=text, target_id=None, flags=flags + ["ambiguous"]))
            continue
        out.append(Instruction(text=text, target_id=e.id, flags=flags))
        if dupes and e.role == "button" and all(d.role == "button" for d in dupes):
            # Same instruction without the container cannot be resolved: abstain is correct.
            out.append(Instruction(text=f"the {e.label} button", target_id=None, flags=flags + ["ambiguous"]))
    present = {e.label for e in elements}
    absent = [lab for lab in LABELS[lang] if lab not in present]
    if absent:
        out.append(Instruction(text=f"the {rng.choice(absent)} button", target_id=None, flags=non_en + ["missing"]))
    # De-duplicate identical instruction texts (keep the first).
    seen, uniq = set(), []
    for i in out:
        if i.text not in seen:
            seen.add(i.text)
            uniq.append(i)
    return uniq


def generate(seed: int, family: str | None = None, factors: Factors = Factors()) -> Sample:
    rng = random.Random(seed)
    family = family or FAMILIES[seed % len(FAMILIES)]
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    theme, font, font_px, scale, lang = _pick_style(rng, factors)
    elements = _elements(rng, family, lang, factors)
    page = _render(elements, rng, family, theme, font, font_px, scale, factors, lang)
    instructions = _instructions(rng, elements, lang)
    return Sample(sample_id=f"{family}-{seed}", family=family, seed=seed, factors=factors, theme=theme, font=font,
                  font_px=font_px, scale=scale, language=lang, viewport=(1280, 800), elements=elements,
                  instructions=instructions, html=page)
