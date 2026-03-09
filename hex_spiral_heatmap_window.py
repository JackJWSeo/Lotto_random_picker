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

    if selected_font is not None:
        matplotlib.rcParams["font.family"] = selected_font

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


def max_index_in_ring(ring: int) -> int:
    """
    ring 0 -> 1
    ring 1 -> 7
    ring 2 -> 19
    ring r -> 1 + 3r(r+1)
    """
    return 1 + 3 * ring * (ring + 1)


def ring_of_index(index_1based: int) -> int:
    """
    주어진 1-based index가 속한 ring 번호를 반환
    """
    if index_1based <= 1:
        return 0

    r = int(math.ceil((-3 + math.sqrt(12 * index_1based - 3)) / 6))
    while max_index_in_ring(r) < index_1based:
        r += 1
    while r > 0 and max_index_in_ring(r - 1) >= index_1based:
        r -= 1
    return r


def index_to_axial(index_1based: int):
    """
    1-based 조합 인덱스를 hex spiral axial 좌표(q, r)로 변환한다.

    배치 규칙:
    - index 1 = 중심 (0, 0)
    - ring 1 시작점 = (1, 0)
    - 이후 육각형 테두리를 따라 6방향으로 순서대로 진행
    """
    if index_1based <= 1:
        return 0, 0

    ring = ring_of_index(index_1based)
    prev_max = max_index_in_ring(ring - 1)
    offset = index_1based - (prev_max + 1)

    q, r = ring, 0

    directions = [
        (-1, 1),
        (-1, 0),
        (0, -1),
        (1, -1),
        (1, 0),
        (0, 1),
    ]

    side = offset // ring
    step_in_side = offset % ring

    for side_idx in range(side):
        dq, dr = directions[side_idx]
        q += dq * ring
        r += dr * ring

    dq, dr = directions[side]
    q += dq * step_in_side
    r += dr * step_in_side

    return q, r


def axial_to_xy(q, r, size=1.0):
    """
    axial(q, r) -> 2D 좌표
    pointy-top hex 좌표계를 사용
    """
    x = size * math.sqrt(3) * (q + r / 2.0)
    y = size * 1.5 * r
    return x, y


def build_highlight_points(excluded_rows, total_count, size=1.0):
    """
    main / bonus 강조용 좌표 생성
    중복 인덱스는 더 강한 값(main) 우선.
    """
    index_map = {}

    for _draw_no, comb_idx, comb_type in excluded_rows:
        if comb_idx < 1 or comb_idx > total_count:
            continue

        current = index_map.get(comb_idx)

        if comb_type == "main":
            index_map[comb_idx] = "main"
        else:
            if current != "main":
                index_map[comb_idx] = "bonus"

    main_x, main_y = [], []
    bonus_x, bonus_y = [], []

    for idx, point_type in sorted(index_map.items()):
        q, r = index_to_axial(idx)
        x, y = axial_to_xy(q, r, size=size)

        if point_type == "main":
            main_x.append(x)
            main_y.append(y)
        else:
            bonus_x.append(x)
            bonus_y.append(y)

    return (main_x, main_y), (bonus_x, bonus_y), index_map


def build_sample_background_points(total_count, step, size=1.0):
    """
    전체 구조를 눈으로 보기 위한 샘플 배경 점 생성.
    step 간격으로 인덱스를 샘플링한다.
    """
    if step <= 0:
        step = 1

    xs = []
    ys = []

    for idx in range(1, total_count + 1, step):
        q, r = index_to_axial(idx)
        x, y = axial_to_xy(q, r, size=size)
        xs.append(x)
        ys.append(y)

    if total_count > 0 and (total_count - 1) % step != 0:
        q, r = index_to_axial(total_count)
        x, y = axial_to_xy(q, r, size=size)
        xs.append(x)
        ys.append(y)

    return xs, ys


def estimate_outer_ring(total_count: int) -> int:
    return ring_of_index(total_count)


def build_main_sequence_points(excluded_rows, total_count, size=1.0):
    """
    main 인덱스만 draw_no 순서대로 정렬해서 연결용 좌표 생성.
    draw_no 중복 시 comb_idx 오름차순 보조 정렬.
    """
    main_rows = []
    for draw_no, comb_idx, comb_type in excluded_rows:
        if comb_type != "main":
            continue
        if comb_idx < 1 or comb_idx > total_count:
            continue
        main_rows.append((draw_no, comb_idx))

    main_rows.sort(key=lambda x: (x[0], x[1]))

    seq = []
    for draw_no, comb_idx in main_rows:
        q, r = index_to_axial(comb_idx)
        x, y = axial_to_xy(q, r, size=size)
        seq.append({
            "draw_no": draw_no,
            "comb_idx": comb_idx,
            "x": x,
            "y": y,
        })
    return seq


def find_nearest_index_from_xy(x, y, total_count, search_window=2500, center_idx=None, size=1.0):
    """
    추정 좌표에 가장 가까운 인덱스를 찾는다.
    전체를 전수 탐색하지 않도록 center_idx 주변을 우선 검색.
    """
    if total_count <= 0:
        return None

    if center_idx is None:
        center_idx = 1

    start_idx = max(1, center_idx - search_window)
    end_idx = min(total_count, center_idx + search_window)

    best_idx = None
    best_dist2 = None

    for idx in range(start_idx, end_idx + 1):
        q, r = index_to_axial(idx)
        px, py = axial_to_xy(q, r, size=size)
        dist2 = (px - x) ** 2 + (py - y) ** 2

        if best_dist2 is None or dist2 < best_dist2:
            best_dist2 = dist2
            best_idx = idx

    return best_idx

def combination_from_index(index_1based, n=45, k=6):
    """
    1-based 조합 인덱스를 실제 로또 번호 조합으로 변환한다.
    조합 순서는 오름차순 사전식(lexicographic) 기준.

    예:
        1 -> [1, 2, 3, 4, 5, 6]
    """
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
            else:
                rank -= count

    return result

def predict_next_main_index(main_seq, total_count, size=1.0, randomness=0.85, candidates=12):
    """
    최근 main 위치 패턴을 기반으로 다음 위치를 휴리스틱하게 추정한다.
    매번 약간 다른 결과가 나올 수 있도록 랜덤 요소를 섞는다.

    방식:
    - 최근 100개 사용
    - 평균 이동 + 가중 평균 이동 + 최근 방향 + 회전 성분
    - 노이즈를 여러 후보에 섞은 뒤 가장 자연스러운 후보 선택
    """
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

    # 최근 회전 경향 반영
    turn_delta = last_delta - prev_delta
    rotated = np.array([-last_delta[1], last_delta[0]], dtype=np.float64)

    # 최근 이동 크기 기준 노이즈 스케일 계산
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

        predicted_idx = find_nearest_index_from_xy(
            predicted_xy[0],
            predicted_xy[1],
            total_count=total_count,
            search_window=5000,
            center_idx=last_idx,
            size=size
        )

        if predicted_idx is None:
            continue

        q, r = index_to_axial(predicted_idx)
        px, py = axial_to_xy(q, r, size=size)

        # 후보 점수:
        # target과 가까울수록 좋고, 마지막 인덱스와 너무 같으면 패널티
        fit_dist2 = (px - predicted_xy[0]) ** 2 + (py - predicted_xy[1]) ** 2
        idx_gap_penalty = 0.0 if predicted_idx != last_idx else (base_scale * 10.0)

        score = fit_dist2 + idx_gap_penalty

        candidate_results.append({
            "score": float(score),
            "predicted_idx": predicted_idx,
            "predicted_x": px,
            "predicted_y": py,
            "target_x": float(predicted_xy[0]),
            "target_y": float(predicted_xy[1]),
        })

    if not candidate_results:
        return None

    candidate_results.sort(key=lambda x: x["score"])

    # 항상 1등만 고르지 않고 상위 후보 중 하나를 확률적으로 선택
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

class HexSpiralHeatmapWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)

        setup_matplotlib_korean_font()

        self.title("육각 나선 조합 인덱스 히트맵")
        self.geometry("1450x980")

        self.excluded_rows = []
        self.index_type_map = {}
        self.main_seq = []

        self.status_var = tk.StringVar(value="불러오는 중...")
        self.show_background_var = tk.BooleanVar(value=True)
        self.sample_step_var = tk.IntVar(value=max(1, TOTAL_COMBINATIONS // 12000))
        self.point_size_var = tk.DoubleVar(value=10.0)
        self.show_main_path_var = tk.BooleanVar(value=False)
        self.animate_count_var = tk.IntVar(value=100)

        self.figure = None
        self.ax_main = None
        self.canvas = None

        self.current_prediction = None
        self.animation_job = None
        self.animation_points = []
        self.animation_line = None
        self.animation_marker = None
        self.animation_text = None
        self.animation_running = False

        self._create_ui()
        self._load_and_draw()

    def _create_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="육각 나선(Hex Spiral) 기반 로또 조합 인덱스 히트맵",
            font=("맑은 고딕", 12, "bold")
        ).pack(side="left", padx=(0, 12))

        ttk.Button(
            top,
            text="새로고침",
            command=self._load_and_draw
        ).pack(side="right", padx=4)

        control = ttk.Frame(self, padding=(10, 0, 10, 8))
        control.pack(fill="x")

        ttk.Checkbutton(
            control,
            text="배경 샘플 점 표시",
            variable=self.show_background_var,
            command=self.redraw
        ).pack(side="left", padx=(0, 12))

        ttk.Label(control, text="배경 샘플 간격").pack(side="left")
        step_spin = ttk.Spinbox(
            control,
            from_=1,
            to=max(1, TOTAL_COMBINATIONS),
            textvariable=self.sample_step_var,
            width=10,
            command=self.redraw
        )
        step_spin.pack(side="left", padx=(4, 12))

        ttk.Label(control, text="강조 점 크기").pack(side="left")
        size_spin = ttk.Spinbox(
            control,
            from_=4,
            to=80,
            increment=1,
            textvariable=self.point_size_var,
            width=8,
            command=self.redraw
        )
        size_spin.pack(side="left", padx=(4, 12))

        ttk.Checkbutton(
            control,
            text="main 순서 연결선 표시",
            variable=self.show_main_path_var,
            command=self.redraw
        ).pack(side="left", padx=(8, 12))

        ttk.Button(
            control,
            text="다시 그리기",
            command=self.redraw
        ).pack(side="left", padx=(4, 0))

        anim_frame = ttk.Frame(self, padding=(10, 0, 10, 8))
        anim_frame.pack(fill="x")

        ttk.Label(anim_frame, text="애니메이션 개수").pack(side="left")
        ttk.Spinbox(
            anim_frame,
            from_=10,
            to=500,
            increment=10,
            textvariable=self.animate_count_var,
            width=8
        ).pack(side="left", padx=(4, 12))

        ttk.Button(
            anim_frame,
            text="애니메이션 시작",
            command=self.animate_last_points
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            anim_frame,
            text="애니메이션 정지",
            command=self.stop_animation
        ).pack(side="left", padx=(0, 16))

        ttk.Button(
            anim_frame,
            text="다음 위치 추정",
            command=self.predict_next_position
        ).pack(side="left", padx=(0, 8))

        self.predict_label = ttk.Label(
            anim_frame,
            text="다음 위치 추정: 준비 전",
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

        self.status_label = ttk.Label(
            info,
            textvariable=self.status_var,
            font=("맑은 고딕", 9)
        )
        self.status_label.pack(anchor="w", pady=(4, 0))

        plot_frame = ttk.Frame(self, padding=10)
        plot_frame.pack(fill="both", expand=True)

        self.figure = Figure(figsize=(13, 9), dpi=100)
        self.ax_main = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=0.04, right=0.98, top=0.95, bottom=0.06)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        legend_text = (
            "범례  |  회색: 전체 인덱스 구조 샘플  |  주황: 보너스 포함 제외 조합  |  빨강: 실제 당첨 조합(main)  |  하늘색 선: main 회차 순서 연결"
        )
        ttk.Label(bottom, text=legend_text, font=("맑은 고딕", 9)).pack(anchor="w")

    def _load_and_draw(self):
        try:
            self.stop_animation()

            self.status_var.set("DB에서 제외 인덱스 정보를 읽는 중...")
            self.update_idletasks()

            self.excluded_rows = load_excluded_index_rows()

            main_count = sum(1 for _, _, t in self.excluded_rows if t == "main")
            bonus_count = len(self.excluded_rows) - main_count
            unique_excluded = len({idx for _, idx, _ in self.excluded_rows})
            outer_ring = estimate_outer_ring(TOTAL_COMBINATIONS)

            self.main_seq = build_main_sequence_points(
                self.excluded_rows,
                TOTAL_COMBINATIONS,
                size=1.0
            )

            self.summary_label.config(
                text=(
                    f"전체 조합: {TOTAL_COMBINATIONS:,}개    "
                    f"최외곽 링: {outer_ring:,}    "
                    f"실제 당첨 조합(main): {main_count:,}개    "
                    f"보너스 포함 제외 조합: {bonus_count:,}개    "
                    f"중복 제거 후 제외 인덱스: {unique_excluded:,}개"
                )
            )

            self.predict_label.config(text="다음 위치 추정: 준비 전")

            self.status_var.set("시각화 생성 중...")
            self.redraw()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"육각 나선 히트맵 데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def _draw_main_path(self):
        if not self.show_main_path_var.get():
            return

        if len(self.main_seq) < 2:
            return

        xs = [p["x"] for p in self.main_seq]
        ys = [p["y"] for p in self.main_seq]

        self.ax_main.plot(
            xs,
            ys,
            color="#66ccff",
            linewidth=1.0,
            alpha=0.55,
            linestyle="-",
            zorder=2,
            label=f"main 순서 연결 ({len(xs):,})"
        )

    def _draw_prediction_marker(self):
        if not self.current_prediction:
            return

        px = self.current_prediction["predicted_x"]
        py = self.current_prediction["predicted_y"]
        idx = self.current_prediction["predicted_idx"]

        self.ax_main.scatter(
            [px],
            [py],
            s=max(40, float(self.point_size_var.get()) * 2.2),
            c="#00ff88",
            edgecolors="black",
            linewidths=0.8,
            zorder=6,
            label=f"추정 위치 idx {idx:,}"
        )

        self.ax_main.annotate(
            f"예상 idx {idx:,}",
            (px, py),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=9,
            color="#00aa66",
            zorder=7
        )

    def redraw(self):
        try:
            self.stop_animation(redraw_after_stop=False)

            self.figure.clear()
            self.ax_main = self.figure.add_subplot(111)
            self.figure.subplots_adjust(left=0.04, right=0.98, top=0.95, bottom=0.06)

            point_scale = 1.0

            self.status_var.set("좌표 계산 중...")
            self.update_idletasks()

            (main_x, main_y), (bonus_x, bonus_y), self.index_type_map = build_highlight_points(
                self.excluded_rows,
                TOTAL_COMBINATIONS,
                size=point_scale
            )

            if self.show_background_var.get():
                sample_step = max(1, int(self.sample_step_var.get()))
                bg_x, bg_y = build_sample_background_points(
                    TOTAL_COMBINATIONS,
                    step=sample_step,
                    size=point_scale
                )

                self.ax_main.scatter(
                    bg_x,
                    bg_y,
                    s=6,
                    alpha=0.18,
                    c="#888888",
                    edgecolors="none",
                    label=f"전체 구조 샘플 (1/{sample_step:,})",
                    rasterized=True,
                    zorder=1
                )

            self._draw_main_path()

            highlight_size = float(self.point_size_var.get())

            if bonus_x:
                self.ax_main.scatter(
                    bonus_x,
                    bonus_y,
                    s=highlight_size,
                    alpha=0.90,
                    c="#ff9900",
                    edgecolors="none",
                    label=f"보너스 포함 제외 ({len(bonus_x):,})",
                    rasterized=True,
                    zorder=3
                )

            if main_x:
                self.ax_main.scatter(
                    main_x,
                    main_y,
                    s=highlight_size * 1.25,
                    alpha=0.95,
                    c="#ff2222",
                    edgecolors="black",
                    linewidths=0.25,
                    label=f"실제 당첨 조합 main ({len(main_x):,})",
                    rasterized=True,
                    zorder=4
                )

            cx, cy = axial_to_xy(0, 0, size=point_scale)
            self.ax_main.scatter(
                [cx],
                [cy],
                s=max(24, highlight_size * 1.6),
                c="#00aaff",
                edgecolors="black",
                linewidths=0.5,
                alpha=0.95,
                label="중앙 인덱스 1",
                zorder=5
            )

            self._draw_prediction_marker()

            self.ax_main.set_title("육각 나선 기반 조합 인덱스 히트맵", fontsize=13)
            self.ax_main.set_xlabel("Hex Spiral X")
            self.ax_main.set_ylabel("Hex Spiral Y")
            self.ax_main.set_aspect("equal", adjustable="box")
            self.ax_main.grid(False)

            self.ax_main.legend(loc="upper right", fontsize=9, frameon=True)
            self.canvas.draw_idle()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"육각 나선 히트맵을 그리는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def animate_last_points(self):
        try:
            self.stop_animation(redraw_after_stop=False)
            self.redraw()

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
                alpha=0.9,
                zorder=7
            )

            self.animation_marker = self.ax_main.scatter(
                [],
                [],
                s=max(60, float(self.point_size_var.get()) * 2.8),
                c="#00ffff",
                edgecolors="black",
                linewidths=0.7,
                zorder=8
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
            self.status_var.set("애니메이션 완료")
            self.animation_running = False
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

    def stop_animation(self, redraw_after_stop=False):
        if self.animation_job is not None:
            try:
                self.after_cancel(self.animation_job)
            except Exception:
                pass
            self.animation_job = None

        self.animation_running = False
        self.animation_points = []
        self.animation_line = None
        self.animation_marker = None
        self.animation_text = None

        if redraw_after_stop:
            self.redraw()

    def predict_next_position(self):
        try:
            self.current_prediction = predict_next_main_index(
                self.main_seq,
                total_count=TOTAL_COMBINATIONS,
                size=1.0,
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
                text=(
                    f"다음 위치 추정: idx {pred_idx:,} / 번호 [{num_text}] "
                    f"(기준 회차 {base_draw})"
                )
            )

            self.redraw()

            messagebox.showinfo(
                "다음 위치 추정",
                (
                    f"최근 main 위치 패턴 기반 휴리스틱 추정 결과\n\n"
                    f"기준 마지막 회차: {base_draw}\n"
                    f"기준 마지막 main 인덱스: {base_idx:,}\n"
                    f"추정 다음 인덱스: {pred_idx:,}\n"
                    f"추정 번호 조합: {pred_numbers}\n\n"
                    f"이 값은 시각 패턴 + 랜덤성을 섞은 연출용 추정값이며\n"
                    f"실제 당첨을 보장하지 않습니다."
                )
            )

        except Exception as e:
            messagebox.showerror("오류", f"다음 위치 추정 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    HexSpiralHeatmapWindow(root)
    root.mainloop()