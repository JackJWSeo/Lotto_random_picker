import tkinter as tk
from tkinter import ttk


class ProgressPopup(tk.Toplevel):
    def __init__(self, master, title="진행 중"):
        super().__init__(master)
        self.title(title)
        self.geometry("420x130")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.label_var = tk.StringVar(value="준비 중...")
        self.label = ttk.Label(self, textvariable=self.label_var, anchor="center")
        self.label.pack(padx=20, pady=(20, 10), fill="x")

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(padx=20, fill="x")
        self.progress.start(10)

    def set_message(self, text):
        self.label_var.set(text)
        self.update_idletasks()