import sqlite3
from config import DB_PATH, COMB_TABLE, WIN_TABLE, WIN_EXCLUDED_TABLE


def get_connection():
    return sqlite3.connect(DB_PATH)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {COMB_TABLE} (
            idx INTEGER PRIMARY KEY,
            lotto_value INTEGER NOT NULL UNIQUE
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {WIN_TABLE} (
            draw_no INTEGER PRIMARY KEY,
            draw_date TEXT,
            comb_idx INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            winner_count INTEGER,
            prize_amount INTEGER,
            inserted_at TEXT,
            FOREIGN KEY (comb_idx) REFERENCES {COMB_TABLE}(idx)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {WIN_EXCLUDED_TABLE} (
            draw_no INTEGER NOT NULL,
            comb_idx INTEGER NOT NULL,
            comb_type TEXT NOT NULL,
            PRIMARY KEY (draw_no, comb_idx),
            FOREIGN KEY (draw_no) REFERENCES {WIN_TABLE}(draw_no),
            FOREIGN KEY (comb_idx) REFERENCES {COMB_TABLE}(idx)
        )
    """)

    conn.commit()
    conn.close()


def get_combination_count():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM {COMB_TABLE}")
    count = cursor.fetchone()[0]

    conn.close()
    return count


def insert_combination_batch(rows):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executemany(
        f"INSERT INTO {COMB_TABLE} (idx, lotto_value) VALUES (?, ?)",
        rows
    )

    conn.commit()
    conn.close()


def get_combination_index_by_value(lotto_value):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT idx FROM {COMB_TABLE} WHERE lotto_value = ?",
        (lotto_value,)
    )
    row = cursor.fetchone()

    conn.close()
    return row[0] if row else None


def get_lotto_value_by_index(idx):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT lotto_value FROM {COMB_TABLE} WHERE idx = ?",
        (idx,)
    )
    row = cursor.fetchone()

    conn.close()
    return row[0] if row else None


def insert_or_replace_winning_row(row):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        INSERT OR REPLACE INTO {WIN_TABLE}
        (
            draw_no, draw_date, comb_idx, bonus,
            winner_count, prize_amount, inserted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, row)

    conn.commit()
    conn.close()


def replace_winning_excluded_rows(draw_no, excluded_rows):
    """
    excluded_rows 예:
    [
        (1214, 12345, 'main'),
        (1214, 33333, 'bonus_replace_1'),
        ...
    ]
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"DELETE FROM {WIN_EXCLUDED_TABLE} WHERE draw_no = ?",
        (draw_no,)
    )

    cursor.executemany(
        f"""
        INSERT INTO {WIN_EXCLUDED_TABLE} (draw_no, comb_idx, comb_type)
        VALUES (?, ?, ?)
        """,
        excluded_rows
    )

    conn.commit()
    conn.close()


def get_all_excluded_combination_indices():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"SELECT DISTINCT comb_idx FROM {WIN_EXCLUDED_TABLE}")
    rows = cursor.fetchall()

    conn.close()
    return {row[0] for row in rows}


def get_all_winning_rows():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT
            w.draw_no,
            w.draw_date,
            w.comb_idx,
            c.lotto_value,
            w.bonus,
            w.winner_count,
            w.prize_amount
        FROM {WIN_TABLE} w
        JOIN {COMB_TABLE} c
            ON w.comb_idx = c.idx
        ORDER BY w.draw_no DESC
    """)

    rows = cursor.fetchall()
    conn.close()
    return rows


def get_excluded_rows_by_draw(draw_no):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT comb_idx, comb_type
        FROM {WIN_EXCLUDED_TABLE}
        WHERE draw_no = ?
        ORDER BY comb_type
    """, (draw_no,))

    rows = cursor.fetchall()
    conn.close()
    return rows