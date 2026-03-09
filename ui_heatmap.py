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

    data = np.zeros((height, width), dtype=np.float32)

    flat = data.ravel()
    flat[:total_count] = 0.15

    for _draw_no, comb_idx, comb_type in excluded_rows:
        idx0 = comb_idx - 1
        if idx0 < 0 or idx0 >= total_count:
            continue

        row = idx0 // width
        col = idx0 % width

        if comb_type == "main":
            data[row, col] = 1.0
        else:
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


def combination_from_index(index_1based, n=45, k=6):
    """
    1-based 조합 인덱스를 실제 로또 번호 조합으로 변환한다.
    조합 순서는 오름차순 사전식(lexicographic) 기준.
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


def build_main_sequence_points_rect(excluded_rows, total_count):
    """
    main 인덱스를 draw_no 순서대로 정렬하고 사각 히트맵 좌표(row, col)로 변환.
    """
    width = math.ceil(math.sqrt(total_count))

    main_rows = []
    for draw_no, comb_idx, comb_type in excluded_rows:
        if comb_type != "main":
            continue
        if comb_idx < 1 or comb_idx > total_count:
            continue
        idx0 = comb_idx - 1
        row = idx0 // width
        col = idx0 % width
        main_rows.append({
            "draw_no": draw_no,
            "comb_idx": comb_idx,
            "row": row,
            "col": col,
        })

    main_rows.sort(key=lambda x: (x["draw_no"], x["comb_idx"]))
    return main_rows


def find_nearest_rect_index(x, y, total_count):
    """
    raw 맵 좌표계에서 가장 가까운 인덱스를 찾는다.
    x -> col, y -> row
    """
    width = math.ceil(math.sqrt(total_count))
    height = math.ceil(total_count / width)

    col = int(round(x))
    row = int(round(y))

    col = max(0, min(width - 1, col))
    row = max(0, min(height - 1, row))

    idx0 = row * width + col
    idx0 = max(0, min(total_count - 1, idx0))
    return idx0 + 1


def predict_next_main_index_rect(main_seq, total_count, randomness=0.85, candidates=12):
    """
    최근 main 위치 패턴을 기반으로 raw 맵에서 다음 위치를 휴리스틱하게 추정한다.
    매번 약간 다른 결과가 나올 수 있도록 랜덤 요소를 섞는다.
    """
    if len(main_seq) < 6:
        return None

    recent = main_seq[-100:] if len(main_seq) >= 100 else main_seq[:]
    pts = np.array([[p["col"], p["row"]] for p in recent], dtype=np.float64)

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

        predicted_idx = find_nearest_rect_index(
            predicted_xy[0],
            predicted_xy[1],
            total_count=total_count
        )

        pred_width = math.ceil(math.sqrt(total_count))
        pred_idx0 = predicted_idx - 1
        pred_row = pred_idx0 // pred_width
        pred_col = pred_idx0 % pred_width

        fit_dist2 = (pred_col - predicted_xy[0]) ** 2 + (pred_row - predicted_xy[1]) ** 2
        idx_gap_penalty = 0.0 if predicted_idx != last_idx else (base_scale * 10.0)

        score = fit_dist2 + idx_gap_penalty

        candidate_results.append({
            "score": float(score),
            "predicted_idx": predicted_idx,
            "predicted_col": float(pred_col),
            "predicted_row": float(pred_row),
            "target_col": float(predicted_xy[0]),
            "target_row": float(predicted_xy[1]),
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
        "predicted_col": picked["predicted_col"],
        "predicted_row": picked["predicted_row"],
        "target_col": picked["target_col"],
        "target_row": picked["target_row"],
        "base_draw_no": recent[-1]["draw_no"],
        "base_idx": last_idx,
        "predicted_numbers": predicted_numbers,
    }


class CombinationHeatmapWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)

        setup_matplotlib_korean_font()

        self.title("조합 인덱스 히트맵")
        self.geometry("1400x940")

        self.excluded_rows = []
        self.main_seq = []
        self.status_var = tk.StringVar(value="불러오는 중...")
        self.mode_var = tk.StringVar(value="density")

        self.figure = None
        self.ax_main = None
        self.canvas = None
        self.colorbar = None

        self.animate_count_var = tk.IntVar(value=100)
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
            text="마지막 N개 애니메이션",
            command=self.animate_last_points
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            anim_frame,
            text="애니메이션 정지",
            command=self.stop_animation
        ).pack(side="left", padx=(0, 16))

        ttk.Button(
            anim_frame,
            text="다음 위치 예측",
            command=self.predict_next_position
        ).pack(side="left", padx=(0, 8))

        self.predict_label = ttk.Label(
            anim_frame,
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
        self.figure.subplots_adjust(left=0.07, right=0.92, top=0.92, bottom=0.09)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        legend_text = (
            "범례  |  배경: 전체 조합 영역  |  노랑/주황: 보너스 포함 제외 조합  |  빨강: 실제 당첨 조합  |  하늘색: 애니메이션/예측"
        )
        ttk.Label(bottom, text=legend_text, font=("맑은 고딕", 9)).pack(anchor="w")

    def _load_and_draw(self):
        try:
            self.stop_animation(redraw_after_stop=False)

            self.status_var.set("DB에서 제외 인덱스 정보를 읽는 중...")
            self.update_idletasks()

            self.excluded_rows = load_excluded_index_rows()
            self.main_seq = build_main_sequence_points_rect(
                self.excluded_rows,
                TOTAL_COMBINATIONS
            )

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

            self.predict_label.config(text="다음 위치 예측: 준비 전")
            self.current_prediction = None

            self.status_var.set("시각화 생성 중...")
            self.redraw()
            self.status_var.set("완료")

        except Exception as e:
            messagebox.showerror("오류", f"히트맵 데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_var.set("오류 발생")

    def _reset_plot(self):
        if self.colorbar is not None:
            try:
                self.colorbar.remove()
            except Exception:
                pass
            self.colorbar = None

        self.figure.clear()
        self.ax_main = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=0.07, right=0.92, top=0.92, bottom=0.09)

    def _draw_prediction_marker_raw(self):
        if self.mode_var.get() != "raw":
            return

        if not self.current_prediction:
            return

        px = self.current_prediction["predicted_col"]
        py = self.current_prediction["predicted_row"]
        idx = self.current_prediction["predicted_idx"]

        self.ax_main.scatter(
            [px],
            [py],
            s=90,
            c="#00ffff",
            edgecolors="black",
            linewidths=0.8,
            zorder=6
        )

        self.ax_main.annotate(
            f"예상 idx {idx:,}",
            (px, py),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=9,
            color="#00aaaa",
            zorder=7,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7)
        )

    def redraw(self):
        try:
            self.stop_animation(redraw_after_stop=False)
            self._reset_plot()

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

                self.colorbar = self.figure.colorbar(
                    im,
                    ax=self.ax_main,
                    fraction=0.03,
                    pad=0.02
                )

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

                self.colorbar = self.figure.colorbar(
                    im,
                    ax=self.ax_main,
                    fraction=0.03,
                    pad=0.02
                )

                self._draw_prediction_marker_raw()

            self.canvas.draw_idle()

        except Exception as e:
            messagebox.showerror("오류", f"히트맵을 그리는 중 오류가 발생했습니다.\n{e}")

    def animate_last_points(self):
        try:
            if self.mode_var.get() != "raw":
                messagebox.showinfo("안내", "애니메이션은 '개별 인덱스 맵' 모드에서 확인할 수 있습니다.")
                return

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
                s=100,
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
        xs = [p["col"] for p in sub]
        ys = [p["row"] for p in sub]
        last = sub[-1]

        self.animation_line.set_data(xs, ys)
        self.animation_marker.set_offsets(np.array([[last["col"], last["row"]]]))
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
            self.current_prediction = predict_next_main_index_rect(
                self.main_seq,
                total_count=TOTAL_COMBINATIONS,
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
                    f"다음 위치 예측: idx {pred_idx:,} / 번호 [{num_text}] "
                    f"(기준 회차 {base_draw})"
                )
            )

            if self.mode_var.get() == "raw":
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
    CombinationHeatmapWindow(root)
    root.mainloop()