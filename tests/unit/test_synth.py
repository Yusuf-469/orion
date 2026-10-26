"""Synthetic UI generator: determinism, factor switches, ground-truth consistency."""

import re

import pytest

from orion.grounding.synth import FAMILIES, LABELS, Factors, generate

SEEDS = range(60)


def test_deterministic_per_seed():
    assert generate(7).model_dump() == generate(7).model_dump()
    assert generate(7).html != generate(8).html


def test_all_factors_off_gives_fixed_defaults():
    off = Factors(layout=False, theme=False, font=False, scaling=False, label_language=False, icon_style=False)
    for seed in SEEDS:
        s = generate(seed, factors=off)
        assert (s.theme, s.font, s.font_px, s.scale, s.language) == ("light", "Segoe UI", 14, 1.0, "en")
        assert all(e.visible_text == e.label for e in s.elements)


@pytest.mark.parametrize("factor,attr,values", [
    ("theme", "theme", {"light", "dark"}),
    ("scaling", "scale", {1.0, 1.25, 1.5}),
    ("label_language", "language", {"en", "hi", "fr"}),
])
def test_each_factor_varies_only_when_on(factor, attr, values):
    on = {getattr(generate(s), attr) for s in SEEDS}
    off = {getattr(generate(s, factors=Factors(**{factor: False})), attr) for s in SEEDS}
    assert on == values and len(off) == 1


def test_every_element_is_in_the_html_once():
    for seed in SEEDS:
        s = generate(seed)
        for e in s.elements:
            assert len(re.findall(rf'data-orion-id="{e.id}"', s.html)) == 1


def test_instruction_targets_are_visible_elements():
    for seed in SEEDS:
        s = generate(seed)
        by_id = {e.id: e for e in s.elements}
        for i in s.instructions:
            if i.target_id is None:
                continue
            e = by_id[i.target_id]
            assert not e.hidden and e.label in i.text and e.container in i.text


def test_targeted_instructions_are_unambiguous():
    """No other visible element may share label, role and container with a target."""
    for seed in range(300):
        s = generate(seed)
        by_id = {e.id: e for e in s.elements}
        for i in s.instructions:
            if i.target_id is None:
                continue
            t = by_id[i.target_id]
            twins = [e for e in s.elements if e.id != t.id and not e.hidden
                     and (e.label, e.role, e.container) == (t.label, t.role, t.container)]
            assert not twins, (seed, i.text)


def test_abstain_cases_are_well_formed():
    seen = set()
    for seed in SEEDS:
        s = generate(seed)
        labels_on_page = {e.label for e in s.elements}
        for i in s.instructions:
            if "missing" in i.flags:
                named = re.fullmatch(r"the (.+) button", i.text).group(1)
                assert i.target_id is None and named not in labels_on_page
            if "hidden" in i.flags or "ambiguous" in i.flags:
                assert i.target_id is None
            seen.update(i.flags)
    assert {"missing", "duplicate_label", "disabled", "hidden", "ambiguous", "icon_only", "non_english"} <= seen


def test_families_cover_all_and_are_recorded():
    fams = {generate(s).family for s in SEEDS}
    assert fams == set(FAMILIES)
    s = generate(3)
    assert f'data-family="{s.family}"' in s.html


def test_labels_are_html_escaped_and_languages_aligned():
    assert all(len(v) == len(LABELS["en"]) for v in LABELS.values())
    s = generate(0)
    assert "<script" not in s.html
