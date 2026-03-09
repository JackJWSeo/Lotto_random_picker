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
    preferred_fonts = [
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]

    available_fonts = {f.name for f in fm.fontManager.ttflist}
    selected_font = None

    for font_name in preferred_fonts:
        if font_name in available_fonts:
            selected_font = font_name
            break

    if selected_font:
        matplotlib.rcParams["font.family"] = selected_font

    matplotlib.rcParams["axes.unicode_minus"] = False


def load_excluded_index_rows():
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


def build_index_type_map(excluded_rows, total_count):
    result = {}

    for _draw_no, comb_idx, comb_type in excluded_rows:
        if comb_idx < 1 or comb_idx > total_count:
            continue

        if comb_type == "main":
            result[comb_idx] = "main"
        else:
            if result.get(comb_idx) != "main":
                result[comb_idx] = "bonus"

    return result


def build_ring_capacities(total_count, circle_radius, ring_gap_factor=2.05):
    capacities = [1]
    assigned = 1
    ring = 1

    diameter = 2.0 * circle_radius

    while assigned < total_count:
        ring_radius = circle_radius * ring_gap_factor * ring
        circumference = 2.0 * math.pi * ring_radius
        cap = max(6, int(circumference / diameter))

        capacities.append(cap)
        assigned += cap
        ring += 1

    return capacities


def estimate_total_rings(capacities):
    return max(0, len(capacities) - 1)


def build_ring_offsets(capacities):
    """
    ring별 시작 인덱스(1-based)를 저장한다.
    ring 0 -> 1
    ring 1 -> 2
    ring 2 -> ...
    """
    offsets = [1]
    current = 2
    for ring in range(1, len(capacities)):
        offsets.append(current)
        current += capacities[ring]
    return offsets


def index_to_ring_position(index_1based, capacities, ring_offsets):
    """
    index -> (ring, pos_in_ring)
    pos_in_ring은 ring 내부 0-based
    """
    if index_1based <= 1:
        return 0, 0

    lo = 1
    hi = len(ring_offsets) - 1
    found_ring = 1

    while lo <= hi:
        mid = (lo + hi) // 2
        start_idx = ring_offsets[mid]
        end_idx = start_idx + capacities[mid] - 1

        if start_idx <= index_1based <= end_idx:
            found_ring = mid
            break
        elif index_1based < start_idx:
            hi = mid - 1
        else:
            lo = mid + 1

    pos_in_ring = index_1based - ring_offsets[found_ring]
    return found_ring, pos_in_ring


def index_to_circular_ring_xy(index_1based, circle_radius, capacities, ring_gap_factor=2.05, ring_offsets=None):
    if index_1based <= 1:
        return 0.0, 0.0

    if ring_offsets is None:
        ring_offsets = build_ring_offsets(capacities)

    ring, pos_in_ring = index_to_ring_position(index_1based, capacities, ring_offsets)
    cap = capacities[ring]
    ring_radius = circle_radius * ring_gap_factor * ring

    angle = (2.0 * math.pi * pos_in_ring) / cap
    x = ring_radius * math.cos(angle)
    y = ring_radius * math.sin(angle)
    return x, y


def build_visible_index_count(total_count, requested_count):
    if requested_count is None:
        return total_count

    requested_count = int(requested_count)
    if requested_count < 1:
        return 1
    if requested_count > total_count:
        return total_count

    return requested_count


def combination_from_index(index_1based, n=45, k=6):
    if index_1based < 1:
        raise ValueError("index_1based must be >= 1")

    total = math.comb(n, k)
    if index_1based > total:
        raise ValueError(f"index_1based must be <= {total}")

    rank = index_1based - 1
    result = []

    start = 1
    remaining_k = k

    while remaining_k > 0:
        for num in range(start, n + 1):
            count = math.comb(n - num, remaining_k - 1)
            if rank < count:
                result.append(num)
                start = num + 1
                remaining_k -= 1
                break
            rank -= count

    return result


def build_main_sequence_points_ring(excluded_rows, total_count, circle_radius, capacities, ring_gap_factor, ring_offsets):
    seq = []

    for draw_no, comb_idx, comb_type in excluded_rows:
        if comb_type != "main":
            continue
        if comb_idx < 1 or comb_idx > total_count:
            continue

        x, y = index_to_circular_ring_xy(
            comb_idx,
            circle_radius=circle_radius,
            capacities=capacities,
            ring_gap_factor=ring_gap_factor,
            ring_offsets=ring_offsets
        )

        seq.append({
            "draw_no": draw_no,
            "comb_idx": comb_idx,
            "x": x,
            "y": y,
        })

    seq.sort(key=lambda item: (item["draw_no"], item["comb_idx"]))
    return seq


def find_nearest_ring_index(x, y, total_count, circle_radius, capacities, ring_gap_factor, ring_offsets, center_idx=None, search_window=5000):
    if total_count <= 0:
        return None

    if center_idx is None:
        center_idx = 1

    start_idx = max(1, center_idx - search_window)
    end_idx = min(total_count, center_idx + search_window)

    best_idx = None
    best_dist2 = None

    for idx in range(start_idx, end_idx + 1):
        px, py = index_to_circular_ring_xy(
            idx,
            circle_radius=circle_radius,
            capacities=capacities,
            ring_gap_factor=ring_gap_factor,
            ring_offsets=ring_offsets
        )
        dist2 = (px - x) ** 2 + (py - y) ** 2

        if best_dist2 is None or dist2 < best_dist2:
            best_dist2 = dist2
            best_idx = idx

    return best_idx


def predict_next_main_index_ring(main_seq, total_count, circle_radius, capacities, ring_gap_factor, ring_offsets, randomness=0.85, candidates=12):
    if len(main_seq) < 6:
        return None

    recent = main_seq[-100:] if len(main_seq) >= 100 else main_seq[:]
    pts = np.array([[p["x"], p["y"]] for p in recent], dtype=np.float64)

    if len(pts) < 6:
        return None

    deltas = pts[1:] - pts[:-1]
    mean_delta = deltas.mean(axis=0)

    weights = np.linspace(0.25, 1.0, len(deltas))
    weighted_delta = (deltas * weights[:, None]).sum(axis=0) / weights.sum()

    last_delta = deltas[-1]
    prev_delta = deltas[-2]
    turn_delta = last_delta - prev_delta
    rotated = np.array([-last_delta[1], last_delta[0]], dtype=np.float64)

    step_norms = np.linalg.norm(deltas, axis=1)
    base_scale = float(step_norms[-20:].mean()) if len(step_norms) >= 20 else float(step_norms.mean())
    if not np.isfinite(base_scale) or base_scale <= 0:
        base_scale = 1.0

    last_pt = pts[-1]
    last_idx = recent[-1]["comb_idx"]

    candidate_results = []

    for _ in range(max(3, int(candidates))):
        noise_main = np.random.normal(0.0, base_scale * 0.55 * randomness, size=2)
        noise_turn = np.random.normal(0.0, base_scale * 0.25 * randomness, size=2)
        rot_scale = np.random.uniform(-0.35, 0.35) * randomness

        predicted_xy = (
            last_pt
            + (0.18 * mean_delta)
            + (0.42 * weighted_delta)
            + (0.20 * last_delta)
            + (0.12 * turn_delta)
            + (rot_scale * rotated)
            + noise_main
            + noise_turn
        )

        predicted_idx = find_nearest_ring_index(
            predicted_xy[0],
            predicted_xy[1],
            total_count=total_count,
            circle_radius=circle_radius,
            capacities=capacities,
            ring_gap_factor=ring_gap_factor,
            ring_offsets=ring_offsets,
            center_idx=last_idx,
            search_window=5000
        )

        if predicted_idx is None:
            continue

        px, py = index_to_circular_ring_xy(
            predicted_idx,
            circle_radius=circle_radius,
            capacities=capacities,
            ring_gap_factor=ring_gap_factor,
            ring_offsets=ring_offsets
        )

        fit_dist2 = (px - predicted_xy[0]) ** 2 + (py - predicted_xy[1]) ** 2
        idx_gap_penalty = 0.0 if predicted_idx != last_idx else (base_scale * 10.0)
        score = fit_dist2 + idx_gap_penalty

        candidate_results.append({
            "score": float(score),
            "predicted_idx": predicted_idx,
            "predicted_x": float(px),
            "predicted_y": float(py),
            "target_x": float(predicted_xy[0]),
            "target_y": float(predicted_xy[1]),
        })

    if not candidate_results:
        return None

    candidate_results.sort(key=lambda x: x["score"])

    top_n = min(4, len(candidate_results))
    pick_weights = np.array([1.0 / (i + 1) for i in range(top_n)], dtype=np.float64)
    pick_weights /= pick_weights.sum()
    picked_rank = np.random.choice(np.arange(top_n), p=pick_weights)
    picked = candidate_results[int(picked_rank)]

    predicted_numbers = combination_from_index(picked["predicted_idx"], n=45, k=6)

    return {
        "predicted_idx": picked["predicted_idx"],
        "predicted_x": picked["predicted_x"],
        "predicted_y": picked["predicted_y"],
        "target_x": picked["target_x"],
        "target_y": picked["target_y"],
        "base_draw_no": recent[-1]["draw_no"],
        "base_idx": last_idx,
        "predicted_numbers": predicted_numbers,
    }


class CircularRingHeatmapWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)

        setup_matplotlib_korean_font()

        self.title("원형 링 조합 인덱스 히트맵")
        self.geometry("1520x1040")

        self.excluded_rows = []
        self.index_type_map = {}
        self.main_seq = []

        self.status_var = tk.StringVar(value="불러오는 중...")
        self.circle_radius_var = tk.DoubleVar(value=0.48)
        self.ring_gap_factor_var = tk.DoubleVar(value=2.05)

        # scatter 방식이라 기본값을 더 크게 잡아도 됨
        self.max_draw_var = tk.IntVar(value=min(TOTAL_COMBINATIONS, 8500000))

        self.show_outline_var = tk.BooleanVar(value=False)
        self.outline_stride_var = tk.IntVar(value=1)
        self.outline_size_var = tk.DoubleVar(value=2.2)
        self.highlight_size_var = tk.DoubleVar(value=18.0)
        self.animate_count_var = tk.IntVar(value=100)

        self.figure = None
        self.ax_main = None
        self.canvas = None

        self.ring_capacities = [1]
        self.ring_offsets = [1]
        self.current_prediction = None

        self.animation_job = None
        self.animation_points = []
        self.animation_running = False
        self.animation_line = None
        self.animation_marker = None
        self.animation_text = None

        self._create_ui()
        self._load_and_draw()

    def _create_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="원형 링 기반 로또 조합 인덱스 히트맵 (Scatter 최적화)",
            font=("맑은 고딕", 12, "bold")
        ).pack(side="left", padx=(0, 12))

        ttk.Button(
            top,
            text="새로고침",
            command=self._load_and_draw
        ).pack(side="right", padx=4)

        ctrl = ttk.Frame(self, padding=(10, 0, 10, 8))
        ctrl.pack(fill="x")

        ttk.Label(ctrl, text="원 반지름").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=0.1,
            to=5.0,
            increment=0.02,
            textvariable=self.circle_radius_var,
            width=8,
            command=self.redraw
        ).pack(side="left", padx=(4, 12))

        ttk.Label(ctrl, text="링 간격 계수").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=2.0,
            to=4.0,
            increment=0.01,
            textvariable=self.ring_gap_factor_var,
            width=8,
            command=self.redraw
        ).pack(side="left", padx=(4, 12))

        ttk.Label(ctrl, text="표시 인덱스 개수").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=1,
            to=max(1, TOTAL_COMBINATIONS),
            increment=1000,
            textvariable=self.max_draw_var,
            width=11,
            command=self.redraw
        ).pack(side="left", padx=(4, 12))

        ttk.Checkbutton(
            ctrl,
            text="일반 인덱스 표시",
            variable=self.show_outline_var,
            command=self.redraw
        ).pack(side="left", padx=(0, 12))

        ttk.Label(ctrl, text="일반 간격").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=1,
            to=100000,
            increment=1,
            textvariable=self.outline_stride_var,
            width=8,
            command=self.redraw
        ).pack(side="left", padx=(4, 12))

        ttk.Label(ctrl, text="일반 점 크기").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=0.5,
            to=20,
            increment=0.2,
            textvariable=self.outline_size_var,
            width=8,
            command=self.redraw
        ).pack(side="left", padx=(4, 12))

        ttk.Label(ctrl, text="강조 점 크기").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=2,
            to=100,
            increment=1,
            textvariable=self.highlight_size_var,
            width=8,
            command=self.redraw
        ).pack(side="left", padx=(4, 12))

        ttk.Button(
            ctrl,
            text="다시 그리기",
            command=self.redraw
        ).pack(side="left", padx=(8, 0))

        anim = ttk.Frame(self, padding=(10, 0, 10, 8))
        anim.pack(fill="x")

        ttk.Label(anim, text="애니메이션 개수").pack(side="left")
        ttk.Spinbox(
            anim,
            from_=10,
            to=500,
            increment=10,
            textvariable=self.animate_count_var,
            width=8
        ).pack(side="left", padx=(4, 12))

        ttk.Button(
            anim,
            text="마지막 N개 애니메이션",
            command=self.animate_last_points
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            anim,
            text="애니메이션 정지",
            command=self.stop_animation
        ).pack(side="left", padx=(0, 16))

        ttk.Button(
            anim,
            text="다음 위치 예측",
            command=self.predict_next_position
        ).pack(side="left", padx=(0, 8))

        self.predict_label = ttk.Label(
            anim,
            text="다음 위치 예측: 준비 전",
            font=("맑은 고딕", 9)
        )
        self.predict_label.pack(side="left", padx=(8, 0))

        info = ttk.Frame(self, padding=(10, 0, 10, 6))
        info.pack(fill="x")

        self.summary_label = ttk.Label(
            info,
            text="요약 정보 준비 중...",
            font=("맑은 고딕", 10)
        )
        self.summary_label.pack(anchor="w")

        ttk.Label(
            info,
            textvariable=self.status_var,
            font=("맑은 고딕", 9)
        ).pack(anchor="w", pady=(4, 0))

        plot_frame = ttk.Frame(self, padding=10)
        plot_frame.pack(fill="both", expand=True)

        self.figure = Figure(figsize=(13, 9), dpi=100)
        self.ax_main = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=0.03, right=0.98, top=0.95, bottom=0.05)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        legend = (
            "범례  |  연회색: 일반 인덱스  |  주황: bonus  |  빨강: main  |  청록: 애니메이션/예측"
        )
        ttk.Label(bottom, text=legend, font=("맑은 고딕", 9)).pack(anchor="w")

    def _prepare_layout_data(self):
        circle_radius = max(0.05, float(self.circle_radius_var.get()))
        ring_gap_factor = max(2.0, float(self.ring_gap_factor_var.get()))

        self.ring_capacities = build_ring_capacities(
            TOTAL_COMBINATIONS,
            circle_radius=circle_radius,
            ring_gap_factor=ring_gap_factor
        )
        self.ring_offsets = build_ring_offsets(self.ring_capacities)

        self.main_seq = build_main_sequence_points_ring(
            self.excluded_rows,
            TOTAL_COMBINATIONS,
            circle_radius=circle_radius,
            capacities=self.ring_capacities,
            ring_gap_factor=ring_gap_factor,
            ring_offsets=self.ring_offsets
        )

        return circle_radius, ring_gap_factor

    def _load_and_draw(self):
        try:
            self.stop_animation(redraw_after_stop=False, clear_items=True)

            self.status_var.set("DB에서 제외 인덱스 정보를 읽는 중...")
            self.update_idletasks()

            self.excluded_rows = load_excluded_index_rows()
            self.index_type_map = build_index_type_map(self.excluded_rows, TOTAL_COMBINATIONS)

            circle_radius, ring_gap_factor = self._prepare_layout_data()

            main_count = sum(1 for v in self.index_type_map.values() if v == "main")
            bonus_count = sum(1 for v in self.index_type_map.values() if v == "bonus")
            total_unique = len(self.index_type_map)
            total_rings = estimate_total_rings(self.ring_capacities)

            self.summary_label.config(
                text=(
                    f"전체 조합: {TOTAL_COMBINATIONS:,}개    "
                    f"총 링 수: {total_rings:,}    "
                    f"실제 당첨 조합(main): {main_count:,}개    "
                    f"보너스 포함 제외 조합: {bonus_count:,}개    "
                    f"중복 제거 후 제외 인덱스: {total_unique:,}개"
                )
            )

            self.current_prediction = None
            self.predict_label.config(text="다음 위치 예측: 준비 전")

            self.redraw()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def _build_scatter_points_fast(self, max_draw_count, circle_radius, ring_gap_factor):
        outline_x, outline_y = [], []
        bonus_x, bonus_y = [], []
        main_x, main_y = [], []

        stride = max(1, int(self.outline_stride_var.get()))
        show_outline = self.show_outline_var.get()

        capped_index_type_map = {
            idx: t for idx, t in self.index_type_map.items() if idx <= max_draw_count
        }

        for idx, point_type in capped_index_type_map.items():
            x, y = index_to_circular_ring_xy(
                idx,
                circle_radius=circle_radius,
                capacities=self.ring_capacities,
                ring_gap_factor=ring_gap_factor,
                ring_offsets=self.ring_offsets
            )
            if point_type == "main":
                main_x.append(x)
                main_y.append(y)
            else:
                bonus_x.append(x)
                bonus_y.append(y)

        if show_outline:
            for idx in range(1, max_draw_count + 1, stride):
                if idx in capped_index_type_map:
                    continue

                x, y = index_to_circular_ring_xy(
                    idx,
                    circle_radius=circle_radius,
                    capacities=self.ring_capacities,
                    ring_gap_factor=ring_gap_factor,
                    ring_offsets=self.ring_offsets
                )
                outline_x.append(x)
                outline_y.append(y)

            if 1 not in capped_index_type_map and (not outline_x or outline_x[0] != 0.0 or outline_y[0] != 0.0):
                outline_x.insert(0, 0.0)
                outline_y.insert(0, 0.0)

        return (outline_x, outline_y), (bonus_x, bonus_y), (main_x, main_y)

    def _draw_prediction_marker(self):
        if not self.current_prediction:
            return

        px = self.current_prediction["predicted_x"]
        py = self.current_prediction["predicted_y"]
        idx = self.current_prediction["predicted_idx"]

        size = max(40, float(self.highlight_size_var.get()) * 1.8)

        self.ax_main.scatter(
            [px],
            [py],
            s=size,
            c="#00ffff",
            edgecolors="black",
            linewidths=0.8,
            zorder=7
        )

        self.ax_main.annotate(
            f"예상 idx {idx:,}",
            (px, py),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=9,
            color="#00aaaa",
            zorder=8,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.75)
        )

    def redraw(self):
        try:
            self.stop_animation(redraw_after_stop=False, clear_items=False)

            self.status_var.set("원형 링 좌표 계산 중...")
            self.update_idletasks()

            circle_radius, ring_gap_factor = self._prepare_layout_data()
            max_draw_count = build_visible_index_count(TOTAL_COMBINATIONS, self.max_draw_var.get())

            self.figure.clear()
            self.ax_main = self.figure.add_subplot(111)
            self.figure.subplots_adjust(left=0.03, right=0.98, top=0.95, bottom=0.05)

            (outline_x, outline_y), (bonus_x, bonus_y), (main_x, main_y) = self._build_scatter_points_fast(
                max_draw_count=max_draw_count,
                circle_radius=circle_radius,
                ring_gap_factor=ring_gap_factor
            )

            outline_size = float(self.outline_size_var.get())
            highlight_size = float(self.highlight_size_var.get())

            if outline_x:
                self.ax_main.scatter(
                    outline_x,
                    outline_y,
                    s=outline_size,
                    c="#e9e9e9",
                    edgecolors="none",
                    alpha=0.90,
                    zorder=1,
                    rasterized=True
                )

            if bonus_x:
                self.ax_main.scatter(
                    bonus_x,
                    bonus_y,
                    s=highlight_size,
                    c="#ff9800",
                    edgecolors="none",
                    alpha=0.95,
                    zorder=3,
                    rasterized=True
                )

            if main_x:
                self.ax_main.scatter(
                    main_x,
                    main_y,
                    s=highlight_size * 1.15,
                    c="#ff2a2a",
                    edgecolors="black",
                    linewidths=0.2,
                    alpha=0.98,
                    zorder=4,
                    rasterized=True
                )

            self._draw_prediction_marker()

            self.ax_main.set_title(
                f"원형 링 조합 인덱스 히트맵 (표시 인덱스: 1 ~ {max_draw_count:,})",
                fontsize=13
            )
            self.ax_main.set_aspect("equal", adjustable="box")
            self.ax_main.autoscale_view()
            self.ax_main.margins(0.02)
            self.ax_main.set_xlabel("X")
            self.ax_main.set_ylabel("Y")
            self.ax_main.grid(False)

            self.canvas.draw_idle()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"히트맵을 그리는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def animate_last_points(self):
        try:
            self.stop_animation(redraw_after_stop=True, clear_items=True)

            count = max(1, int(self.animate_count_var.get()))
            seq = self.main_seq[-count:] if len(self.main_seq) >= count else self.main_seq[:]

            if len(seq) == 0:
                messagebox.showinfo("안내", "애니메이션할 main 데이터가 없습니다.")
                return

            self.animation_points = seq
            self.animation_running = True

            self.animation_line, = self.ax_main.plot(
                [],
                [],
                color="#00ffff",
                linewidth=2.0,
                alpha=0.95,
                zorder=8
            )

            marker_size = max(60, float(self.highlight_size_var.get()) * 2.0)

            self.animation_marker = self.ax_main.scatter(
                [],
                [],
                s=marker_size,
                c="#00ffff",
                edgecolors="black",
                linewidths=0.7,
                zorder=9
            )

            self.animation_text = self.ax_main.text(
                0.02,
                0.98,
                "",
                transform=self.ax_main.transAxes,
                ha="left",
                va="top",
                fontsize=10,
                color="#00bbbb",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white", alpha=0.75)
            )

            self.status_var.set(f"애니메이션 실행 중... 최근 {len(seq)}개")
            self._animate_step(1)

        except Exception as e:
            messagebox.showerror("오류", f"애니메이션 시작 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def _animate_step(self, step_idx):
        if not self.animation_running:
            return

        if step_idx > len(self.animation_points):
            self.animation_running = False

            if self.animation_job is not None:
                try:
                    self.after_cancel(self.animation_job)
                except Exception:
                    pass
                self.animation_job = None

            self.status_var.set("애니메이션 완료 (마지막 경로 유지)")
            return

        sub = self.animation_points[:step_idx]
        xs = [p["x"] for p in sub]
        ys = [p["y"] for p in sub]
        last = sub[-1]

        self.animation_line.set_data(xs, ys)
        self.animation_marker.set_offsets(np.array([[last["x"], last["y"]]]))
        self.animation_text.set_text(
            f"회차: {last['draw_no']}\n인덱스: {last['comb_idx']:,}\n진행: {step_idx}/{len(self.animation_points)}"
        )

        self.canvas.draw_idle()
        self.animation_job = self.after(60, lambda: self._animate_step(step_idx + 1))

    def stop_animation(self, redraw_after_stop=False, clear_items=True):
        self.animation_running = False
        self.animation_points = []

        if self.animation_job is not None:
            try:
                self.after_cancel(self.animation_job)
            except Exception:
                pass
            self.animation_job = None

        if clear_items:
            if self.animation_line is not None:
                try:
                    self.animation_line.remove()
                except Exception:
                    pass
                self.animation_line = None

            if self.animation_marker is not None:
                try:
                    self.animation_marker.remove()
                except Exception:
                    pass
                self.animation_marker = None

            if self.animation_text is not None:
                try:
                    self.animation_text.remove()
                except Exception:
                    pass
                self.animation_text = None

        if redraw_after_stop:
            self.redraw()

    def predict_next_position(self):
        try:
            circle_radius, ring_gap_factor = self._prepare_layout_data()

            self.current_prediction = predict_next_main_index_ring(
                self.main_seq,
                total_count=TOTAL_COMBINATIONS,
                circle_radius=circle_radius,
                capacities=self.ring_capacities,
                ring_gap_factor=ring_gap_factor,
                ring_offsets=self.ring_offsets,
                randomness=0.85,
                candidates=12
            )

            if not self.current_prediction:
                messagebox.showinfo("안내", "예측에 필요한 main 데이터가 부족합니다.")
                return

            pred_idx = self.current_prediction["predicted_idx"]
            base_draw = self.current_prediction["base_draw_no"]
            base_idx = self.current_prediction["base_idx"]
            pred_numbers = self.current_prediction["predicted_numbers"]

            num_text = ", ".join(str(n) for n in pred_numbers)

            self.predict_label.config(
                text=f"다음 위치 예측: idx {pred_idx:,} / 번호 [{num_text}] (기준 회차 {base_draw})"
            )

            self.redraw()

            messagebox.showinfo(
                "다음 위치 예측",
                (
                    f"최근 main 위치 패턴 기반 휴리스틱 예측 결과\n\n"
                    f"기준 마지막 회차: {base_draw}\n"
                    f"기준 마지막 main 인덱스: {base_idx:,}\n"
                    f"예측 다음 인덱스: {pred_idx:,}\n"
                    f"예측 번호 조합: {pred_numbers}\n\n"
                    f"이 값은 시각 패턴 + 랜덤성을 섞은 연출용 예측값이며\n"
                    f"실제 당첨을 보장하지 않습니다."
                )
            )

        except Exception as e:
            messagebox.showerror("오류", f"다음 위치 예측 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    CircularRingHeatmapWindow(root)
    root.mainloop()