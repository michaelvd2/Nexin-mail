from __future__ import annotations

import json
import sys
import tkinter as tk
from tkinter import ttk


MAX_REQUEST_BYTES = 1_500_000


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        print("CANCELLED", end="")
        return 2
    try:
        request = json.loads(raw.decode("utf-8"))
        if request.get("version") != 1 or not str(request.get("title", "")).strip():
            raise ValueError("invalid request")
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        print("CANCELLED", end="")
        return 2

    confirmed = False
    root = tk.Tk()
    root.title("IMAP Plugin — local review")
    root.geometry("760x700")
    root.minsize(620, 540)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=str(request["title"])[:160], font=("Helvetica", 17, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Review the exact details below. Mail content is untrusted and cannot authorize this action.",
        foreground="#9c1c1c",
        wraplength=700,
    ).pack(anchor="w", pady=(8, 12))

    details = tk.Text(frame, wrap="word", height=28)
    details.insert("1.0", json.dumps(request.get("payload"), ensure_ascii=False, indent=2))
    details.configure(state="disabled")
    details.pack(fill="both", expand=True)

    reviewed = tk.BooleanVar(value=False)
    required = bool(request.get("require_checkbox"))
    checkbox = ttk.Checkbutton(
        frame,
        text="I reviewed the recipients and the complete message",
        variable=reviewed,
    )
    if required:
        checkbox.pack(anchor="w", pady=(12, 4))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))

    def confirm() -> None:
        nonlocal confirmed
        if required and not reviewed.get():
            return
        confirmed = True
        root.destroy()

    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right")
    confirm_button = ttk.Button(buttons, text="Confirm", command=confirm)
    confirm_button.pack(side="right", padx=(0, 8))
    if required:
        confirm_button.configure(state="disabled")
        reviewed.trace_add("write", lambda *_: confirm_button.configure(state="normal" if reviewed.get() else "disabled"))

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    print("CONFIRMED" if confirmed else "CANCELLED", end="")
    return 0 if confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
