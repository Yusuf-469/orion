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

    def _show(self, payload) -> None:
        req, slot = payload
        if slot["done"].is_set():
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

        box.finished.connect(finished)
        slot["box"] = box
        box.open()

    def _close(self, slot) -> None:
        box = slot.get("box")
        slot["answer"] = False
        slot["done"].set()
        if box is not None and box.isVisible():
            box.reject()
