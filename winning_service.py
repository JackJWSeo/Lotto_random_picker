from datetime import datetime

from database import (
    create_tables,
    get_combination_count,
    insert_or_replace_winning_row,
    replace_winning_excluded_rows,
    get_all_winning_rows,
)
from lotto_generator import combination_to_index
from winning_parser import parse_winning_text


def build_excluded_number_sets(numbers, bonus):
    """
    numbers: 당첨번호 6개
    bonus: 보너스 번호

    반환:
    [
        ([당첨번호6개], "main"),
        ([보너스로 1개 교체한 조합], "bonus_replace_1"),
        ...
    ]
    """
    sorted_numbers = sorted(numbers)
    result = [(sorted_numbers[:], "main")]

    for i in range(6):
        temp = sorted_numbers[:]
        temp[i] = bonus
        temp = sorted(temp)

        # 혹시라도 중복이 생기면 잘못된 조합이므로 제외
        if len(set(temp)) != 6:
            continue

        result.append((temp, f"bonus_replace_{i + 1}"))

    return result


def convert_number_sets_to_excluded_rows(draw_no, number_sets):
    excluded_rows = []

    for nums, comb_type in number_sets:
        comb_idx = combination_to_index(nums)
        excluded_rows.append((draw_no, comb_idx, comb_type))

    return excluded_rows


def import_winning_data_from_text(raw_text, progress_callback=None):
    create_tables()

    # 조합 DB 생성 여부를 여전히 프로그램 정책상 확인하고 싶다면 유지 가능
    # 다만 idx 계산 자체는 이제 DB 검색을 하지 않음
    parsed_rows = parse_winning_text(raw_text)
    if not parsed_rows:
        raise ValueError("파싱 가능한 당첨번호 데이터가 없습니다.")

    total = len(parsed_rows)

    for i, draw in enumerate(parsed_rows, start=1):
        main_comb_idx = combination_to_index(draw["numbers"])

        insert_or_replace_winning_row((
            draw["draw_no"],
            draw["draw_date"],
            main_comb_idx,
            draw["bonus"],
            draw["winner_count"],
            draw["prize_amount"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        excluded_number_sets = build_excluded_number_sets(
            draw["numbers"],
            draw["bonus"]
        )
        excluded_rows = convert_number_sets_to_excluded_rows(
            draw["draw_no"],
            excluded_number_sets
        )
        replace_winning_excluded_rows(draw["draw_no"], excluded_rows)

        if progress_callback:
            progress_callback(f"당첨번호 저장 중... {i} / {total}")

    if progress_callback:
        progress_callback(f"당첨번호 저장 완료: {total}개 회차")


def get_all_winning_numbers():
    return get_all_winning_rows()