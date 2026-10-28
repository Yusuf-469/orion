"""ORION demo app whose buttons are DRAWN on a canvas, so Windows UI Automation cannot see them.

Only what is visible on screen identifies a button; this is what visual grounding is for.
Every click is appended to the log file given on the command line, so ORION can verify the result.

usage: python canvas_buttons.py CLICK_LOG [POSITION] [LAYOUT]
LAYOUT "duplicate" relabels Help as a second Export; the log then says which one ("Export #2").
"""

import sys
import tkinter as tk
from datetime import datetime

BUTTONS = [("Open", 30, 30), ("Export", 190, 30), ("Settings", 350, 30),
           ("Refresh", 30, 120), ("Help", 190, 120), ("Close Report", 350, 120)]
W, H = 140, 56


def main() -> None:
    log = sys.argv[1] if len(sys.argv) > 1 else "canvas_clicks.log"
    pos = sys.argv[2] if len(sys.argv) > 2 else "+200+200"   # e.g. "+-1700+200" for a left-hand monitor
    buttons = BUTTONS
    if len(sys.argv) > 3 and sys.argv[3] == "duplicate":
        buttons = [("Export" if b[0] == "Help" else b[0], *b[1:]) for b in BUTTONS]
    labels = [b[0] for b in buttons]
    root = tk.Tk()
    root.title("ORION Canvas Demo")
    root.geometry(f"540x260{pos}")
    root.resizable(False, False)
    c = tk.Canvas(root, width=540, height=260, bg="#f7f7f7", highlightthickness=0)
    c.pack()
    c.create_text(270, 228, text="Buttons here are drawn, not real controls", fill="#888", font=("Segoe UI", 10))
    status = c.create_text(270, 205, text="", fill="#2e7d32", font=("Segoe UI", 10, "bold"))
    areas = []
    for k, (label, x, y) in enumerate(buttons):
        c.create_rectangle(x, y, x + W, y + H, fill="#2d6cdf", outline="#1b4fa8", width=2)
        c.create_text(x + W / 2, y + H / 2, text=label, fill="white", font=("Segoe UI", 13, "bold"))
        n = labels[:k + 1].count(label)
        areas.append((label if labels.count(label) == 1 else f"{label} #{n}", x, y))

    def on_click(e):
        for label, x, y in areas:
            if x <= e.x <= x + W and y <= e.y <= y + H:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().isoformat(timespec='seconds')} clicked {label}\n")
                c.itemconfigure(status, text=f"Clicked: {label}")
                return

    c.bind("<Button-1>", on_click)
    root.mainloop()


if __name__ == "__main__":
    main()
