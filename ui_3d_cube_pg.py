import math
import os
import sqlite3
import sys

os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"

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
    """
    점이 너무 많으면 연결선이 과도하게 많아져서 느려지므로
    일부 점만 사용해서 인접 점 연결선을 만든다.
    """
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


class Combination3DCubePGWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("GPU 3D 조합 큐브")
        self.resize(1450, 980)

        self.excluded_rows = []
        self.cube_size = 0
        self.main_points = np.empty((0, 3), dtype=np.float32)
        self.bonus_points = np.empty((0, 3), dtype=np.float32)

        self.current_items = []

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
            self.status_label.setText("DB에서 제외 인덱스를 읽는 중...")
            QtWidgets.QApplication.processEvents()

            if not os.path.exists(DB_PATH):
                raise FileNotFoundError(f"DB 파일이 없습니다: {DB_PATH}")

            self.excluded_rows = load_excluded_index_rows()
            self.cube_size, self.main_points, self.bonus_points = build_point_cloud(self.excluded_rows)

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