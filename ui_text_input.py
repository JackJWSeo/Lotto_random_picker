import tkinter as tk
from tkinter import ttk, messagebox


class WinningTextInputWindow(tk.Toplevel):
    def __init__(self, master, on_import_callback):
        super().__init__(master)
        self.title("역대 당첨번호 붙여넣기")
        self.geometry("900x600")
        self.on_import_callback = on_import_callback

        top_label = ttk.Label(
            self,
            text="아래에 역대 당첨번호 표 텍스트를 붙여넣고 가져오기를 누르세요.",
            font=("맑은 고딕", 10)
        )
        top_label.pack(padx=10, pady=(10, 6), anchor="w")

        self.text = tk.Text(self, wrap="none", font=("Consolas", 11))
        self.text.pack(fill="both", expand=True, padx=10, pady=10)

        sample = (
            "회차\t당첨번호\t\t\t\t\t\t보너스\t당첨게임수\t1게임당 당첨금액\n"
            "1,214\t10\t15\t19\t27\t30\t33\t14\t12 명\t2,431,577,188 원\n"
            "1,213\t5\t11\t25\t27\t36\t38\t2\t18 명\t1,740,011,646 원\n"
        )
        self.text.insert("1.0", sample)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(btn_frame, text="가져오기", command=self.import_text).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="닫기", command=self.destroy).pack(side="right", padx=4)

    def import_text(self):
        raw_text = self.text.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("경고", "붙여넣은 텍스트가 없습니다.")
            return

        self.on_import_callback(raw_text)
        self.destroy()