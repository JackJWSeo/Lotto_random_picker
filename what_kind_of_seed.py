import sys
import random
import math
import hashlib
from PySide6.QtGui import QTextCursor
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Callable, Tuple, Dict, Any, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QSpinBox
)

# =========================================================
# 프로젝트 연동
# =========================================================
from winning_service import get_all_winning_numbers

try:
    from lotto_generator import index_to_combination as project_index_to_combination
except ImportError:
    project_index_to_combination = None


# =========================================================
# 조합 역변환 fallback
# =========================================================
def nCk(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1
    k = min(k, n - k)
    result = 1
    for i in range(1, k + 1):
        result = result * (n - k + i) // i
    return result


def index_to_combination_lexicographic(index_value: int, n: int = 45, k: int = 6) -> List[int]:
    total = nCk(n, k)
    if index_value < 0 or index_value >= total:
        raise ValueError(f"index out of range: {index_value} (valid: 0 ~ {total - 1})")

    result = []
    remain = index_value
    start = 1

    for pos in range(k):
        for num in range(start, n + 1):
            count = nCk(n - num, k - pos - 1)
            if remain < count:
                result.append(num)
                start = num + 1
                break
            remain -= count

    return result


def index_to_numbers(index_value: int) -> List[int]:
    if project_index_to_combination is not None:
        nums = project_index_to_combination(index_value)
        return sorted(int(x) for x in nums)

    return index_to_combination_lexicographic(index_value - 1, 45, 6)


# =========================================================
# DB row -> 분석용 observed_draws 변환
# =========================================================
def extract_field(row: Any, key: str, index_map: Dict[str, int], default=None):
    if isinstance(row, dict):
        return row.get(key, default)

    if hasattr(row, "keys") and callable(row.keys):
        try:
            return row[key]
        except Exception:
            pass

    if isinstance(row, (list, tuple)):
        idx = index_map.get(key)
        if idx is not None and 0 <= idx < len(row):
            return row[idx]

    return default


def normalize_date(raw_date: Any) -> str:
    if raw_date is None:
        return ""

    s = str(raw_date).strip()

    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]

    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    if len(s) >= 10:
        maybe = s[:10]
        try:
            datetime.strptime(maybe, "%Y-%m-%d")
            return maybe
        except Exception:
            pass

    return s


def load_observed_draws_from_project_db() -> List[Dict[str, Any]]:
    rows = get_all_winning_numbers()
    observed_draws = []

    index_map = {
        "draw_no": 0,
        "draw_date": 1,
        "main_comb_idx": 2,
        "bonus": 3,
        "winner_count": 4,
        "prize_amount": 5,
        "updated_at": 6,
    }

    for row in rows:
        draw_no = extract_field(row, "draw_no", index_map)
        draw_date = extract_field(row, "draw_date", index_map)
        main_comb_idx = extract_field(row, "main_comb_idx", index_map)

        if draw_date is None or main_comb_idx is None:
            continue

        date_str = normalize_date(draw_date)
        numbers = index_to_numbers(int(main_comb_idx))

        if len(numbers) != 6:
            continue

        observed_draws.append({
            "draw_no": int(draw_no) if draw_no is not None else None,
            "date": date_str,
            "numbers": sorted(numbers),
            "index": int(main_comb_idx),
        })

    observed_draws.sort(key=lambda x: x["date"])
    return observed_draws


# =========================================================
# seed transform
# =========================================================
def to_datetime(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def seed_from_yyyymmdd(row: Dict[str, Any]) -> int:
    dt = to_datetime(row["date"])
    return int(dt.strftime("%Y%m%d"))


def seed_from_ordinal(row: Dict[str, Any]) -> int:
    dt = to_datetime(row["date"])
    return dt.toordinal()


def seed_from_unix_day(row: Dict[str, Any]) -> int:
    dt = to_datetime(row["date"]).replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) // 86400


def seed_from_unix_seconds_fixed_time(row: Dict[str, Any], hour: int = 20, minute: int = 0, second: int = 0) -> int:
    dt = to_datetime(row["date"]).replace(
        hour=hour, minute=minute, second=second, tzinfo=timezone.utc
    )
    return int(dt.timestamp())


def seed_mix_date_xor_draw(row: Dict[str, Any]) -> int:
    base = seed_from_unix_seconds_fixed_time(row, 20, 0, 0)
    draw_no = int(row.get("draw_no") or 0)
    return (base ^ draw_no) & 0xFFFFFFFF


def seed_mix_date_add_draw(row: Dict[str, Any]) -> int:
    base = seed_from_unix_seconds_fixed_time(row, 20, 0, 0)
    draw_no = int(row.get("draw_no") or 0)
    return (base + draw_no) & 0xFFFFFFFF


def seed_hash_date_draw(row: Dict[str, Any]) -> int:
    s = f"{row['date']}|{row.get('draw_no', 0)}"
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


SEED_TRANSFORMS: Dict[str, Callable[[Dict[str, Any]], int]] = {
    "yyyymmdd": seed_from_yyyymmdd,
    "ordinal": seed_from_ordinal,
    "unix_day": seed_from_unix_day,
    "unix_fixed_20h": lambda row: seed_from_unix_seconds_fixed_time(row, 20, 0, 0),
    "date_xor_draw": seed_mix_date_xor_draw,
    "date_add_draw": seed_mix_date_add_draw,
    "hash_date_draw": seed_hash_date_draw,
}

FUTURE_SAFE_SEED_NAMES = list(SEED_TRANSFORMS.keys())


# =========================================================
# RNG 후보
# =========================================================
class RNGBase:
    def randint(self, a: int, b: int) -> int:
        raise NotImplementedError


class PythonRandomRNG(RNGBase):
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def randint(self, a: int, b: int) -> int:
        return self.rng.randint(a, b)


class LCG32RNG(RNGBase):
    def __init__(self, seed: int, a: int = 1664525, c: int = 1013904223):
        self.state = seed & 0xFFFFFFFF
        self.a = a
        self.c = c
        self.mod = 2**32

    def next_u32(self) -> int:
        self.state = (self.a * self.state + self.c) % self.mod
        return self.state

    def randint(self, a: int, b: int) -> int:
        span = b - a + 1
        return a + (self.next_u32() % span)


class XorShift32RNG(RNGBase):
    def __init__(self, seed: int):
        seed &= 0xFFFFFFFF
        if seed == 0:
            seed = 2463534242
        self.state = seed

    def next_u32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state

    def randint(self, a: int, b: int) -> int:
        span = b - a + 1
        return a + (self.next_u32() % span)


RNG_FACTORIES: Dict[str, Callable[[int], RNGBase]] = {
    "python_random": lambda seed: PythonRandomRNG(seed),
    "lcg32": lambda seed: LCG32RNG(seed),
    "xorshift32": lambda seed: XorShift32RNG(seed),
}


# =========================================================
# 추첨 방식 후보
# =========================================================
def draw_unique_by_retry(rng: RNGBase, pool_size: int, pick_count: int, start_index: int = 1) -> List[int]:
    picked = set()
    while len(picked) < pick_count:
        n = rng.randint(start_index, start_index + pool_size - 1)
        picked.add(n)
    return sorted(picked)


def draw_by_shuffle(rng: RNGBase, pool_size: int, pick_count: int, start_index: int = 1) -> List[int]:
    arr = list(range(start_index, start_index + pool_size))
    for i in range(len(arr) - 1, 0, -1):
        j = rng.randint(0, i)
        arr[i], arr[j] = arr[j], arr[i]
    return sorted(arr[:pick_count])


DRAW_METHODS: Dict[str, Callable[[RNGBase, int, int, int], List[int]]] = {
    "unique_retry": draw_unique_by_retry,
    "shuffle_front": draw_by_shuffle,
}


# =========================================================
# 점수 함수
# =========================================================
def score_exact_match(pred: List[int], actual: List[int]) -> float:
    return 1.0 if pred == sorted(actual) else 0.0


def score_overlap(pred: List[int], actual: List[int]) -> float:
    return len(set(pred) & set(actual)) / max(1, len(actual))


def score_position_soft(pred: List[int], actual: List[int]) -> float:
    pred_sorted = sorted(pred)
    actual_sorted = sorted(actual)
    total = 0.0
    for x, y in zip(pred_sorted, actual_sorted):
        diff = abs(x - y)
        total += math.exp(-diff / 5.0)
    return total / len(actual_sorted)


def combined_score(pred: List[int], actual: List[int]) -> float:
    return (
        2.0 * score_exact_match(pred, actual) +
        1.0 * score_overlap(pred, actual) +
        0.5 * score_position_soft(pred, actual)
    )


# =========================================================
# 설정
# =========================================================
@dataclass
class SearchConfig:
    pool_size: int = 45
    pick_count: int = 6
    start_index: int = 1
    offset_min: int = -200
    offset_max: int = 200
    top_k: int = 10


# =========================================================
# 시뮬레이션
# =========================================================
def simulate_one_draw(
    row: Dict[str, Any],
    seed_transform_name: str,
    rng_name: str,
    draw_method_name: str,
    offset: int,
    config: SearchConfig,
) -> Tuple[int, List[int]]:
    base_seed = SEED_TRANSFORMS[seed_transform_name](row)
    seed = (base_seed + offset) & 0xFFFFFFFF

    rng = RNG_FACTORIES[rng_name](seed)
    draw_func = DRAW_METHODS[draw_method_name]
    picked = draw_func(rng, config.pool_size, config.pick_count, config.start_index)
    return seed, picked


def evaluate_candidate(
    observed_draws: List[Dict[str, Any]],
    seed_transform_name: str,
    rng_name: str,
    draw_method_name: str,
    offset: int,
    config: SearchConfig,
) -> Dict[str, Any]:
    total_score = 0.0
    exact_count = 0
    overlap_sum = 0.0
    details = []

    for row in observed_draws:
        actual = sorted(row["numbers"])

        seed, pred = simulate_one_draw(
            row=row,
            seed_transform_name=seed_transform_name,
            rng_name=rng_name,
            draw_method_name=draw_method_name,
            offset=offset,
            config=config,
        )

        s = combined_score(pred, actual)
        ov = score_overlap(pred, actual)
        ex = (pred == actual)

        total_score += s
        overlap_sum += ov
        exact_count += int(ex)

        details.append({
            "draw_no": row.get("draw_no"),
            "date": row["date"],
            "seed": seed,
            "stored_index": row.get("index"),
            "pred": pred,
            "actual": actual,
            "score": round(s, 6),
            "overlap": round(ov, 6),
            "exact": ex,
        })

    n = max(1, len(observed_draws))
    return {
        "seed_transform": seed_transform_name,
        "rng": rng_name,
        "draw_method": draw_method_name,
        "offset": offset,
        "avg_score": total_score / n,
        "avg_overlap": overlap_sum / n,
        "exact_count": exact_count,
        "details": details,
    }


def search_best_candidates(
    observed_draws: List[Dict[str, Any]],
    config: SearchConfig,
    log_callback: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    seed_transform_names = FUTURE_SAFE_SEED_NAMES
    rng_names = ["python_random", "lcg32", "xorshift32"]
    draw_method_names = ["unique_retry", "shuffle_front"]

    results = []
    total_cases = (
        len(seed_transform_names) *
        len(rng_names) *
        len(draw_method_names) *
        (config.offset_max - config.offset_min + 1)
    )
    done = 0

    for seed_t in seed_transform_names:
        for rng_name in rng_names:
            for draw_name in draw_method_names:
                for offset in range(config.offset_min, config.offset_max + 1):
                    result = evaluate_candidate(
                        observed_draws=observed_draws,
                        seed_transform_name=seed_t,
                        rng_name=rng_name,
                        draw_method_name=draw_name,
                        offset=offset,
                        config=config,
                    )
                    results.append(result)

                    done += 1
                    if log_callback and (done % 1000 == 0 or done == total_cases):
                        log_callback(f"Progress: {done}/{total_cases}")

    results.sort(
        key=lambda x: (x["exact_count"], x["avg_score"], x["avg_overlap"]),
        reverse=True
    )
    return results[:config.top_k]


# =========================================================
# 다음 회차 예측
# =========================================================
def infer_next_draw_date(last_date_str: str) -> str:
    dt = datetime.strptime(last_date_str, "%Y-%m-%d")
    next_dt = dt + timedelta(days=7)
    return next_dt.strftime("%Y-%m-%d")


def build_next_draw_row(last_row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "draw_no": int(last_row["draw_no"]) + 1,
        "date": infer_next_draw_date(last_row["date"]),
        "numbers": [],
        "index": None,
    }


def predict_next_numbers(
    observed_draws: List[Dict[str, Any]],
    candidate: Dict[str, Any],
    config: SearchConfig,
) -> Dict[str, Any]:
    last_row = observed_draws[-1]
    next_row = build_next_draw_row(last_row)

    seed, pred = simulate_one_draw(
        row=next_row,
        seed_transform_name=candidate["seed_transform"],
        rng_name=candidate["rng"],
        draw_method_name=candidate["draw_method"],
        offset=candidate["offset"],
        config=config,
    )

    return {
        "next_draw_no": next_row["draw_no"],
        "next_date": next_row["date"],
        "seed": seed,
        "predicted_numbers": pred,
        "seed_transform": candidate["seed_transform"],
        "rng": candidate["rng"],
        "draw_method": candidate["draw_method"],
        "offset": candidate["offset"],
        "exact_count": candidate["exact_count"],
        "avg_overlap": candidate["avg_overlap"],
        "avg_score": candidate["avg_score"],
    }


# =========================================================
# 문자열 출력 유틸
# =========================================================
def build_loaded_text(observed_draws: List[Dict[str, Any]], sample_count: int = 5) -> str:
    lines = [f"loaded draws = {len(observed_draws)}"]
    for row in observed_draws[:sample_count]:
        lines.append(
            f"draw_no={row.get('draw_no')} | "
            f"date={row['date']} | "
            f"index={row['index']} | "
            f"numbers={row['numbers']}"
        )
    return "\n".join(lines)


def build_top_results_text(results: List[Dict[str, Any]], top_n: int = 10) -> str:
    lines = []
    lines.append("=" * 110)
    lines.append("TOP 10 FUTURE-SAFE CANDIDATES")
    lines.append("=" * 110)

    for i, r in enumerate(results[:top_n], start=1):
        lines.append(
            f"[{i}] "
            f"seed_transform={r['seed_transform']:<18} | "
            f"rng={r['rng']:<14} | "
            f"draw={r['draw_method']:<12} | "
            f"offset={r['offset']:<6} | "
            f"exact={r['exact_count']:<3} | "
            f"avg_overlap={r['avg_overlap']:.4f} | "
            f"avg_score={r['avg_score']:.4f}"
        )

    lines.append("=" * 110)
    return "\n".join(lines)


def build_candidate_detail_text(candidate: Dict[str, Any], max_rows: int = 30) -> str:
    lines = []
    lines.append("-" * 110)
    lines.append("BEST FUTURE-SAFE CANDIDATE DETAILS")
    lines.append("-" * 110)
    lines.append(
        f"seed_transform={candidate['seed_transform']}, "
        f"rng={candidate['rng']}, "
        f"draw_method={candidate['draw_method']}, "
        f"offset={candidate['offset']}, "
        f"exact_count={candidate['exact_count']}, "
        f"avg_overlap={candidate['avg_overlap']:.4f}, "
        f"avg_score={candidate['avg_score']:.4f}"
    )
    lines.append("-" * 110)

    for d in candidate["details"][:max_rows]:
        lines.append(
            f"draw_no={d['draw_no']} | "
            f"date={d['date']} | "
            f"stored_index={d['stored_index']} | "
            f"seed={d['seed']} | "
            f"pred={d['pred']} | "
            f"actual={d['actual']} | "
            f"overlap={d['overlap']:.4f} | "
            f"exact={d['exact']}"
        )

    if len(candidate["details"]) > max_rows:
        lines.append(f"... ({len(candidate['details']) - max_rows} rows more)")
    lines.append("-" * 110)
    return "\n".join(lines)


def build_prediction_text(pred: Dict[str, Any], rank: int) -> str:
    lines = []
    lines.append("#" * 110)
    lines.append(f"NEXT DRAW PREDICTION FROM FUTURE-SAFE RANK {rank}")
    lines.append("#" * 110)
    lines.append(f"next_draw_no={pred['next_draw_no']}")
    lines.append(f"next_date={pred['next_date']}")
    lines.append(f"seed={pred['seed']}")
    lines.append(f"seed_transform={pred['seed_transform']}")
    lines.append(f"rng={pred['rng']}")
    lines.append(f"draw_method={pred['draw_method']}")
    lines.append(f"offset={pred['offset']}")
    lines.append(f"exact_count={pred['exact_count']}")
    lines.append(f"avg_overlap={pred['avg_overlap']:.4f}")
    lines.append(f"avg_score={pred['avg_score']:.4f}")
    lines.append(f"predicted_numbers={pred['predicted_numbers']}")
    lines.append("#" * 110)
    return "\n".join(lines)


def build_final_summary_text(predictions: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append("다음 회차 예측 결과")
    lines.append("")

    for i, pred in enumerate(predictions, start=1):
        nums = ", ".join(str(x) for x in pred["predicted_numbers"])
        lines.append(
            f"RANK {i}: {nums}    "
            f"({pred['seed_transform']} / {pred['rng']} / {pred['draw_method']} / offset={pred['offset']})"
        )

    return "\n".join(lines)


# =========================================================
# Worker
# =========================================================
class SearchWorker(QThread):
    log_signal = Signal(str)
    result_signal = Signal(str)
    final_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, config: SearchConfig):
        super().__init__()
        self.config = config

    def run(self):
        try:
            observed_draws = load_observed_draws_from_project_db()
            if not observed_draws:
                raise ValueError("위닝 DB에서 불러온 데이터가 없습니다.")

            self.log_signal.emit(build_loaded_text(observed_draws))

            results = search_best_candidates(
                observed_draws=observed_draws,
                config=self.config,
                log_callback=self.log_signal.emit,
            )

            self.log_signal.emit("")
            self.log_signal.emit(build_top_results_text(results, top_n=10))

            predictions = []

            if results:
                self.log_signal.emit("")
                self.log_signal.emit(build_candidate_detail_text(results[0], max_rows=30))

                top_predict_count = min(3, len(results))
                for i in range(top_predict_count):
                    pred = predict_next_numbers(observed_draws, results[i], self.config)
                    predictions.append(pred)

                    self.log_signal.emit("")
                    self.log_signal.emit(build_prediction_text(pred, i + 1))

                self.final_signal.emit(build_final_summary_text(predictions))
            else:
                self.final_signal.emit("결과가 없습니다.")

        except Exception as e:
            self.error_signal.emit(str(e))


# =========================================================
# UI
# =========================================================
class LottoPredictionWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lotto RNG Search Viewer")
        self.resize(1300, 850)

        self.worker = None

        main_layout = QVBoxLayout(self)

        control_layout = QHBoxLayout()

        self.offset_min_spin = QSpinBox()
        self.offset_min_spin.setRange(-100000, 100000)
        self.offset_min_spin.setValue(-200)

        self.offset_max_spin = QSpinBox()
        self.offset_max_spin.setRange(-100000, 100000)
        self.offset_max_spin.setValue(200)

        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(1, 100)
        self.topk_spin.setValue(10)

        self.run_button = QPushButton("탐색 시작")
        self.clear_button = QPushButton("로그 지우기")

        control_layout.addWidget(QLabel("Offset Min"))
        control_layout.addWidget(self.offset_min_spin)
        control_layout.addWidget(QLabel("Offset Max"))
        control_layout.addWidget(self.offset_max_spin)
        control_layout.addWidget(QLabel("Top K"))
        control_layout.addWidget(self.topk_spin)
        control_layout.addWidget(self.run_button)
        control_layout.addWidget(self.clear_button)

        main_layout.addLayout(control_layout)

        main_layout.addWidget(QLabel("진행 로그"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text, 4)

        main_layout.addWidget(QLabel("최종 결과"))
        self.final_text = QTextEdit()
        self.final_text.setReadOnly(True)
        self.final_text.setMaximumHeight(180)
        main_layout.addWidget(self.final_text, 1)

        self.status_label = QLabel("대기 중")
        self.status_label.setAlignment(Qt.AlignLeft)
        main_layout.addWidget(self.status_label)

        self.run_button.clicked.connect(self.start_search)
        self.clear_button.clicked.connect(self.clear_texts)

    def append_log(self, text: str):
        self.log_text.moveCursor(QTextCursor.End)
        self.log_text.insertPlainText(text + "\n")
        self.log_text.moveCursor(QTextCursor.End)

    def set_final(self, text: str):
        self.final_text.setPlainText(text)

    def clear_texts(self):
        self.log_text.clear()
        self.final_text.clear()
        self.status_label.setText("대기 중")

    def start_search(self):
        if self.worker is not None and self.worker.isRunning():
            return

        self.clear_texts()

        config = SearchConfig(
            pool_size=45,
            pick_count=6,
            start_index=1,
            offset_min=self.offset_min_spin.value(),
            offset_max=self.offset_max_spin.value(),
            top_k=self.topk_spin.value(),
        )

        self.worker = SearchWorker(config)
        self.worker.log_signal.connect(self.append_log)
        self.worker.final_signal.connect(self.set_final)
        self.worker.error_signal.connect(self.on_error)
        self.worker.finished.connect(self.on_finished)

        self.status_label.setText("탐색 중...")
        self.run_button.setEnabled(False)
        self.worker.start()

    def on_error(self, message: str):
        self.append_log(f"\n[ERROR] {message}")
        self.status_label.setText("오류 발생")

    def on_finished(self):
        self.status_label.setText("완료")
        self.run_button.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = LottoPredictionWindow()
    win.show()
    sys.exit(app.exec())
