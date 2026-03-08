import math
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import matplotlib
import matplotlib.font_manager as fm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from config import TOTAL_COMBINATIONS
from database import get_connection, WIN_EXCLUDED_TABLE


def setup_matplotlib_korean_font():
    preferred_fonts = [
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]

    available_fonts = {f.name for f in fm.fontManager.ttflist}

    for font_name in preferred_fonts:
        if font_name in available_fonts:
            matplotlib.rcParams["font.family"] = font_name
            break

    matplotlib.rcParams["axes.unicode_minus"] = False


def load_excluded_index_rows():
    """
    return:
    [
        (draw_no, comb_idx, comb_type),
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


def get_cube_size(total_count: int) -> int:
    """
    total_count 를 담을 수 있는 최소 큐브 한 변 길이
    """
    return math.ceil(total_count ** (1 / 3))


def index_to_xyz(idx: int, cube_size: int):
    """
    1-base comb_idx -> 0-base cube 좌표
    """
    idx0 = idx - 1
    x = idx0 % cube_size
    y = (idx0 // cube_size) % cube_size
    z = idx0 // (cube_size * cube_size)
    return x, y, z


def build_point_cloud(excluded_rows):
    """
    main / bonus 점 좌표를 각각 만든다.
    """
    cube_size = get_cube_size(TOTAL_COMBINATIONS)

    main_points = []
    bonus_points = []

    for _draw_no, comb_idx, comb_type in excluded_rows:
        if comb_idx < 1 or comb_idx > TOTAL_COMBINATIONS:
            continue

        x, y, z = index_to_xyz(comb_idx, cube_size)

        if comb_type == "main":
            main_points.append((x, y, z))
        else:
            bonus_points.append((x, y, z))

    return cube_size, np.array(main_points, dtype=np.int32), np.array(bonus_points, dtype=np.int32)


def build_density_cube(excluded_rows, bin_size=8):
    """
    3D 밀도 큐브 생성
    - main: 2점
    - bonus: 1점
    """
    cube_size = get_cube_size(TOTAL_COMBINATIONS)
    bins = math.ceil(cube_size / bin_size)

    density = np.zeros((bins, bins, bins), dtype=np.float32)

    for _draw_no, comb_idx, comb_type in excluded_rows:
        if comb_idx < 1 or comb_idx > TOTAL_COMBINATIONS:
            continue

        x, y, z = index_to_xyz(comb_idx, cube_size)

        bx = x // bin_size
        by = y // bin_size
        bz = z // bin_size

        if comb_type == "main":
            density[bz, by, bx] += 2.0
        else:
            density[bz, by, bx] += 1.0

    return cube_size, density, bins


class Combination3DCubeWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)

        setup_matplotlib_korean_font()

        self.title("3D 조합 큐브")
        self.geometry("1400x920")

        self.excluded_rows = []
        self.cube_size = 0
        self.main_points = np.empty((0, 3), dtype=np.int32)
        self.bonus_points = np.empty((0, 3), dtype=np.int32)
        self.density_cube = None
        self.density_bins = 0

        self.status_var = tk.StringVar(value="불러오는 중...")
        self.mode_var = tk.StringVar(value="points")
        self.bin_size_var = tk.IntVar(value=8)
        self.max_cells_var = tk.IntVar(value=500)

        self._create_ui()
        self._load_data_and_draw()

    def _create_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="전체 조합 인덱스를 3차원 큐브 공간으로 펼친 시각화",
            font=("맑은 고딕", 12, "bold")
        ).pack(side="left", padx=(0, 12))

        ttk.Radiobutton(
            top,
            text="포인트 모드",
            value="points",
            variable=self.mode_var,
            command=self.redraw
        ).pack(side="left", padx=4)

        ttk.Radiobutton(
            top,
            text="밀도 큐브 모드",
            value="density",
            variable=self.mode_var,
            command=self.redraw
        ).pack(side="left", padx=4)

        ttk.Button(
            top,
            text="새로고침",
            command=self._load_data_and_draw
        ).pack(side="right", padx=4)

        control = ttk.Frame(self, padding=(10, 0, 10, 6))
        control.pack(fill="x")

        ttk.Label(control, text="밀도 bin 크기:", font=("맑은 고딕", 9)).pack(side="left")
        bin_combo = ttk.Combobox(
            control,
            width=6,
            state="readonly",
            values=[4, 6, 8, 10, 12, 16, 20],
            textvariable=self.bin_size_var
        )
        bin_combo.pack(side="left", padx=(6, 12))
        bin_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_density_and_redraw())

        ttk.Label(control, text="최대 표시 셀:", font=("맑은 고딕", 9)).pack(side="left")
        max_cells_combo = ttk.Combobox(
            control,
            width=8,
            state="readonly",
            values=[100, 200, 300, 500, 800, 1200, 2000],
            textvariable=self.max_cells_var
        )
        max_cells_combo.pack(side="left", padx=(6, 12))
        max_cells_combo.bind("<<ComboboxSelected>>", lambda e: self.redraw())

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
        self.ax = self.figure.add_subplot(111, projection="3d")

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        toolbar_frame = ttk.Frame(plot_frame)
        toolbar_frame.pack(fill="x")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        legend_text = (
            "범례  |  포인트 모드: 빨강=실제 당첨 조합, 주황=보너스 포함 제외 조합"
            "  |  밀도 큐브 모드: 밝을수록 해당 공간에 제외 인덱스가 더 많이 몰려 있음"
        )
        ttk.Label(bottom, text=legend_text, font=("맑은 고딕", 9)).pack(anchor="w")

    def _load_data_and_draw(self):
        try:
            self.status_var.set("DB에서 제외 인덱스 정보를 읽는 중...")
            self.update_idletasks()

            self.excluded_rows = load_excluded_index_rows()
            self.cube_size, self.main_points, self.bonus_points = build_point_cloud(self.excluded_rows)

            self.status_var.set("밀도 큐브 생성 중...")
            self.update_idletasks()

            self._build_density_cube()

            main_count = sum(1 for _, _, t in self.excluded_rows if t == "main")
            bonus_count = len(self.excluded_rows) - main_count
            unique_excluded = len({idx for _, idx, _ in self.excluded_rows})

            self.summary_label.config(
                text=(
                    f"전체 조합: {TOTAL_COMBINATIONS:,}개    "
                    f"큐브 한 변: {self.cube_size}    "
                    f"실제 당첨(main): {main_count:,}개    "
                    f"보너스 제외: {bonus_count:,}개    "
                    f"중복 제거 후 제외 인덱스: {unique_excluded:,}개"
                )
            )

            self.redraw()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"3D 큐브 데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def _build_density_cube(self):
        self.cube_size, self.density_cube, self.density_bins = build_density_cube(
            self.excluded_rows,
            bin_size=self.bin_size_var.get()
        )

    def _rebuild_density_and_redraw(self):
        try:
            self.status_var.set("밀도 큐브 다시 계산 중...")
            self.update_idletasks()
            self._build_density_cube()
            self.redraw()
            self.status_var.set("완료")
        except Exception as e:
            messagebox.showerror("오류", f"밀도 큐브를 다시 계산하는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def redraw(self):
        try:
            self.ax.clear()

            mode = self.mode_var.get()

            if mode == "points":
                self._draw_points_mode()
            else:
                self._draw_density_mode()

            self.figure.tight_layout()
            self.canvas.draw()

        except Exception as e:
            messagebox.showerror("오류", f"3D 큐브를 그리는 중 오류가 발생했습니다.\n{e}")

    def _draw_points_mode(self):
        if len(self.bonus_points) > 0:
            self.ax.scatter(
                self.bonus_points[:, 0],
                self.bonus_points[:, 1],
                self.bonus_points[:, 2],
                s=10,
                alpha=0.55,
                c="orange",
                label=f"보너스 제외 ({len(self.bonus_points):,})",
                depthshade=True
            )

        if len(self.main_points) > 0:
            self.ax.scatter(
                self.main_points[:, 0],
                self.main_points[:, 1],
                self.main_points[:, 2],
                s=22,
                alpha=0.95,
                c="red",
                label=f"실제 당첨 ({len(self.main_points):,})",
                depthshade=True
            )

        self.ax.set_title("3D 조합 큐브 - 포인트 모드", fontsize=13)
        self.ax.set_xlabel("큐브 X")
        self.ax.set_ylabel("큐브 Y")
        self.ax.set_zlabel("큐브 Z")

        self.ax.set_xlim(0, self.cube_size)
        self.ax.set_ylim(0, self.cube_size)
        self.ax.set_zlim(0, self.cube_size)

        self.ax.legend(loc="upper left")
        self.ax.view_init(elev=22, azim=35)

    def _draw_density_mode(self):
        density = self.density_cube
        if density is None or density.size == 0:
            self.ax.set_title("표시할 밀도 데이터가 없습니다.", fontsize=13)
            return

        nonzero = np.argwhere(density > 0)
        if len(nonzero) == 0:
            self.ax.set_title("제외 인덱스가 없어 밀도 큐브를 표시할 수 없습니다.", fontsize=13)
            return

        values = density[density > 0]
        max_cells = self.max_cells_var.get()

        # 값이 큰 셀만 선택
        order = np.argsort(values)[::-1]
        chosen_idx = order[:max_cells]

        selected_positions = nonzero[chosen_idx]
        selected_values = values[chosen_idx]

        xs = selected_positions[:, 2]
        ys = selected_positions[:, 1]
        zs = selected_positions[:, 0]

        norm = matplotlib.colors.Normalize(
            vmin=float(selected_values.min()),
            vmax=float(selected_values.max())
        )
        cmap = matplotlib.cm.get_cmap("hot")
        colors = cmap(norm(selected_values))

        sizes = 40 + (selected_values / selected_values.max()) * 260

        self.ax.scatter(
            xs,
            ys,
            zs,
            s=sizes,
            c=colors,
            alpha=0.78,
            depthshade=True
        )

        self.ax.set_title(
            f"3D 조합 큐브 - 밀도 모드 (bin={self.bin_size_var.get()}, 상위 {len(selected_values)}개 셀)",
            fontsize=13
        )
        self.ax.set_xlabel("블록 X")
        self.ax.set_ylabel("블록 Y")
        self.ax.set_zlabel("블록 Z")

        self.ax.set_xlim(0, self.density_bins)
        self.ax.set_ylim(0, self.density_bins)
        self.ax.set_zlim(0, self.density_bins)

        self.ax.view_init(elev=24, azim=38)

        # colorbar 기존 것 제거
        if len(self.figure.axes) > 1:
            for extra_ax in self.figure.axes[1:]:
                self.figure.delaxes(extra_ax)

        sm = matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])
        self.figure.colorbar(sm, ax=self.ax, fraction=0.03, pad=0.02)