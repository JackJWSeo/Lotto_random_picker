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


def fibonacci_sphere_point(index_1based: int, total_count: int, radius: float):
    if total_count <= 1:
        return 0.0, radius, 0.0

    i = index_1based - 1
    n = total_count

    y = 1.0 - (2.0 * i) / (n - 1)
    r = max(0.0, math.sqrt(max(0.0, 1.0 - y * y)))

    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    theta = i * golden_angle

    x = math.cos(theta) * r
    z = math.sin(theta) * r

    return x * radius, y * radius, z * radius


def build_background_points(total_count: int, radius: float, step: int):
    step = max(1, int(step))

    points = []
    for idx in range(1, total_count + 1, step):
        points.append(fibonacci_sphere_point(idx, total_count, radius))

    if total_count > 0 and (total_count - 1) % step != 0:
        points.append(fibonacci_sphere_point(total_count, total_count, radius))

    if not points:
        return np.empty((0, 3), dtype=np.float32)

    return np.array(points, dtype=np.float32)


def build_highlight_points(excluded_rows, total_count: int, radius: float, radius_offset: float = 0.0):
    index_type_map = {}

    for _draw_no, comb_idx, comb_type in excluded_rows:
        if comb_idx < 1 or comb_idx > total_count:
            continue

        if comb_type == "main":
            index_type_map[comb_idx] = "main"
        else:
            if index_type_map.get(comb_idx) != "main":
                index_type_map[comb_idx] = "bonus"

    main_pts = []
    bonus_pts = []
    rr = radius + radius_offset

    for idx, point_type in sorted(index_type_map.items()):
        x, y, z = fibonacci_sphere_point(idx, total_count, rr)
        if point_type == "main":
            main_pts.append((x, y, z))
        else:
            bonus_pts.append((x, y, z))

    main_arr = np.array(main_pts, dtype=np.float32) if main_pts else np.empty((0, 3), dtype=np.float32)
    bonus_arr = np.array(bonus_pts, dtype=np.float32) if bonus_pts else np.empty((0, 3), dtype=np.float32)

    return main_arr, bonus_arr, index_type_map


def build_main_sequence_points_sphere(excluded_rows, total_count: int, radius: float, radius_offset: float = 0.0):
    seq = []
    rr = radius + radius_offset

    for draw_no, comb_idx, comb_type in excluded_rows:
        if comb_type != "main":
            continue
        if comb_idx < 1 or comb_idx > total_count:
            continue

        x, y, z = fibonacci_sphere_point(comb_idx, total_count, rr)
        seq.append({
            "draw_no": draw_no,
            "comb_idx": comb_idx,
            "x": float(x),
            "y": float(y),
            "z": float(z),
        })

    seq.sort(key=lambda item: (item["draw_no"], item["comb_idx"]))
    return seq


def downsample_points(points: np.ndarray, max_points: int):
    if len(points) <= max_points:
        return points
    idx = np.linspace(0, len(points) - 1, max_points, dtype=np.int32)
    return points[idx]


def build_neighbor_edges(points: np.ndarray, distance_threshold: float, max_points_for_edges: int = 1200, max_edges: int = 2500):
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


def normalize_vector(v):
    norm = np.linalg.norm(v)
    if norm <= 1e-12:
        return v
    return v / norm


def find_nearest_index_on_sphere(pred_xyz, total_count: int, radius: float, center_idx=None, search_window=6000):
    if total_count <= 0:
        return None

    if center_idx is None:
        center_idx = 1

    start_idx = max(1, center_idx - search_window)
    end_idx = min(total_count, center_idx + search_window)

    pred_dir = normalize_vector(np.array(pred_xyz, dtype=np.float64))

    best_idx = None
    best_score = None

    for idx in range(start_idx, end_idx + 1):
        x, y, z = fibonacci_sphere_point(idx, total_count, radius)
        cand = np.array([x, y, z], dtype=np.float64)
        cand_dir = normalize_vector(cand)

        dot = float(np.dot(pred_dir, cand_dir))
        score = 1.0 - dot

        if best_score is None or score < best_score:
            best_score = score
            best_idx = idx

    return best_idx


def predict_next_main_index_sphere(main_seq, total_count: int, radius: float, randomness=0.85, candidates=12):
    if len(main_seq) < 6:
        return None

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
        base_scale = radius * 0.05

    last_pt = pts[-1]
    last_idx = recent[-1]["comb_idx"]

    candidate_results = []

    for _ in range(max(3, int(candidates))):
        noise_main = np.random.normal(0.0, base_scale * 0.45 * randomness, size=3)
        noise_turn = np.random.normal(0.0, base_scale * 0.20 * randomness, size=3)

        predicted_xyz = (
            last_pt
            + (0.18 * mean_delta)
            + (0.42 * weighted_delta)
            + (0.20 * last_delta)
            + (0.12 * turn_delta)
            + noise_main
            + noise_turn
        )

        predicted_xyz = normalize_vector(predicted_xyz) * radius

        predicted_idx = find_nearest_index_on_sphere(
            predicted_xyz,
            total_count=total_count,
            radius=radius,
            center_idx=last_idx,
            search_window=6000
        )

        if predicted_idx is None:
            continue

        px, py, pz = fibonacci_sphere_point(predicted_idx, total_count, radius)
        pred_point = np.array([px, py, pz], dtype=np.float64)

        fit_dist2 = float(np.sum((pred_point - predicted_xyz) ** 2))
        idx_gap_penalty = 0.0 if predicted_idx != last_idx else (base_scale * 8.0)
        score = fit_dist2 + idx_gap_penalty

        candidate_results.append({
            "score": score,
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


class LottoSphereOpenGLWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.default_radius = 120.0
        self.default_background_step = max(1, TOTAL_COMBINATIONS // 8000)
        self.default_background_size = 2.0
        self.default_highlight_size = 8.0
        self.default_link_distance = 12
        self.default_animate_count = 100
        self.default_sphere_alpha = 0.28

        self.radius = self.default_radius

        self.highlight_radius_offset = 0.7
        self.sequence_radius_offset = 0.9
        self.prediction_radius_offset = 1.2

        self.setWindowTitle("GPU 3D 로또 구체 표면 시각화")
        self.resize(1540, 1040)

        self.excluded_rows = []

        self.background_points = np.empty((0, 3), dtype=np.float32)
        self.main_points = np.empty((0, 3), dtype=np.float32)
        self.bonus_points = np.empty((0, 3), dtype=np.float32)
        self.main_seq = []
        self.index_type_map = {}

        self.current_items = []

        self.animation_timer = None
        self.animation_running = False
        self.animation_points = []
        self.animation_index = 0

        self.animation_head_item = None
        self.animation_mint_points_item = None
        self.animation_segments = []

        self.prediction_item = None
        self.current_prediction = None

        self._create_ui()
        self._load_data_and_draw()

    def _create_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        top_row = QtWidgets.QHBoxLayout()
        root.addLayout(top_row)

        title = QtWidgets.QLabel("전체 로또 조합 인덱스를 3D 구체 표면에 펼친 OpenGL 시각화")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        top_row.addWidget(title)
        top_row.addStretch(1)

        refresh_btn = QtWidgets.QPushButton("새로고침")
        refresh_btn.clicked.connect(self._load_data_and_draw)
        top_row.addWidget(refresh_btn)

        control_row = QtWidgets.QHBoxLayout()
        root.addLayout(control_row)

        control_row.addWidget(QtWidgets.QLabel("구 반지름"))
        self.radius_spin = QtWidgets.QDoubleSpinBox()
        self.radius_spin.setRange(20.0, 500.0)
        self.radius_spin.setSingleStep(5.0)
        self.radius_spin.setValue(self.radius)
        self.radius_spin.setFixedWidth(90)
        self.radius_spin.valueChanged.connect(self.redraw)
        control_row.addWidget(self.radius_spin)

        control_row.addSpacing(16)

        self.show_background_checkbox = QtWidgets.QCheckBox("전체 배경 인덱스 표시")
        self.show_background_checkbox.setChecked(True)
        self.show_background_checkbox.stateChanged.connect(self.redraw)
        control_row.addWidget(self.show_background_checkbox)

        control_row.addWidget(QtWidgets.QLabel("배경 간격"))
        self.background_step_spin = QtWidgets.QSpinBox()
        self.background_step_spin.setRange(1, max(1, TOTAL_COMBINATIONS))
        self.background_step_spin.setSingleStep(100)
        self.background_step_spin.setValue(self.default_background_step)
        self.background_step_spin.setFixedWidth(100)
        self.background_step_spin.valueChanged.connect(self.redraw)
        control_row.addWidget(self.background_step_spin)

        control_row.addWidget(QtWidgets.QLabel("배경 점 크기"))
        self.background_size_spin = QtWidgets.QDoubleSpinBox()
        self.background_size_spin.setRange(1.0, 20.0)
        self.background_size_spin.setSingleStep(0.5)
        self.background_size_spin.setValue(self.default_background_size)
        self.background_size_spin.setFixedWidth(90)
        self.background_size_spin.valueChanged.connect(self.redraw)
        control_row.addWidget(self.background_size_spin)

        control_row.addSpacing(16)

        control_row.addWidget(QtWidgets.QLabel("강조 점 크기"))
        self.highlight_size_spin = QtWidgets.QDoubleSpinBox()
        self.highlight_size_spin.setRange(2.0, 40.0)
        self.highlight_size_spin.setSingleStep(1.0)
        self.highlight_size_spin.setValue(self.default_highlight_size)
        self.highlight_size_spin.setFixedWidth(90)
        self.highlight_size_spin.valueChanged.connect(self.redraw)
        control_row.addWidget(self.highlight_size_spin)

        control_row.addSpacing(16)

        self.link_checkbox = QtWidgets.QCheckBox("인접 점 연결")
        self.link_checkbox.setChecked(False)
        self.link_checkbox.stateChanged.connect(self.redraw)
        control_row.addWidget(self.link_checkbox)

        control_row.addWidget(QtWidgets.QLabel("인접 거리"))
        self.distance_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.distance_slider.setMinimum(1)
        self.distance_slider.setMaximum(80)
        self.distance_slider.setValue(self.default_link_distance)
        self.distance_slider.setFixedWidth(160)
        self.distance_slider.valueChanged.connect(self.redraw)
        control_row.addWidget(self.distance_slider)

        self.distance_value_label = QtWidgets.QLabel(str(self.default_link_distance))
        control_row.addWidget(self.distance_value_label)

        control_row.addSpacing(16)

        self.show_bonus_checkbox = QtWidgets.QCheckBox("보너스 조합 점 표시")
        self.show_bonus_checkbox.setChecked(True)
        self.show_bonus_checkbox.stateChanged.connect(self.redraw)
        control_row.addWidget(self.show_bonus_checkbox)

        control_row.addStretch(1)

        sphere_row = QtWidgets.QHBoxLayout()
        root.addLayout(sphere_row)

        sphere_row.addWidget(QtWidgets.QLabel("구체 알파"))
        self.sphere_alpha_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sphere_alpha_slider.setMinimum(0)
        self.sphere_alpha_slider.setMaximum(100)
        self.sphere_alpha_slider.setValue(int(self.default_sphere_alpha * 100))
        self.sphere_alpha_slider.setFixedWidth(180)
        self.sphere_alpha_slider.valueChanged.connect(self.redraw)
        sphere_row.addWidget(self.sphere_alpha_slider)

        self.sphere_alpha_label = QtWidgets.QLabel(f"{self.default_sphere_alpha:.2f}")
        sphere_row.addWidget(self.sphere_alpha_label)

        self.show_sphere_fill_checkbox = QtWidgets.QCheckBox("검은 반투명 구 표시")
        self.show_sphere_fill_checkbox.setChecked(True)
        self.show_sphere_fill_checkbox.stateChanged.connect(self.redraw)
        sphere_row.addWidget(self.show_sphere_fill_checkbox)

        sphere_row.addStretch(1)

        anim_row = QtWidgets.QHBoxLayout()
        root.addLayout(anim_row)

        anim_row.addWidget(QtWidgets.QLabel("애니메이션 개수"))
        self.animate_count_spin = QtWidgets.QSpinBox()
        self.animate_count_spin.setRange(10, 500)
        self.animate_count_spin.setSingleStep(10)
        self.animate_count_spin.setValue(self.default_animate_count)
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
        self.view.setMinimumHeight(640)
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

    def _reset_ui_to_defaults(self):
        self.radius_spin.setValue(self.default_radius)
        self.show_background_checkbox.setChecked(True)
        self.background_step_spin.setValue(self.default_background_step)
        self.background_size_spin.setValue(self.default_background_size)
        self.highlight_size_spin.setValue(self.default_highlight_size)

        self.link_checkbox.setChecked(False)
        self.distance_slider.setValue(self.default_link_distance)

        self.animate_count_spin.setValue(self.default_animate_count)
        self.show_bonus_checkbox.setChecked(True)

        self.sphere_alpha_slider.setValue(int(self.default_sphere_alpha * 100))
        self.show_sphere_fill_checkbox.setChecked(True)

        self.current_prediction = None
        self.predict_label.setText("다음 위치 예측: 준비 전")

    def _setup_static_scene(self):
        self.view.clear()
        self.current_items = []

        grid = gl.GLGridItem()
        grid.setSize(x=320, y=320, z=0)
        grid.setSpacing(x=20, y=20, z=20)
        grid.translate(0, 0, -160)
        self.view.addItem(grid)

        axis = gl.GLAxisItem()
        axis.setSize(140, 140, 140)
        self.view.addItem(axis)

        self.view.opts["distance"] = 420
        self.view.opts["elevation"] = 18
        self.view.opts["azimuth"] = 34
        self.view.opts["fov"] = 60
        self.view.opts["center"] = pg.Vector(0, 0, 0)

    def _remove_item_safe(self, item):
        if item is None:
            return None
        try:
            self.view.removeItem(item)
        except Exception:
            pass
        return None

    def _clear_dynamic_items(self):
        for item in self.current_items:
            try:
                self.view.removeItem(item)
            except Exception:
                pass
        self.current_items.clear()

        self.prediction_item = self._remove_item_safe(self.prediction_item)
        self.animation_head_item = self._remove_item_safe(self.animation_head_item)
        self.animation_mint_points_item = self._remove_item_safe(self.animation_mint_points_item)
        self._clear_animation_segments()

    def _clear_animation_segments(self):
        for seg in self.animation_segments:
            seg["item"] = self._remove_item_safe(seg.get("item"))
        self.animation_segments.clear()

    def _prepare_points(self):
        self.radius = float(self.radius_spin.value())

        self.background_points = build_background_points(
            TOTAL_COMBINATIONS,
            radius=self.radius,
            step=int(self.background_step_spin.value())
        )

        self.main_points, self.bonus_points, self.index_type_map = build_highlight_points(
            self.excluded_rows,
            TOTAL_COMBINATIONS,
            radius=self.radius,
            radius_offset=self.highlight_radius_offset
        )

        self.main_seq = build_main_sequence_points_sphere(
            self.excluded_rows,
            TOTAL_COMBINATIONS,
            radius=self.radius,
            radius_offset=self.sequence_radius_offset
        )

    def _load_data_and_draw(self):
        try:
            self.stop_animation(reset_scene=False)
            self._reset_ui_to_defaults()

            self.status_label.setText("DB에서 제외 인덱스를 읽는 중...")
            QtWidgets.QApplication.processEvents()

            if not os.path.exists(DB_PATH):
                raise FileNotFoundError(f"DB 파일이 없습니다: {DB_PATH}")

            self.excluded_rows = load_excluded_index_rows()
            self._prepare_points()

            main_count = sum(1 for _, _, t in self.excluded_rows if t == "main")
            bonus_count = len(self.excluded_rows) - main_count
            unique_excluded = len({idx for _, idx, _ in self.excluded_rows})

            bg_count = len(self.background_points) if self.show_background_checkbox.isChecked() else 0

            self.summary_label.setText(
                f"전체 조합: {TOTAL_COMBINATIONS:,}개    "
                f"구 반지름: {self.radius:.1f}    "
                f"배경 샘플 점: {bg_count:,}개    "
                f"실제 당첨(main): {main_count:,}개    "
                f"보너스 제외: {bonus_count:,}개    "
                f"중복 제거 후 제외 인덱스: {unique_excluded:,}개"
            )

            self.redraw()
            self.status_label.setText("완료")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"구체 데이터를 불러오는 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")

    def redraw(self):
        try:
            distance_threshold = float(self.distance_slider.value())
            self.distance_value_label.setText(f"{distance_threshold:.0f}")

            sphere_alpha = float(self.sphere_alpha_slider.value()) / 100.0
            self.sphere_alpha_label.setText(f"{sphere_alpha:.2f}")

            self.status_label.setText("렌더링 중...")
            QtWidgets.QApplication.processEvents()

            self._prepare_points()
            self._setup_static_scene()
            self._clear_dynamic_items()

            self._draw_sphere_outline()

            if self.show_background_checkbox.isChecked() and len(self.background_points) > 0:
                self._draw_background_points()

            if self.show_bonus_checkbox.isChecked():
                self._draw_bonus_points()

            self._draw_main_points()

            if self.link_checkbox.isChecked():
                self._draw_neighbor_links()

            self._draw_prediction_marker()

            self.status_label.setText("완료")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"구체를 그리는 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")

    def _draw_sphere_outline(self):
        md = gl.MeshData.sphere(rows=32, cols=48, radius=self.radius)
        sphere_alpha = float(self.sphere_alpha_slider.value()) / 100.0

        if self.show_sphere_fill_checkbox.isChecked() and sphere_alpha > 0.0:
            sphere_fill = gl.GLMeshItem(
                meshdata=md,
                smooth=True,
                drawFaces=True,
                drawEdges=False,
                color=(0.0, 0.0, 0.0, sphere_alpha)
            )
            sphere_fill.setGLOptions("translucent")
            self.view.addItem(sphere_fill)
            self.current_items.append(sphere_fill)

        sphere_edge = gl.GLMeshItem(
            meshdata=md,
            smooth=True,
            drawFaces=False,
            drawEdges=True,
            edgeColor=(0.30, 0.30, 0.34, 0.28)
        )
        sphere_edge.setGLOptions("translucent")
        self.view.addItem(sphere_edge)
        self.current_items.append(sphere_edge)

    def _draw_background_points(self):
        size = float(self.background_size_spin.value())
        pts = self.background_points

        colors = np.zeros((len(pts), 4), dtype=np.float32)
        colors[:, 0] = 0.78
        colors[:, 1] = 0.78
        colors[:, 2] = 0.78
        colors[:, 3] = 0.16

        item = gl.GLScatterPlotItem(
            pos=pts,
            color=colors,
            size=size,
            pxMode=True
        )
        item.setGLOptions("translucent")
        self.view.addItem(item)
        self.current_items.append(item)

    def _draw_bonus_points(self):
        if len(self.bonus_points) == 0:
            return

        size = float(self.highlight_size_spin.value())

        colors = np.zeros((len(self.bonus_points), 4), dtype=np.float32)
        colors[:, 0] = 1.0
        colors[:, 1] = 0.60
        colors[:, 2] = 0.05
        colors[:, 3] = 0.88

        item = gl.GLScatterPlotItem(
            pos=self.bonus_points,
            color=colors,
            size=size,
            pxMode=True
        )
        item.setGLOptions("translucent")
        self.view.addItem(item)
        self.current_items.append(item)

    def _draw_main_points(self):
        if len(self.main_points) == 0:
            return

        size = float(self.highlight_size_spin.value()) * 1.2

        colors = np.zeros((len(self.main_points), 4), dtype=np.float32)
        colors[:, 0] = 1.0
        colors[:, 1] = 0.12
        colors[:, 2] = 0.12
        colors[:, 3] = 0.95

        item = gl.GLScatterPlotItem(
            pos=self.main_points,
            color=colors,
            size=size,
            pxMode=True
        )
        item.setGLOptions("translucent")
        self.view.addItem(item)
        self.current_items.append(item)

    def _draw_neighbor_links(self):
        distance_threshold = float(self.distance_slider.value())

        if self.show_bonus_checkbox.isChecked() and len(self.bonus_points) > 0:
            starts, ends = build_neighbor_edges(
                self.bonus_points,
                distance_threshold=distance_threshold,
                max_points_for_edges=1200,
                max_edges=2500
            )
            for i in range(len(starts)):
                seg = np.array([starts[i], ends[i]], dtype=np.float32)
                line = gl.GLLinePlotItem(
                    pos=seg,
                    color=(1.0, 0.55, 0.08, 0.16),
                    width=1,
                    antialias=True,
                    mode="lines"
                )
                line.setGLOptions("translucent")
                self.view.addItem(line)
                self.current_items.append(line)

        if len(self.main_points) > 0:
            starts, ends = build_neighbor_edges(
                self.main_points,
                distance_threshold=distance_threshold,
                max_points_for_edges=1200,
                max_edges=2500
            )
            for i in range(len(starts)):
                seg = np.array([starts[i], ends[i]], dtype=np.float32)
                line = gl.GLLinePlotItem(
                    pos=seg,
                    color=(1.0, 0.18, 0.18, 0.22),
                    width=1,
                    antialias=True,
                    mode="lines"
                )
                line.setGLOptions("translucent")
                self.view.addItem(line)
                self.current_items.append(line)

    def _draw_prediction_marker(self):
        self.prediction_item = self._remove_item_safe(self.prediction_item)

        if self.current_prediction is None:
            return

        p = np.array([
            self.current_prediction["predicted_x"],
            self.current_prediction["predicted_y"],
            self.current_prediction["predicted_z"]
        ], dtype=np.float32)

        norm = np.linalg.norm(p)
        if norm > 1e-8:
            p = p / norm * (self.radius + self.prediction_radius_offset)

        pos = np.array([p], dtype=np.float32)
        color = np.array([[0.0, 1.0, 1.0, 1.0]], dtype=np.float32)

        self.prediction_item = gl.GLScatterPlotItem(
            pos=pos,
            color=color,
            size=max(12.0, float(self.highlight_size_spin.value()) * 1.8),
            pxMode=True
        )
        self.prediction_item.setGLOptions("translucent")
        self.view.addItem(self.prediction_item)

    def _rebuild_animation_mint_points(self, pts: np.ndarray):
        self.animation_mint_points_item = self._remove_item_safe(self.animation_mint_points_item)

        if len(pts) <= 1:
            return

        trace_pts = pts[:-1]
        trace_colors = np.zeros((len(trace_pts), 4), dtype=np.float32)
        trace_colors[:, 0] = 0.15
        trace_colors[:, 1] = 0.95
        trace_colors[:, 2] = 0.75
        trace_colors[:, 3] = 0.92

        self.animation_mint_points_item = gl.GLScatterPlotItem(
            pos=trace_pts,
            color=trace_colors,
            size=max(8.0, float(self.highlight_size_spin.value()) * 1.25),
            pxMode=True
        )
        self.animation_mint_points_item.setGLOptions("translucent")
        self.view.addItem(self.animation_mint_points_item)

    def _add_animation_segment(self, p1, p2):
        seg_pos = np.array([p1, p2], dtype=np.float32)
        item = gl.GLLinePlotItem(
            pos=seg_pos,
            color=(0.0, 1.0, 1.0, 0.95),
            width=2,
            antialias=True,
            mode="lines"
        )
        item.setGLOptions("translucent")
        self.view.addItem(item)

        self.animation_segments.append({
            "pos": seg_pos,
            "item": item,
            "alpha": 0.95,
            "age": 0,
            "fading": False,
        })

    def _update_animation_segments(self, force_all_fade=False):
        alive = []

        for seg in self.animation_segments:
            seg["age"] += 1

            if force_all_fade:
                seg["fading"] = True
            elif seg["age"] >= 3:
                seg["fading"] = True

            if seg["fading"]:
                seg["alpha"] -= 0.16

            if seg["alpha"] <= 0.0:
                seg["item"] = self._remove_item_safe(seg["item"])
                continue

            seg["item"] = self._remove_item_safe(seg["item"])
            seg["item"] = gl.GLLinePlotItem(
                pos=seg["pos"],
                color=(0.0, 1.0, 1.0, float(max(0.0, min(1.0, seg["alpha"])))),
                width=2,
                antialias=True,
                mode="lines"
            )
            seg["item"].setGLOptions("translucent")
            self.view.addItem(seg["item"])
            alive.append(seg)

        self.animation_segments = alive

    def animate_last_points(self):
        try:
            self.stop_animation(reset_scene=True)

            count = max(1, int(self.animate_count_spin.value()))
            seq = self.main_seq[-count:] if len(self.main_seq) >= count else self.main_seq[:]

            if len(seq) == 0:
                QtWidgets.QMessageBox.information(self, "안내", "애니메이션할 main 데이터가 없습니다.")
                return

            self.animation_points = seq
            self.animation_index = 0
            self.animation_running = True
            self.animation_head_item = None
            self.animation_mint_points_item = None
            self._clear_animation_segments()

            self.animation_timer = QtCore.QTimer(self)
            self.animation_timer.timeout.connect(self._animate_step_3d)
            self.animation_timer.start(60)

            self.status_label.setText(f"애니메이션 실행 중... 최근 {len(seq)}개")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"애니메이션 시작 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")

    def _animate_step_3d(self):
        if not self.animation_running and not self.animation_segments:
            return

        if self.animation_running:
            self.animation_index += 1

            if self.animation_index > len(self.animation_points):
                self.animation_running = False
            else:
                sub = self.animation_points[:self.animation_index]
                pts = np.array([[p["x"], p["y"], p["z"]] for p in sub], dtype=np.float32)

                self._rebuild_animation_mint_points(pts)

                if len(pts) >= 2:
                    p1 = pts[-2]
                    p2 = pts[-1]
                    self._add_animation_segment(p1, p2)

                self.animation_head_item = self._remove_item_safe(self.animation_head_item)

                head_pos = np.array([pts[-1]], dtype=np.float32)
                head_color = np.array([[0.0, 1.0, 1.0, 1.0]], dtype=np.float32)

                self.animation_head_item = gl.GLScatterPlotItem(
                    pos=head_pos,
                    color=head_color,
                    size=max(14.0, float(self.highlight_size_spin.value()) * 2.0),
                    pxMode=True
                )
                self.animation_head_item.setGLOptions("translucent")
                self.view.addItem(self.animation_head_item)

                last = sub[-1]
                self.status_label.setText(
                    f"애니메이션 실행 중... 회차 {last['draw_no']} / 인덱스 {last['comb_idx']:,} / {self.animation_index}/{len(self.animation_points)}"
                )

        if self.animation_running:
            self._update_animation_segments(force_all_fade=False)
        else:
            self._update_animation_segments(force_all_fade=True)

            self.animation_head_item = self._remove_item_safe(self.animation_head_item)

            if not self.animation_segments:
                if self.animation_timer is not None:
                    try:
                        self.animation_timer.stop()
                    except Exception:
                        pass
                    self.animation_timer = None

                self.status_label.setText("애니메이션 완료")
            else:
                self.status_label.setText("애니메이션 종료 후 선분 순차 페이드아웃 중...")

    def stop_animation(self, reset_scene=True):
        self.animation_running = False
        self.animation_points = []
        self.animation_index = 0

        if self.animation_timer is not None:
            try:
                self.animation_timer.stop()
            except Exception:
                pass
            self.animation_timer = None

        self.animation_head_item = self._remove_item_safe(self.animation_head_item)
        self.animation_mint_points_item = self._remove_item_safe(self.animation_mint_points_item)
        self._clear_animation_segments()

        if reset_scene:
            self.redraw()

    def predict_next_position(self):
        try:
            self._prepare_points()

            self.current_prediction = predict_next_main_index_sphere(
                self.main_seq,
                total_count=TOTAL_COMBINATIONS,
                radius=self.radius + self.sequence_radius_offset,
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
                    f"최근 main 위치 패턴 기반 구체 표면 휴리스틱 예측 결과\n\n"
                    f"기준 마지막 회차: {base_draw}\n"
                    f"기준 마지막 main 인덱스: {base_idx:,}\n"
                    f"예측 다음 인덱스: {pred_idx:,}\n"
                    f"예측 위치: ({self.current_prediction['predicted_x']:.2f}, "
                    f"{self.current_prediction['predicted_y']:.2f}, "
                    f"{self.current_prediction['predicted_z']:.2f})\n"
                    f"예측 번호 조합: {pred_numbers}\n\n"
                    f"이 값은 시각 패턴 + 랜덤성을 섞은 연출용 예측값이며\n"
                    f"실제 당첨을 보장하지 않습니다."
                )
            )

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "오류", f"다음 위치 예측 중 오류가 발생했습니다.\n{e}")
            self.status_label.setText("오류 발생")


def run_sphere_opengl():
    app = QtWidgets.QApplication.instance()
    owns_app = app is None

    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    pg.setConfigOptions(antialias=True)

    window = LottoSphereOpenGLWindow()
    window.show()

    if owns_app:
        sys.exit(app.exec())


if __name__ == "__main__":
    run_sphere_opengl()