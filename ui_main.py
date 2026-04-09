import os
import queue
import threading
import tkinter as tk
import sys
import base64
import subprocess
import pyperclip
from Lotto_base64 import Lotto_base64
from tkinter import ttk, messagebox, filedialog
from ui_heatmap import CombinationHeatmapWindow

from config import APP_TITLE, APP_GEOMETRY, DB_PATH
from database import create_tables, get_all_winning_rows
from lotto_generator import (
    get_random_lotto_number_sets,
    get_density_weighted_random_lotto_number_sets,
    index_to_combination,
)
from winning_service import import_winning_data_from_text
from ui_popup import ProgressPopup
from ui_text_input import WinningTextInputWindow
from ui_3d_cube import Combination3DCubeWindow
from hex_spiral_heatmap_window import HexSpiralHeatmapWindow
from circle_packing_heatmap_window import CircularRingHeatmapWindow
from sphere_lotto_opengl import LottoSphereOpenGLWindow
from ui_3d_cube_pg import Combination3DCubePGWindow

# ------------------------------------------------------------
# 아이콘 로드
# ------------------------------------------------------------
def load_embedded_icon():
    icon_data = base64.b64decode(Lotto_base64)
    return tk.PhotoImage(data=icon_data)

class LottoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(APP_GEOMETRY)
        self.resizable(False, False)

        self.sphere_window = None
        self.cube_pg_window = None

        try:
            self.iconphoto(True, load_embedded_icon())
        except Exception:
            pass

        self.msg_queue = queue.Queue()
        self.result_vars = []

        self.create_menu()
        self.create_main_ui()

        self.after(100, self.process_queue)
        self.after(200, self.check_db_on_start)

    def create_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="종료", command=self.destroy)
        menubar.add_cascade(label="파일", menu=file_menu)

        win_menu = tk.Menu(menubar, tearoff=0)
        win_menu.add_command(label="텍스트로 당첨번호 붙여넣기", command=self.open_winning_text_input)
        win_menu.add_command(label="txt 파일에서 당첨번호 불러오기", command=self.import_winning_from_file)
        win_menu.add_separator()
        win_menu.add_command(label="역대 당첨번호 보기", command=self.show_winning_numbers_window)
        win_menu.add_separator()
        win_menu.add_command(label="조합 인덱스 히트맵 보기", command=self.open_heatmap_window)
        win_menu.add_separator()
        win_menu.add_command(label="육각 히트맵 보기", command=self.open_hex_spiral_heatmap)
        win_menu.add_separator()
        win_menu.add_command(label="원형 히트맵 보기", command=self.open_circle_heatmap)
        # win_menu.add_separator()
        # win_menu.add_command(label="3D 조합 큐브 보기", command=self.open_3d_cube_window)
        win_menu.add_separator()
        win_menu.add_command(label="GPU 3D 큐브 보기", command=self.open_3d_cube_pg_window)
        win_menu.add_separator()
        win_menu.add_command(label="GPU 3D 스피어 보기", command=self.open_3d_sphere_pg_window)
        menubar.add_cascade(label="당첨번호", menu=win_menu)
        

        self.config(menu=menubar)

    def create_main_ui(self):
        outer = ttk.Frame(self, padding=20)

        outer.pack(fill="both", expand=True)

        title = ttk.Label(
            outer,
            text="로또 6/45 번호 생성기",
            font=("맑은 고딕", 18, "bold")
        )
        title.pack(pady=(10, 12))

        desc = ttk.Label(
            outer,
            text="제외된 역대 당첨 조합을 피해서 로또 번호 5세트를 생성합니다.",
            font=("맑은 고딕", 10)
        )
        desc.pack(pady=(0, 16))

        result_title = ttk.Label(
            outer,
            text="생성된 번호 5세트",
            font=("맑은 고딕", 11, "bold")
        )
        result_title.pack(pady=(6, 8))

        result_frame = ttk.Frame(outer, relief="solid", borderwidth=1, padding=12)
        result_frame.pack(pady=(4, 16), fill="x", padx=30)

        for i in range(5):
            var = tk.StringVar(value=f"{i+1}세트  :  --   --   --   --   --   --")
            self.result_vars.append(var)

            lbl = ttk.Label(
                result_frame,
                textvariable=var,
                font=("Consolas", 16, "bold"),
                anchor="center"
            )
            lbl.pack(fill="x", pady=6)

        btn_frame = ttk.Frame(outer)
        btn_frame.pack(pady=(0, 12))

        self.generate_btn = ttk.Button(
            btn_frame,
            text="기본 랜덤 5세트",
            command=self.generate_numbers
        )
        self.generate_btn.pack(side="left", ipadx=12, ipady=10, padx=4)

        self.generate_low_density_btn = ttk.Button(
            btn_frame,
            text="저밀도 우선 5세트",
            command=self.generate_numbers_low_density
        )
        self.generate_low_density_btn.pack(side="left", ipadx=12, ipady=10, padx=4)

        self.generate_high_density_btn = ttk.Button(
            btn_frame,
            text="고밀도 우선 5세트",
            command=self.generate_numbers_high_density
        )
        self.generate_high_density_btn.pack(side="left", ipadx=12, ipady=10, padx=4)

        self.status_var = tk.StringVar(value="상태: 준비 중")
        status = ttk.Label(
            outer,
            textvariable=self.status_var,
            font=("맑은 고딕", 10)
        )
        status.pack(side="bottom", pady=(10, 0))

    def process_queue(self):
        try:
            while True:
                msg_type, payload = self.msg_queue.get_nowait()

                if msg_type == "progress":
                    popup, text = payload
                    if popup.winfo_exists():
                        popup.set_message(text)

                elif msg_type == "done":
                    popup, text, callback = payload
                    if popup.winfo_exists():
                        popup.destroy()
                    if callback:
                        callback(text)

        except queue.Empty:
            pass

        self.after(100, self.process_queue)

    def check_db_on_start(self):
        try:
            create_tables()

            if not os.path.exists(DB_PATH):
                self.status_var.set("상태: DB 파일 생성 준비 완료")
            else:
                self.status_var.set("상태: 준비 완료")

            self.generate_btn.config(state="normal")
            self.generate_low_density_btn.config(state="normal")
            self.generate_high_density_btn.config(state="normal")

        except Exception as e:
            self.generate_btn.config(state="disabled")
            self.generate_low_density_btn.config(state="disabled")
            self.generate_high_density_btn.config(state="disabled")
            messagebox.showerror("오류", f"초기화 중 오류가 발생했습니다.\n{e}")

    def generate_numbers(self):
        try:
            number_sets = get_random_lotto_number_sets(5)
            clip = ""
            clip_total = ""

            for i, nums in enumerate(number_sets, start=1):
                clip = ", ".join(str(n) for n in nums)
                self.result_vars[i - 1].set(clip)
                clip_total += clip if len(clip_total) == 0 else f"\n{clip}"

            self.status_var.set("상태: 번호 5세트 생성 완료")
            pyperclip.copy(clip_total)

        except Exception as e:
            messagebox.showerror("오류", f"번호 생성 중 오류가 발생했습니다.\n{e}")

    def generate_numbers_low_density(self):
        try:
            number_sets = get_density_weighted_random_lotto_number_sets(
                set_count=5,
                density_mode="low",
                block_size=40,
                candidate_pool_size=2000,
            )

            clip = ""
            clip_total = ""

            for i, nums in enumerate(number_sets, start=1):
                clip = ", ".join(str(n) for n in nums)
                self.result_vars[i - 1].set(clip)
                clip_total += clip if len(clip_total) == 0 else f"\n{clip}"

            self.status_var.set("상태: 저밀도 우선 번호 5세트 생성 완료")
            pyperclip.copy(clip_total)

        except Exception as e:
            messagebox.showerror("오류", f"저밀도 우선 번호 생성 중 오류가 발생했습니다.\n{e}")


    def generate_numbers_high_density(self):
        try:
            number_sets = get_density_weighted_random_lotto_number_sets(
                set_count=5,
                density_mode="high",
                block_size=40,
                candidate_pool_size=2000,
            )

            clip = ""
            clip_total = ""

            for i, nums in enumerate(number_sets, start=1):
                clip = ", ".join(str(n) for n in nums)
                self.result_vars[i - 1].set(clip)
                clip_total += clip if len(clip_total) == 0 else f"\n{clip}"

            self.status_var.set("상태: 고밀도 우선 번호 5세트 생성 완료")
            pyperclip.copy(clip_total)

        except Exception as e:
            messagebox.showerror("오류", f"고밀도 우선 번호 생성 중 오류가 발생했습니다.\n{e}")
            
    def open_winning_text_input(self):
        WinningTextInputWindow(self, self.import_winning_from_text)

    def import_winning_from_text(self, raw_text):
        popup = ProgressPopup(self, "당첨번호 가져오기")

        def worker():
            try:
                import_winning_data_from_text(
                    raw_text,
                    progress_callback=lambda text: self.msg_queue.put(("progress", (popup, text)))
                )
                self.msg_queue.put(("done", (popup, "당첨번호 저장 완료", self.on_winning_import_done)))
            except Exception as e:
                self.msg_queue.put(("done", (popup, f"당첨번호 저장 실패: {e}", self.on_winning_import_failed)))

        threading.Thread(target=worker, daemon=True).start()

    def import_winning_from_file(self):
        file_path = filedialog.askopenfilename(
            title="당첨번호 txt 파일 선택",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            self.import_winning_from_text(raw_text)
        except Exception as e:
            messagebox.showerror("오류", f"파일 읽기 실패:\n{e}")

    def on_winning_import_done(self, text):
        self.status_var.set("상태: 당첨번호 저장 완료")
        messagebox.showinfo("완료", text)

    def on_winning_import_failed(self, text):
        self.status_var.set("상태: 당첨번호 저장 실패")
        messagebox.showerror("실패", text)

    def open_heatmap_window(self):
        CombinationHeatmapWindow(self)

    def open_3d_cube_window(self):
        Combination3DCubeWindow(self)

    def open_3d_cube_pg_window(self):
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable, "--cube"])
            else:
                main_script = os.path.join(os.path.dirname(__file__), "main.py")
                subprocess.Popen([sys.executable, main_script, "--cube"])
        except Exception as e:
            messagebox.showerror("오류", f"GPU 3D 큐브 창을 여는 중 오류가 발생했습니다.\n{e}")

    def open_3d_sphere_pg_window(self):
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable, "--sphere"])
            else:
                main_script = os.path.join(os.path.dirname(__file__), "main.py")
                subprocess.Popen([sys.executable, main_script, "--sphere"])
        except Exception as e:
            messagebox.showerror("오류", f"GPU 3D 스피어 창을 여는 중 오류가 발생했습니다.\n{e}")
    
    def open_hex_spiral_heatmap(self):
        HexSpiralHeatmapWindow(self)
    
    def open_circle_heatmap(self):
        CircularRingHeatmapWindow(self)

    def show_winning_numbers_window(self):
        try:
            rows = get_all_winning_rows()

            win = tk.Toplevel(self)
            win.title("역대 당첨번호")
            win.geometry("1150x550")

            frame = ttk.Frame(win, padding=10)
            frame.pack(fill="both", expand=True)

            columns = (
                "draw_no", "draw_date", "comb_idx",
                "numbers", "bonus", "winner_count", "prize_amount"
            )

            tree = ttk.Treeview(frame, columns=columns, show="headings")

            tree.heading("draw_no", text="회차")
            tree.heading("draw_date", text="추첨일")
            tree.heading("comb_idx", text="조합 IDX")
            tree.heading("numbers", text="당첨번호")
            tree.heading("bonus", text="보너스")
            tree.heading("winner_count", text="당첨게임수")
            tree.heading("prize_amount", text="1게임당 당첨금액")

            tree.column("draw_no", width=80, anchor="center")
            tree.column("draw_date", width=100, anchor="center")
            tree.column("comb_idx", width=110, anchor="center")
            tree.column("numbers", width=380, anchor="center")
            tree.column("bonus", width=80, anchor="center")
            tree.column("winner_count", width=100, anchor="center")
            tree.column("prize_amount", width=170, anchor="e")

            yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=yscroll.set)

            tree.pack(side="left", fill="both", expand=True)
            yscroll.pack(side="right", fill="y")

            for row in rows:
                draw_no, draw_date, comb_idx, bonus, winner_count, prize_amount = row
                nums = index_to_combination(comb_idx)
                num_text = "  ".join(f"{n:02d}" for n in nums)

                winner_text = f"{winner_count} 명" if winner_count is not None else ""
                prize_text = f"{prize_amount:,} 원" if prize_amount is not None else ""

                tree.insert("", "end", values=(
                    f"{draw_no:,}",
                    draw_date if draw_date else "",
                    comb_idx,
                    num_text,
                    f"{bonus:02d}",
                    winner_text,
                    prize_text
                ))

            if not rows:
                messagebox.showinfo("안내", "저장된 역대 당첨번호가 없습니다.")

        except Exception as e:
            messagebox.showerror("오류", f"역대 당첨번호 창을 여는 중 오류가 발생했습니다.\n{e}")
