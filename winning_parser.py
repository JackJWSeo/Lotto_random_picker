import re


def parse_int_from_text(text):
    only_num = re.sub(r"[^\d]", "", text)
    if not only_num:
        return None
    return int(only_num)


def parse_winning_text(raw_text):
    lines = raw_text.splitlines()
    parsed_rows = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if "회차" in line and "보너스" in line:
            continue

        parts = re.findall(r"[\d,]+", line)

        if len(parts) < 10:
            continue

        try:
            draw_no = parse_int_from_text(parts[0])
            numbers = [parse_int_from_text(x) for x in parts[1:7]]
            bonus = parse_int_from_text(parts[7])
            winner_count = parse_int_from_text(parts[8])
            prize_amount = parse_int_from_text(parts[9])

            if draw_no is None or bonus is None:
                continue
            if any(n is None for n in numbers):
                continue

            parsed_rows.append({
                "draw_no": draw_no,
                "draw_date": None,
                "numbers": sorted(numbers),
                "bonus": bonus,
                "winner_count": winner_count,
                "prize_amount": prize_amount,
            })
        except Exception:
            continue

    return parsed_rows