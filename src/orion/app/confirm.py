"""Confirmation dialog for the policy engine, callable from worker threads.

The worker thread blocks until the user answers. If the kill switch fires
while the dialog is open, the dialog is closed and the answer is "no".
"""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from orion.orchestration.cancel import CancelToken
from orion.policy.engine import ConfirmationRequest


class QtConfirmer(QObject):
    _ask = Signal(object)
    _dismiss = Signal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        self._ask.connect(self._show, Qt.QueuedConnection)
        self._dismiss.connect(self._close, Qt.QueuedConnection)

    def confirm(self, request: ConfirmationRequest, token: CancelToken) -> bool:
        slot: dict[str, Any] = {"done": threading.Event(), "answer": False, "box": None}
        self._ask.emit((request, slot))
        while not slot["done"].wait(0.05):
            if token.is_cancelled:
                self._dismiss.emit(slot)
                return False
        return bool(slot["answer"]) and not token.is_cancelled

    def choose(self, request: ConfirmationRequest, options: list[str], token: CancelToken) -> int | None:
        slot: dict[str, Any] = {"done": threading.Event(), "answer": None, "box": None, "options": options}
        self._ask.emit((request, slot))
        while not slot["done"].wait(0.05):
            if token.is_cancelled:
                self._dismiss.emit(slot)
                return None
        return None if token.is_cancelled else slot["answer"]

    def _show(self, payload) -> None:
        req, slot = payload
        if slot["done"].is_set():
            return
        if "options" in slot:
            self._show_choice(req, slot)
            return
        box = QMessageBox(self._parent)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("ORION needs your confirmation")
        box.setText(req.action)
        box.setInformativeText(
            f"Consequence: {req.consequence}\n\n"
            f"Tool: {req.tool_id}  ({req.side_effect})\n"
            f"This approval covers this one action only."
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setObjectName("orion_confirm")

        def finished(_code: int) -> None:
            clicked = box.clickedButton()
            slot["answer"] = clicked is not None and box.standardButton(clicked) == QMessageBox.Yes
            slot["done"].set()
            # One dialog per request: drop the name at once and free it, so no stale hidden dialog lingers.
            box.setObjectName("orion_confirm_answered")
            box.deleteLater()

        box.finished.connect(finished)
        slot["box"] = box
        box.open()

    def _show_choice(self, req: ConfirmationRequest, slot: dict[str, Any]) -> None:
        box = QMessageBox(self._parent)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("ORION: which one did you mean?")
        box.setText(req.action)
        box.setInformativeText(f"{req.consequence}\n\nThis answer covers this one action only.")
        buttons = [box.addButton(o, QMessageBox.AcceptRole) for o in slot["options"]]
        none = box.addButton("Neither, don't click", QMessageBox.RejectRole)
        box.setDefaultButton(none)
        box.setEscapeButton(none)
        box.setObjectName("orion_choose")

        def finished(_code: int) -> None:
            clicked = box.clickedButton()
            slot["answer"] = buttons.index(clicked) if clicked in buttons else None
            slot["done"].set()
            box.setObjectName("orion_choose_answered")
            box.deleteLater()

        box.finished.connect(finished)
        slot["box"] = box
        box.open()

    def _close(self, slot) -> None:
        box = slot.get("box")
        slot["answer"] = None if "options" in slot else False
        slot["done"].set()
        if box is not None and box.isVisible():
            box.reject()
