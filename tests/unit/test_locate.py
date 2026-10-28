from orion.grounding.locate import Candidate, collapse_nested, locate, merge, parse_target
from orion.grounding.screen import Box, OcrWord


def ocr(text, x, y, conf=0.95):
    return OcrWord(text, Box(x, y, x + 60, y + 20), conf)


def test_parse_target():
    assert parse_target("the Export button") == ("export", "ButtonControl")
    assert parse_target('click "Close Report"') == ("close report", None)
    assert parse_target("Settings") == ("settings", None)


def test_finds_exact_ocr_text():
    cands = merge([], [ocr("Open", 0, 0), ocr("Export", 100, 0), ocr("Settings", 200, 0)])
    r = locate("the Export button", cands)
    assert r.candidate and r.candidate.text == "Export"


def test_abstains_when_missing():
    cands = merge([], [ocr("Open", 0, 0), ocr("Settings", 200, 0)])
    r = locate("Delete", cands)
    assert r.candidate is None and "no visible element" in r.reason


def test_abstains_when_two_places_match():
    cands = merge([], [ocr("Export", 0, 0), ocr("Export", 300, 200)])
    r = locate("Export", cands)
    assert r.candidate is None and "ambiguous" in r.reason
    assert {c.box.left for c in r.choices} == {0, 300}   # both places are offered to the user


def test_uia_and_ocr_agreement_merges_into_one_candidate():
    uia = [Candidate("Save", Box(0, 0, 80, 30), "uia", "ButtonControl", 1.0, True)]
    cands = merge(uia, [ocr("Save", 10, 5)])
    assert len(cands) == 1 and cands[0].source == "uia+ocr" and cands[0].invokable
    assert locate("Save button", cands).candidate.source == "uia+ocr"


def test_near_miss_text_below_threshold_abstains():
    r = locate("Export", merge([], [ocr("Expert mode", 0, 0)]))
    assert r.candidate is None


def test_nested_same_name_elements_are_one_control():
    """Real apps (Paint 'File', Calculator 'Log') expose one control as a menu item + button + text label."""
    uia = [Candidate("File", Box(200, 140, 244, 174), "uia", "MenuItemControl"),
           Candidate("File", Box(200, 140, 244, 174), "uia", "ButtonControl", invokable=True),
           Candidate("File", Box(210, 149, 234, 168), "uia", "TextControl"),
           Candidate("Edit", Box(250, 140, 296, 174), "uia", "ButtonControl")]
    out = collapse_nested(merge(uia, [ocr("File", 205, 150)]))
    files = [c for c in out if c.text == "File"]
    assert len(files) == 1 and files[0].invokable and files[0].role in ("MenuItemControl", "ButtonControl")
    assert files[0].box == Box(200, 140, 244, 174) and "ocr" in files[0].source
    assert locate("File", out).candidate is not None   # no longer "ambiguous"


def test_real_duplicates_in_different_places_stay_separate():
    two = [Candidate("Empty", Box(0, 0, 20, 20), "uia", "ButtonControl"),
           Candidate("Empty", Box(40, 0, 60, 20), "uia", "ButtonControl")]
    assert len(collapse_nested(two)) == 2 and locate("Empty", collapse_nested(two)).candidate is None
