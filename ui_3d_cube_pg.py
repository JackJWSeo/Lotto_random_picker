import math
import os
import sqlite3
import sys
import pyperclip

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.Qt import QtCore, QtWidgets

from config import DB_PATH, TOTAL_COMBINATIONS, WIN_EXCLUDED_TABLE


def get_connection():
    return sqlite3.connect(DB_PATH)


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


def get_cube_size(total_count: int) -> int:
    return math.ceil(total_count ** (1 / 3))


def index_to_xyz(idx: int, cube_size: int):
    idx0 = idx - 1
    x = idx0 % cube_size
    y = (idx0 // cube_size) % cube_size
    z = idx0 // (cube_size * cube_size)
    return x, y, z


def xyz_to_index(x: int, y: int, z: int, cube_size: int, total_count: int):
    x = max(0, min(cube_size - 1, int(x)))
    y = max(0, min(cube_size - 1, int(y)))
    z = max(0, min(cube_size - 1, int(z)))

    idx0 = z * cube_size * cube_size + y * cube_size + x
    idx0 = max(0, min(total_count - 1, idx0))
    return idx0 + 1


def build_point_cloud(excluded_rows):
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

    main_arr = np.array(main_points, dtype=np.float32) if main_points else np.empty((0, 3), dtype=np.float32)
    bonus_arr = np.array(bonus_points, dtype=np.float32) if bonus_points else np.empty((0, 3), dtype=np.float32)

    return cube_size, main_arr, bonus_arr


def build_main_sequence_points_3d(excluded_rows, total_count):
    cube_size = get_cube_size(total_count)

    seq = []
    for draw_no, comb_idx, comb_type in excluded_rows:
        if comb_type != "main":
            continue
        if comb_idx < 1 or comb_idx > total_count:
            continue

        x, y, z = index_to_xyz(comb_idx, cube_size)
        seq.append({
            "draw_no": draw_no,
            "comb_idx": comb_idx,
            "x": float(x),
            "y": float(y),
            "z": float(z),
        })

    seq.sort(key=lambda item: (item["draw_no"], item["comb_idx"]))
    return seq


def build_density_cloud(excluded_rows, bin_size=8, max_cells=1200):
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

    nonzero = np.argwhere(density > 0)
    if len(nonzero) == 0:
        return cube_size, np.empty((0, 3), dtype=np.float32), np.empty((0,), dtype=np.float32)

    values = density[density > 0]
    order = np.argsort(values)[::-1]
    chosen = order[:max_cells]

    selected_pos = nonzero[chosen]
    selected_val = values[chosen]

    pts = []
    for bz, by, bx in selected_pos:
        cx = bx * bin_size + (bin_size / 2.0)
        cy = by * bin_size + (bin_size / 2.0)
        cz = bz * bin_size + (bin_size / 2.0)
        pts.append((cx, cy, cz))

    pts_arr = np.array(pts, dtype=np.float32)
    val_arr = np.array(selected_val, dtype=np.float32)

    return cube_size, pts_arr, val_arr


def center_points(points: np.ndarray, cube_size: int):
    if len(points) == 0:
        return points
    centered = points.copy()
    centered[:, 0] -= cube_size / 2.0
    centered[:, 1] -= cube_size / 2.0
    centered[:, 2] -= cube_size / 2.0
    return centered


def downsample_points(points: np.ndarray, max_points: int):
    if len(points) <= max_points:
        return points
    idx = np.linspace(0, len(points) - 1, max_points, dtype=np.int32)
    return points[idx]


def build_neighbor_edges(points: np.ndarray, distance_threshold: float, max_points_for_edges: int = 1200, max_edges: int = 6000):
    if len(points) < 2:
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.float32)

    pts = downsample_points(points, max_points_for_edges)
    threshold_sq = distance_threshold * distance_threshold

    segments = []
    n = len(pts)

    for i in range(n):
        pi = pts[i]
        diff = pts[i + 1:] - pi
        dist_sq = np.sum(diff * diff, axis=1)

        near_idx = np.where(dist_sq <= threshold_sq)[0]
        if len(near_idx) == 0:
            continue

        for j_local in near_idx:
            j = i + 1 + j_local
            segments.append((pi, pts[j]))
            if len(segments) >= max_edges:
                break

        if len(segments) >= max_edges:
            break

    if not segments:
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.float32)

    starts = np.array([s[0] for s in segments], dtype=np.float32)
    ends = np.array([s[1] for s in segments], dtype=np.float32)
    return starts, ends


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
            else:
                rank -= count

    return result


def find_nearest_cube_index(x, y, z, cube_size, total_count):
    rx = int(round(x))
    ry = int(round(y))
    rz = int(round(z))
    return xyz_to_index(rx, ry, rz, cube_size, total_count)


def predict_next_main_index_3d(main_seq, total_count, randomness=0.85, candidates=12):
    if len(main_seq) < 6:
        return None

    cube_size = get_cube_size(total_count)
    recent = main_seq[-100:] if len(main_seq) >= 100 else main_seq[:]
    pts = np.array([[p["x"], p["y"], p["z"]] for p in recent], dtype=np.float64)

    if len(pts) < 6:
        return None

    deltas = pts[1:] - pts[:-1]
    mean_delta = deltas.mean(axis=0)

    weights = np.linspace(0.25, 1.0, len(deltas))
    weighted_delta = (deltas * weights[:, None]).sum(axis=0) / weights.sum()

    last_delta = deltas[-1]
    prev_delta = deltas[-2]
    turn_delta = last_delta - prev_delta

    step_norms = np.linalg.norm(deltas, axis=1)
    base_scale = float(step_norms[-20:].mean()) if len(step_norms) >= 20 else float(step_norms.mean())
    if not np.isfinite(base_scale) or base_scale <= 0:
        base_scale = 1.0

    last_pt = pts[-1]
    last_idx = recent[-1]["comb_idx"]

    candidate_results = []

    for _ in range(max(3, int(candidates))):
        noise_main = np.random.normal(0.0, base_scale * 0.55 * randomness, size=3)
        noise_turn = np.random.normal(0.0, base_scale * 0.25 * randomness, size=3)

        predicted_xyz = (
            last_pt
            + (0.18 * mean_delta)
            + (0.42 * weighted_delta)
            + (0.20 * last_delta)
            + (0.12 * turn_delta)
            + noise_main
            + noise_turn
        )

        predicted_idx = find_nearest_cube_index(
            predicted_xyz[0],
            predicted_xyz[1],
            predicted_xyz[2],
            cube_size=cube_size,
            total_count=total_count
        )

        px, py, pz = index_to_xyz(predicted_idx, cube_size)

        fit_dist2 = (
            (px - predicted_xyz[0]) ** 2 +
            (py - predicted_xyz[1]) ** 2 +
            (pz - predicted_xyz[2]) ** 2
        )
        idx_gap_penalty = 0.0 if predicted_idx != last_idx else (base_scale * 10.0)
        score = fit_dist2 + idx_gap_penalty

        candidate_results.append({
            "score": float(score),
            "predicted_idx": predicted_idx,
            "predicted_x": float(px),
            "predicted_y": float(py),
            "predicted_z": float(pz),
            "target_x": float(predicted_xyz[0]),
            "target_y": float(predicted_xyz[1]),
            "target_z": float(predicted_xyz[2]),
        })

    if not candidate_results:
        return None

    candidate_results.sort(key=lambda item: item["score"])

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
        "predicted_z": picked["predicted_z"],
        "target_x": picked["target_x"],
        "target_y": picked["target_y"],
        "target_z": picked["target_z"],
        "base_draw_no": recent[-1]["draw_no"],
        "base_idx": last_idx,
        "predicted_numbers": predicted_numbers,
    }


class Combination3DCubePGWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("GPU 3D 조합 큐브")
        self.resize(1520, 1020)

        self.excluded_rows = []
        self.cube_size = 0
        self.main_points = np.empty((0, 3), dtype=np.float32)
        self.bonus_points = np.empty((0, 3), dtype=np.float32)
        self.main_seq = []

        self.current_items = []
        self.animation_timer = None
        self.animation_running = False
        self.animation_points = []
        self.animation_index = 0
        self.animation_line_item = None
        self.animation_head_item = None
        self.prediction_item = None

        self.current_prediction = None

        self._create_ui()
        self._load_data_and_draw()

    def _create_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        top_row = QtWidgets.QHBoxLayout()
        root.addLayout(top_row)

        title = QtWidgets.QLabel("전체 조합 인덱스를 3차원 큐브 공간으로 펼친 GPU 시각화")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        top_row.addWidget(title)
        top_row.addStretch(1)

        top_row.addWidget(QtWidgets.QLabel("모드"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["포인트 모드", "밀도 모드"])
        self.mode_combo.currentIndexChanged.connect(self.redraw)
        top_row.addWidget(self.mode_combo)

        top_row.addWidget(QtWidgets.QLabel("bin 크기"))
        self.bin_combo = QtWidgets.QComboBox()
        self.bin_combo.addItems(["4", "6", "8", "10", "12", "16", "20"])
        self.bin_combo.setCurrentText("8")
        self.bin_combo.currentIndexChanged.connect(self.redraw)
        top_row.addWidget(self.bin_combo)

        top_row.addWidget(QtWidgets.QLabel("최대 표시 셀"))
        self.max_cells_combo = QtWidgets.QComboBox()
        self.max_cells_combo.addItems(["100", "200", "300", "500", "800", "1200", "2000"])
        self.max_cells_combo.setCurrentText("1200")
        self.max_cells_combo.currentIndexChanged.connect(self.redraw)
        top_row.addWidget(self.max_cells_combo)

        refresh_btn = QtWidgets.QPushButton("새로고침")
        refresh_btn.clicked.connect(self._load_data_and_draw)
        top_row.addWidget(refresh_btn)

        control_row = QtWidgets.QHBoxLayout()
        root.addLayout(control_row)

        control_row.addWidget(QtWidgets.QLabel("점 알파"))
        self.alpha_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.alpha_slider.setMinimum(1)
        self.alpha_slider.setMaximum(100)
        self.alpha_slider.setValue(18)
        self.alpha_slider.setFixedWidth(160)
        self.alpha_slider.valueChanged.connect(self.redraw)
        control_row.addWidget(self.alpha_slider)

        self.alpha_value_label = QtWidgets.QLabel("0.18")
        control_row.addWidget(self.alpha_value_label)

        control_row.addSpacing(20)

        self.link_checkbox = QtWidgets.QCheckBox("인접 점 연결")
        self.link_checkbox.setChecked(False)
        self.link_checkbox.stateChanged.connect(self.redraw)
        control_row.addWidget(self.link_checkbox)

        control_row.addWidget(QtWidgets.QLabel("인접 거리"))
        self.distance_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.distance_slider.setMinimum(1)
        self.distance_slider.setMaximum(60)
        self.distance_slider.setValue(8)
        self.distance_slider.setFixedWidth(180)
        self.distance_slider.valueChanged.connect(self.redraw)
        control_row.addWidget(self.distance_slider)

        self.distance_value_label = QtWidgets.QLabel("8")
        control_row.addWidget(self.distance_value_label)

        control_row.addSpacing(20)

        control_row.addWidget(QtWidgets.QLabel("연결선 알파"))
        self.link_alpha_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.link_alpha_slider.setMinimum(1)
        self.link_alpha_slider.setMaximum(100)
        self.link_alpha_slider.setValue(12)
        self.link_alpha_slider.setFixedWidth(160)
        self.link_alpha_slider.valueChanged.connect(self.redraw)
        control_row.addWidget(self.link_alpha_slider)

        self.link_alpha_value_label = QtWidgets.QLabel("0.12")
        control_row.addWidget(self.link_alpha_value_label)

        control_row.addStretch(1)

        anim_row = QtWidgets.QHBoxLayout()
        root.addLayout(anim_row)

        anim_row.addWidget(QtWidgets.QLabel("애니메이션 개수"))
        self.animate_count_spin = QtWidgets.QSpinBox()
        self.animate_count_spin.setRange(10, 500)
        self.animate_count_spin.setSingleStep(10)
        self.animate_count_spin.setValue(100)
        self.animate_count_spin.setFixedWidth(90)
        anim_row.addWidget(self.animate_count_spin)

        self.animate_btn = QtWidgets.QPushButton("마지막 N개 애니메이션")
        self.animate_btn.clicked.connect(self.animate_last_points)
        anim_row.addWidget(self.animate_btn)

        self.stop_btn = QtWidgets.QPushButton("애니메이션 정지")
        self.stop_btn.clicked.connect(self.stop_animation)
        anim_row.addWidget(self.stop_btn)

        self.predict_btn = QtWidgets.QPushButton("다음 위치 예측")
        self.predict_btn.clicked.connect(self.predict_next_position)
        anim_row.addWidget(self.predict_btn)

        self.predict_label = QtWidgets.QLabel("다음 위치 예측: 준비 전")
        self.predict_label.setStyleSheet("font-size: 13px;")
        anim_row.addWidget(self.predict_label)
        anim_row.addStretch(1)

        self.summary_label = QtWidgets.QLabel("요약 정보 준비 중...")
        self.summary_label.setStyleSheet("font-size: 14px;")
        root.addWidget(self.summary_label)

        self.status_label = QtWidgets.QLabel("불러오는 중...")
        root.addWidget(self.status_label)

        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor((8, 8, 8, 255))
        self.view.setMinimumHeight(600)
        self.view.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        root.addWidget(self.view, stretch=1)

        guide = QtWidgets.QLabel(
            "마우스 좌클릭 드래그: 회전   |   휠: 확대/축소   |   우클릭 드래그: 이동"
        )
        guide.setMaximumHeight(30)
        root.addWidget(guide)

        self._setup_static_scene()

    def _setup_static_scene(self):
        self.view.clear()

        grid = gl.GLGridItem()
        grid.setSize(x=260, y=260, z=0)
        grid.setSpacing(x=10, y=10, z=10)
        grid.translate(0, 0, -110)
        self.view.addItem(grid)

        axis = gl.GLAxisItem()
        axis.setSize(120, 120, 120)
        self.view.addItem(axis)

        self.view.opts["distance"] = 350
        self.view.opts["elevation"] = 22
        self.view.opts["azimuth"] = 38
        self.view.opts["fov"] = 60
        self.view.opts["center"] = pg.Vector(0, 0, 0)

    def _clear_dynamic_items(self):
        for item in self.current_items:
            try:
                self.view.removeItem(item)
            except Exception:
                pass
        self.current_items.clear()

    def _load_data_and_draw(self):
        try:
            self.stop_animation(reset_scene=False)
            self.status_label.setText("DB에서 제외 인덱스를 읽는 중...")
            QtWidgets.QApplication.processEvents()

            if not os.path.exists(DB_PATH):
                raise FileNotFoundError(f"DB 파일이 없습니다: {DB_PATH}")

            self.excluded_rows = load_excluded_index_rows()
            self.cube_size, self.main_points, self.bonus_points = build_point_cloud(self.excluded_rows)
            self.main_seq = build_main_sequence_points_3d(self.excluded_rows, TOTAL_COMBINATIONS)

            main_count = sum(1 for _, _, t in self.excluded_rows if t == "main")
            bonus_count = len(self.excluded_rows) - main_count
            unique_excluded = len({idx for _, idx, _ in self.excluded_rows})

            self.summary_label.setText(
                f"전체 조합: {TOTAL_COMBINATIONS:,}개    "
                f"큐브 한 변: {self.cube_size}    "
                f"실제 당첨(main): {main_count:,}개    "
                f"보너스 제외: {bonus_count:,}개    "
                f"중복 제거 후 제외 인덱스: {unique_excluded:,}개"
            )

            self.current_prediction = None
            self.predict_label.setText("다음 위치 예측: 준비 전")

            self.redraw()
            self.status_label.setText("완료")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"3D 큐브 데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")

    def redraw(self):
        try:
            point_alpha = self.alpha_slider.value() / 100.0
            link_alpha = self.link_alpha_slider.value() / 100.0
            distance_threshold = float(self.distance_slider.value())

            self.alpha_value_label.setText(f"{point_alpha:.2f}")
            self.link_alpha_value_label.setText(f"{link_alpha:.2f}")
            self.distance_value_label.setText(f"{distance_threshold:.0f}")

            self.status_label.setText("렌더링 중...")
            QtWidgets.QApplication.processEvents()

            self._setup_static_scene()
            self._clear_dynamic_items()

            mode = self.mode_combo.currentText()
            if mode == "포인트 모드":
                self._draw_points_mode(point_alpha, link_alpha, distance_threshold)
            else:
                self._draw_density_mode(point_alpha)

            self._draw_prediction_marker()
            self.status_label.setText("완료")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"3D 큐브를 그리는 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")

    def _draw_cube_outline(self, cube_size):
        half = cube_size / 2.0
        corners = np.array([
            [-half, -half, -half],
            [ half, -half, -half],
            [ half,  half, -half],
            [-half,  half, -half],
            [-half, -half,  half],
            [ half, -half,  half],
            [ half,  half,  half],
            [-half,  half,  half],
        ], dtype=np.float32)

        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]

        for a, b in edges:
            pts = np.array([corners[a], corners[b]], dtype=np.float32)
            line = gl.GLLinePlotItem(
                pos=pts,
                color=(0.3, 0.3, 0.3, 0.7),
                width=1,
                antialias=True,
                mode="lines"
            )
            self.view.addItem(line)
            self.current_items.append(line)

    def _add_neighbor_links(self, points: np.ndarray, color_rgba, distance_threshold: float):
        if not self.link_checkbox.isChecked():
            return

        starts, ends = build_neighbor_edges(
            points,
            distance_threshold=distance_threshold,
            max_points_for_edges=1200,
            max_edges=6000
        )

        if len(starts) == 0:
            return

        for i in range(len(starts)):
            seg = np.array([starts[i], ends[i]], dtype=np.float32)
            line = gl.GLLinePlotItem(
                pos=seg,
                color=color_rgba,
                width=1,
                antialias=True,
                mode="lines"
            )
            self.view.addItem(line)
            self.current_items.append(line)

    def _draw_points_mode(self, point_alpha: float, link_alpha: float, distance_threshold: float):
        cube_size = self.cube_size
        self._draw_cube_outline(cube_size)

        main_pts = center_points(self.main_points, cube_size)
        bonus_pts = center_points(self.bonus_points, cube_size)

        if len(bonus_pts) > 0:
            bonus_colors = np.zeros((len(bonus_pts), 4), dtype=np.float32)
            bonus_colors[:, 0] = 1.0
            bonus_colors[:, 1] = 0.55
            bonus_colors[:, 2] = 0.05
            bonus_colors[:, 3] = point_alpha

            bonus_item = gl.GLScatterPlotItem(
                pos=bonus_pts,
                color=bonus_colors,
                size=4.5,
                pxMode=True
            )
            self.view.addItem(bonus_item)
            self.current_items.append(bonus_item)

            self._add_neighbor_links(
                bonus_pts,
                color_rgba=(1.0, 0.55, 0.05, link_alpha),
                distance_threshold=distance_threshold
            )

        if len(main_pts) > 0:
            main_alpha = min(1.0, point_alpha * 1.8)

            main_colors = np.zeros((len(main_pts), 4), dtype=np.float32)
            main_colors[:, 0] = 1.0
            main_colors[:, 1] = 0.1
            main_colors[:, 2] = 0.1
            main_colors[:, 3] = main_alpha

            main_item = gl.GLScatterPlotItem(
                pos=main_pts,
                color=main_colors,
                size=8.0,
                pxMode=True
            )
            self.view.addItem(main_item)
            self.current_items.append(main_item)

            self._add_neighbor_links(
                main_pts,
                color_rgba=(1.0, 0.15, 0.15, min(1.0, link_alpha * 1.3)),
                distance_threshold=distance_threshold
            )

    def _draw_density_mode(self, point_alpha: float):
        bin_size = int(self.bin_combo.currentText())
        max_cells = int(self.max_cells_combo.currentText())

        cube_size, pts, vals = build_density_cloud(
            self.excluded_rows,
            bin_size=bin_size,
            max_cells=max_cells
        )

        self._draw_cube_outline(cube_size)

        if len(pts) == 0:
            return

        pts = center_points(pts, cube_size)

        vmin = float(vals.min())
        vmax = float(vals.max()) if float(vals.max()) > vmin else vmin + 1.0
        norm = (vals - vmin) / (vmax - vmin)

        colors = np.zeros((len(pts), 4), dtype=np.float32)
        colors[:, 0] = 1.0
        colors[:, 1] = 0.15 + norm * 0.85
        colors[:, 2] = 0.05
        colors[:, 3] = (0.08 + norm * 0.45) * max(0.15, point_alpha)

        sizes = 6.0 + norm * 18.0

        density_item = gl.GLScatterPlotItem(
            pos=pts,
            color=colors,
            size=sizes,
            pxMode=True
        )
        self.view.addItem(density_item)
        self.current_items.append(density_item)

    def _draw_prediction_marker(self):
        if self.current_prediction is None:
            return

        if self.mode_combo.currentText() != "포인트 모드":
            return

        px = self.current_prediction["predicted_x"] - (self.cube_size / 2.0)
        py = self.current_prediction["predicted_y"] - (self.cube_size / 2.0)
        pz = self.current_prediction["predicted_z"] - (self.cube_size / 2.0)

        pos = np.array([[px, py, pz]], dtype=np.float32)
        color = np.array([[0.0, 1.0, 1.0, 1.0]], dtype=np.float32)

        self.prediction_item = gl.GLScatterPlotItem(
            pos=pos,
            color=color,
            size=14.0,
            pxMode=True
        )
        self.view.addItem(self.prediction_item)
        self.current_items.append(self.prediction_item)

    def animate_last_points(self):
        try:
            if self.mode_combo.currentText() != "포인트 모드":
                QtWidgets.QMessageBox.information(self, "안내", "애니메이션은 포인트 모드에서 확인할 수 있습니다.")
                return

            self.stop_animation(reset_scene=True)

            count = max(1, int(self.animate_count_spin.value()))
            seq = self.main_seq[-count:] if len(self.main_seq) >= count else self.main_seq[:]

            if len(seq) == 0:
                QtWidgets.QMessageBox.information(self, "안내", "애니메이션할 main 데이터가 없습니다.")
                return

            self.animation_points = seq
            self.animation_index = 0
            self.animation_running = True

            self.animation_timer = QtCore.QTimer(self)
            self.animation_timer.timeout.connect(self._animate_step_3d)
            self.animation_timer.start(60)

            self.status_label.setText(f"애니메이션 실행 중... 최근 {len(seq)}개")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"애니메이션 시작 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")

    def _animate_step_3d(self):
        if not self.animation_running:
            return

        self.animation_index += 1

        if self.animation_index > len(self.animation_points):
            self.animation_running = False

            if self.animation_timer is not None:
                try:
                    self.animation_timer.stop()
                except Exception:
                    pass
                self.animation_timer = None

            self.status_label.setText("애니메이션 완료 (마지막 경로 유지)")
            return

        sub = self.animation_points[:self.animation_index]

        pts = np.array(
            [[p["x"], p["y"], p["z"]] for p in sub],
            dtype=np.float32
        )
        pts = center_points(pts, self.cube_size)

        if self.animation_line_item is not None:
            try:
                self.view.removeItem(self.animation_line_item)
            except Exception:
                pass

        self.animation_line_item = gl.GLLinePlotItem(
            pos=pts,
            color=(0.0, 1.0, 1.0, 0.95),
            width=2,
            antialias=True,
            mode="line_strip"
        )
        self.view.addItem(self.animation_line_item)

        if self.animation_head_item is not None:
            try:
                self.view.removeItem(self.animation_head_item)
            except Exception:
                pass

        head_pos = np.array([pts[-1]], dtype=np.float32)
        head_color = np.array([[0.0, 1.0, 1.0, 1.0]], dtype=np.float32)

        self.animation_head_item = gl.GLScatterPlotItem(
            pos=head_pos,
            color=head_color,
            size=16.0,
            pxMode=True
        )
        self.view.addItem(self.animation_head_item)

        last = sub[-1]
        self.status_label.setText(
            f"애니메이션 실행 중... 회차 {last['draw_no']} / 인덱스 {last['comb_idx']:,} / {self.animation_index}/{len(self.animation_points)}"
        )

    def stop_animation(self, reset_scene=True, clear_items=True):
        self.animation_running = False
        self.animation_points = []
        self.animation_index = 0

        if self.animation_timer is not None:
            try:
                self.animation_timer.stop()
            except Exception:
                pass
            self.animation_timer = None

        if clear_items:
            if self.animation_line_item is not None:
                try:
                    self.view.removeItem(self.animation_line_item)
                except Exception:
                    pass
                self.animation_line_item = None

            if self.animation_head_item is not None:
                try:
                    self.view.removeItem(self.animation_head_item)
                except Exception:
                    pass
                self.animation_head_item = None

        if reset_scene:
            self.redraw()

    def predict_next_position(self):
        try:
            self.current_prediction = predict_next_main_index_3d(
                self.main_seq,
                total_count=TOTAL_COMBINATIONS,
                randomness=0.85,
                candidates=12
            )

            if not self.current_prediction:
                QtWidgets.QMessageBox.information(self, "안내", "예측에 필요한 main 데이터가 부족합니다.")
                return

            pred_idx = self.current_prediction["predicted_idx"]
            base_draw = self.current_prediction["base_draw_no"]
            base_idx = self.current_prediction["base_idx"]
            pred_numbers = self.current_prediction["predicted_numbers"]

            num_text = ", ".join(str(n) for n in pred_numbers)
            pyperclip.copy(num_text)

            self.predict_label.setText(
                f"다음 위치 예측: idx {pred_idx:,} / 번호 [{num_text}] / 기준 회차 {base_draw}"
            )

            self.redraw()

            QtWidgets.QMessageBox.information(
                self,
                "다음 위치 예측",
                (
                    f"최근 main 위치 패턴 기반 3D 휴리스틱 예측 결과\n\n"
                    f"기준 마지막 회차: {base_draw}\n"
                    f"기준 마지막 main 인덱스: {base_idx:,}\n"
                    f"예측 다음 인덱스: {pred_idx:,}\n"
                    f"예측 위치: ({self.current_prediction['predicted_x']:.0f}, "
                    f"{self.current_prediction['predicted_y']:.0f}, "
                    f"{self.current_prediction['predicted_z']:.0f})\n"
                    f"예측 번호 조합: {pred_numbers}\n\n"
                    f"이 값은 시각 패턴 + 랜덤성을 섞은 연출용 예측값이며\n"
                    f"실제 당첨을 보장하지 않습니다."
                )
            )

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"다음 위치 예측 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")


def run_3d_cube_pg():
    app = QtWidgets.QApplication.instance()
    owns_app = app is None

    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    pg.setConfigOptions(antialias=True)

    window = Combination3DCubePGWindow()
    window.show()

    if owns_app:
        sys.exit(app.exec())


if __name__ == "__main__":
    run_3d_cube_pg()