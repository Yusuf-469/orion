"""Merging detector boxes and OCR words into screen elements (pure logic, no screen)."""

from orion.grounding.screen import Box, OcrWord
from orion.grounding.vision import elements, where


def w(text, l, t, r, b, conf=0.9):
    return OcrWord(text, Box(l, t, r, b), conf)


def test_text_inside_a_detected_box_labels_it_and_icons_stay_unlabeled():
    words = [w("Export", 210, 40, 260, 60), w("Buttons here are drawn", 150, 220, 390, 236)]
    det = [(Box(190, 30, 330, 86), 0.8), (Box(20, 20, 50, 50), 0.6)]
    got = elements(words, det, known=[])
    assert [(s.role, s.name) for s in got] == [("icon", ""), ("control", "Export"), ("text", "Buttons here are drawn")]


def test_things_ui_automation_already_lists_are_dropped():
    words = [w("Save", 110, 12, 150, 28), w("Hello", 300, 300, 350, 320)]
    det = [(Box(100, 10, 160, 30), 0.9)]
    got = elements(words, det, known=[Box(98, 8, 162, 32)])
    assert [s.name for s in got] == ["Hello"]


def test_multi_word_label_reads_left_to_right():
    words = [w("Report", 400, 140, 450, 156), w("Close", 360, 140, 395, 156)]
    got = elements(words, [(Box(350, 120, 490, 176), 0.7)], known=[])
    assert got[0].name == "Close Report"


def test_where_names_the_area_of_the_window():
    win = Box(0, 0, 900, 600)
    assert where(Box(10, 10, 40, 40), win) == "top left"
    assert where(Box(440, 290, 460, 310), win) == "centre"
    assert where(Box(850, 560, 890, 590), win) == "bottom right"
