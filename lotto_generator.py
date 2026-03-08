import math
import random
from itertools import combinations
from math import comb

from config import TOTAL_COMBINATIONS
from database import (
    create_tables,
    get_combination_count,
    insert_combination_batch,
    get_all_excluded_combination_indices,
)


def combination_to_long(nums):
    return int("".join(f"{n:02d}" for n in nums))


def long_to_combination(value):
    s = str(value).zfill(12)
    return [int(s[i:i + 2]) for i in range(0, 12, 2)]


def combination_to_index(nums):
    nums = sorted(nums)

    if len(nums) != 6:
        raise ValueError("번호는 6개여야 합니다.")

    if len(set(nums)) != 6:
        raise ValueError("번호는 중복 없이 6개여야 합니다.")

    if any(n < 1 or n > 45 for n in nums):
        raise ValueError("번호는 1~45 범위여야 합니다.")

    rank_zero_based = 0
    prev = 0
    n_total = 45
    k_total = 6

    for i in range(k_total):
        current = nums[i]

        for candidate in range(prev + 1, current):
            rank_zero_based += comb(n_total - candidate, k_total - i - 1)

        prev = current

    return rank_zero_based + 1


def index_to_combination(idx):
    if idx < 1 or idx > TOTAL_COMBINATIONS:
        raise ValueError(f"idx는 1~{TOTAL_COMBINATIONS:,} 범위여야 합니다.")

    rank = idx - 1
    result = []

    next_min = 1
    n_total = 45
    k_total = 6

    for i in range(k_total):
        for candidate in range(next_min, n_total + 1):
            count = comb(n_total - candidate, k_total - i - 1)

            if rank < count:
                result.append(candidate)
                next_min = candidate + 1
                break
            else:
                rank -= count

    return result


def build_all_combinations(progress_callback=None):
    create_tables()

    exists_count = get_combination_count()
    if exists_count > 0:
        if progress_callback:
            progress_callback(f"조합 DB가 이미 존재합니다. ({exists_count:,}개)")
        return

    batch_size = 10000
    buffer = []
    idx = 1

    for comb_nums in combinations(range(1, 46), 6):
        lotto_value = combination_to_long(comb_nums)
        buffer.append((idx, lotto_value))
        idx += 1

        if len(buffer) >= batch_size:
            insert_combination_batch(buffer)
            buffer.clear()

            if progress_callback:
                current = idx - 1
                progress_callback(f"조합 DB 생성 중... {current:,} / {TOTAL_COMBINATIONS:,}")

    if buffer:
        insert_combination_batch(buffer)

    if progress_callback:
        progress_callback("조합 DB 생성 완료")


def get_random_lotto_numbers():
    excluded_indices = get_all_excluded_combination_indices()

    if len(excluded_indices) >= TOTAL_COMBINATIONS:
        raise ValueError("생성 가능한 조합이 없습니다. 제외 인덱스가 전체 조합 수 이상입니다.")

    while True:
        rand_idx = random.randint(1, TOTAL_COMBINATIONS)
        if rand_idx in excluded_indices:
            continue

        return index_to_combination(rand_idx)


def get_random_lotto_number_sets(set_count=5):
    excluded_indices = get_all_excluded_combination_indices()

    if len(excluded_indices) >= TOTAL_COMBINATIONS:
        raise ValueError("생성 가능한 조합이 없습니다. 제외 인덱스가 전체 조합 수 이상입니다.")

    selected_indices = set()
    result_sets = []

    while len(result_sets) < set_count:
        rand_idx = random.randint(1, TOTAL_COMBINATIONS)

        if rand_idx in excluded_indices:
            continue

        if rand_idx in selected_indices:
            continue

        selected_indices.add(rand_idx)
        result_sets.append(index_to_combination(rand_idx))

    return result_sets


# =========================================================
# 2D 밀도 기반 가중 랜덤
# =========================================================
def get_2d_grid_size(total_count=TOTAL_COMBINATIONS):
    width = math.ceil(math.sqrt(total_count))
    height = math.ceil(total_count / width)
    return width, height


def index_to_2d_pos(idx, width):
    idx0 = idx - 1
    row = idx0 // width
    col = idx0 % width
    return row, col


def build_2d_density_blocks(excluded_indices, block_size=40):
    """
    전체 인덱스를 2D로 펼친 뒤 block_size 단위로 밀도 집계
    """
    width, height = get_2d_grid_size(TOTAL_COMBINATIONS)

    block_rows = math.ceil(height / block_size)
    block_cols = math.ceil(width / block_size)

    density = [[0 for _ in range(block_cols)] for _ in range(block_rows)]

    for idx in excluded_indices:
        row, col = index_to_2d_pos(idx, width)
        br = row // block_size
        bc = col // block_size
        density[br][bc] += 1

    max_density = 0
    for row in density:
        row_max = max(row) if row else 0
        if row_max > max_density:
            max_density = row_max

    return density, width, height, block_rows, block_cols, max_density


def get_block_density(idx, density_info, block_size=40):
    density, width, _height, _block_rows, _block_cols, _max_density = density_info
    row, col = index_to_2d_pos(idx, width)
    br = row // block_size
    bc = col // block_size
    return density[br][bc]


def choose_weighted_index_from_candidates(candidates, density_info, density_mode="low", block_size=40):
    """
    density_mode:
    - low  : 밀도 낮은 구역 우대
    - high : 밀도 높은 구역 우대
    """
    _density, _width, _height, _br, _bc, max_density = density_info

    weights = []
    for idx in candidates:
        d = get_block_density(idx, density_info, block_size=block_size)

        if density_mode == "low":
            # 밀도가 낮을수록 가중치 상승
            w = (max_density - d) + 1
        elif density_mode == "high":
            # 밀도가 높을수록 가중치 상승
            w = d + 1
        else:
            w = 1

        weights.append(float(w))

    return random.choices(candidates, weights=weights, k=1)[0]


def get_density_weighted_random_lotto_number_sets(
    set_count=5,
    density_mode="low",
    block_size=40,
    candidate_pool_size=2000,
):
    """
    2D 밀도 기준으로 랜덤 5세트 생성

    density_mode:
    - low  : 저밀도 우선
    - high : 고밀도 우선
    """
    excluded_indices = get_all_excluded_combination_indices()

    if len(excluded_indices) >= TOTAL_COMBINATIONS:
        raise ValueError("생성 가능한 조합이 없습니다. 제외 인덱스가 전체 조합 수 이상입니다.")

    density_info = build_2d_density_blocks(excluded_indices, block_size=block_size)

    selected_indices = set()
    result_sets = []

    while len(result_sets) < set_count:
        candidates = set()

        while len(candidates) < candidate_pool_size:
            rand_idx = random.randint(1, TOTAL_COMBINATIONS)

            if rand_idx in excluded_indices:
                continue

            if rand_idx in selected_indices:
                continue

            candidates.add(rand_idx)

        chosen_idx = choose_weighted_index_from_candidates(
            list(candidates),
            density_info,
            density_mode=density_mode,
            block_size=block_size,
        )

        selected_indices.add(chosen_idx)
        result_sets.append(index_to_combination(chosen_idx))

    return result_sets