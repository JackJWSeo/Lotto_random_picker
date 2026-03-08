import math
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
import matplotlib.font_manager as fm

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import TOTAL_COMBINATIONS
from database import get_connection, WIN_EXCLUDED_TABLE

def setup_matplotlib_korean_font():
    """
    matplotlib에서 한글이 깨지지 않도록 폰트를 설정한다.
    Windows에서는 보통 'Malgun Gothic'이 가장 안정적이다.
    """
    preferred_fonts = [
        "Malgun Gothic",      # Windows
        "AppleGothic",        # macOS
        "NanumGothic",        # Linux/설치 환경
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]

    available_fonts = {f.name for f in fm.fontManager.ttflist}

    selected_font = None
    for font_name in preferred_fonts:
        if font_name in available_fonts:
            selected_font = font_name
            break

    if selected_font is not None:
        matplotlib.rcParams["font.family"] = selected_font

    # 마이너스 기호 깨짐 방지
    matplotlib.rcParams["axes.unicode_minus"] = False

def load_excluded_index_rows():
    """
    winning_excluded_combinations 에 저장된 전체 제외 인덱스 목록을 읽는다.

    return 예:
    [
        (1214, 123456, 'main'),
        (1214, 234567, 'bonus_replace_1'),
        ...
    ]
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT draw_no, comb_idx, comb_type
        FROM {WIN_EXCLUDED_TABLE}
        ORDER BY draw_no ASC, comb_idx ASC
    """)

    rows = cursor.fetchall()
    conn.close()
    return rows


def build_heatmap_array(total_count, excluded_rows):
    """
    전체 인덱스를 정사각형에 가깝게 펼쳐서 2D 배열로 만든다.

    값 의미:
    0.0 = 데이터 없음(배경)
    0.15 = 전체 조합 영역
    0.75 = bonus_replace 계열
    1.00 = main 당첨 조합
    """
    width = math.ceil(math.sqrt(total_count))
    height = math.ceil(total_count / width)

    # 전체 조합 범위를 옅은 값으로 채움
    data = np.zeros((height, width), dtype=np.float32)

    # 실제 존재하는 인덱스 영역만 기본값 부여
    valid_count = total_count
    flat = data.ravel()
    flat[:valid_count] = 0.15

    # 제외 인덱스 강조
    for _draw_no, comb_idx, comb_type in excluded_rows:
        idx0 = comb_idx - 1
        if idx0 < 0 or idx0 >= total_count:
            continue

        row = idx0 // width
        col = idx0 % width

        if comb_type == "main":
            data[row, col] = 1.0
        else:
            # bonus_replace 계열
            # main 보다 약간 낮게 표시
            if data[row, col] < 1.0:
                data[row, col] = max(data[row, col], 0.75)

    return data, width, height


def build_density_array(total_count, excluded_rows, block_size=20):
    """
    큰 영역에서 군집이 보이도록 블록 단위 밀도 맵을 만든다.
    block_size x block_size 셀 단위로 묶어서 합산한다.

    main = 2점
    bonus_replace = 1점
    """
    width = math.ceil(math.sqrt(total_count))
    height = math.ceil(total_count / width)

    block_w = math.ceil(width / block_size)
    block_h = math.ceil(height / block_size)

    density = np.zeros((block_h, block_w), dtype=np.float32)

    for _draw_no, comb_idx, comb_type in excluded_rows:
        idx0 = comb_idx - 1
        if idx0 < 0 or idx0 >= total_count:
            continue

        row = idx0 // width
        col = idx0 % width

        br = row // block_size
        bc = col // block_size

        if comb_type == "main":
            density[br, bc] += 2.0
        else:
            density[br, bc] += 1.0

    return density


class CombinationHeatmapWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        
        setup_matplotlib_korean_font()

        self.title("조합 인덱스 히트맵")
        self.geometry("1280x860")

        self.excluded_rows = []
        self.status_var = tk.StringVar(value="불러오는 중...")
        self.mode_var = tk.StringVar(value="density")

        self._create_ui()
        self._load_and_draw()

    def _create_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="전체 조합 인덱스 대비 당첨/보너스 제외 조합 분포",
            font=("맑은 고딕", 12, "bold")
        ).pack(side="left", padx=(0, 12))

        ttk.Radiobutton(
            top,
            text="밀도 히트맵",
            value="density",
            variable=self.mode_var,
            command=self.redraw
        ).pack(side="left", padx=4)

        ttk.Radiobutton(
            top,
            text="개별 인덱스 맵",
            value="raw",
            variable=self.mode_var,
            command=self.redraw
        ).pack(side="left", padx=4)

        ttk.Button(
            top,
            text="새로고침",
            command=self._load_and_draw
        ).pack(side="right", padx=4)

        info = ttk.Frame(self, padding=(10, 0, 10, 6))
        info.pack(fill="x")

        self.summary_label = ttk.Label(
            info,
            text="요약 정보 준비 중...",
            font=("맑은 고딕", 10)
        )
        self.summary_label.pack(anchor="w")

        self.status_label = ttk.Label(
            info,
            textvariable=self.status_var,
            font=("맑은 고딕", 9)
        )
        self.status_label.pack(anchor="w", pady=(4, 0))

        plot_frame = ttk.Frame(self, padding=10)
        plot_frame.pack(fill="both", expand=True)

        self.figure = Figure(figsize=(12, 8), dpi=100)
        self.ax_main = self.figure.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        legend_text = (
            "범례  |  배경: 전체 조합 영역  |  노랑/주황: 보너스 포함 제외 조합  |  빨강: 실제 당첨 조합"
        )
        ttk.Label(bottom, text=legend_text, font=("맑은 고딕", 9)).pack(anchor="w")

    def _load_and_draw(self):
        try:
            self.status_var.set("DB에서 제외 인덱스 정보를 읽는 중...")
            self.update_idletasks()

            self.excluded_rows = load_excluded_index_rows()

            main_count = sum(1 for _, _, t in self.excluded_rows if t == "main")
            bonus_count = len(self.excluded_rows) - main_count
            total_excluded = len({idx for _, idx, _ in self.excluded_rows})

            self.summary_label.config(
                text=(
                    f"전체 조합: {TOTAL_COMBINATIONS:,}개    "
                    f"실제 당첨 조합(main): {main_count:,}개    "
                    f"보너스 포함 제외 조합: {bonus_count:,}개    "
                    f"중복 제거 후 제외 인덱스: {total_excluded:,}개"
                )
            )

            self.status_var.set("시각화 생성 중...")
            self.redraw()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"히트맵 데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def redraw(self):
        try:
            self.ax_main.clear()

            mode = self.mode_var.get()

            if mode == "density":
                density = build_density_array(
                    TOTAL_COMBINATIONS,
                    self.excluded_rows,
                    block_size=20
                )

                im = self.ax_main.imshow(
                    density,
                    cmap="hot",
                    interpolation="nearest",
                    aspect="auto",
                    origin="upper"
                )
                self.ax_main.set_title("조합 인덱스 밀도 히트맵", fontsize=12)
                self.ax_main.set_xlabel("인덱스 영역 X")
                self.ax_main.set_ylabel("인덱스 영역 Y")

                # 이전 colorbar 제거를 위해 figure 전체 axes 수 고려
                if len(self.figure.axes) > 1:
                    for extra_ax in self.figure.axes[1:]:
                        self.figure.delaxes(extra_ax)

                self.figure.colorbar(im, ax=self.ax_main, fraction=0.03, pad=0.02)

            else:
                raw_map, width, height = build_heatmap_array(
                    TOTAL_COMBINATIONS,
                    self.excluded_rows
                )

                im = self.ax_main.imshow(
                    raw_map,
                    cmap="hot",
                    interpolation="nearest",
                    aspect="auto",
                    origin="upper",
                    vmin=0.0,
                    vmax=1.0
                )
                self.ax_main.set_title(
                    f"개별 인덱스 맵 ({width:,} x {height:,})",
                    fontsize=12
                )
                self.ax_main.set_xlabel("인덱스 펼침 X")
                self.ax_main.set_ylabel("인덱스 펼침 Y")

                if len(self.figure.axes) > 1:
                    for extra_ax in self.figure.axes[1:]:
                        self.figure.delaxes(extra_ax)

                self.figure.colorbar(im, ax=self.ax_main, fraction=0.03, pad=0.02)

            self.figure.tight_layout()
            self.canvas.draw()

        except Exception as e:
            messagebox.showerror("오류", f"히트맵을 그리는 중 오류가 발생했습니다.\n{e}")