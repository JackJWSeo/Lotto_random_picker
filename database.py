import sqlite3
from config import DB_PATH, WIN_TABLE, WIN_EXCLUDED_TABLE


LEGACY_COMB_TABLE = "lotto_combinations"


def get_connection():
    return sqlite3.connect(DB_PATH)


def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def _table_sql_contains(cursor, table_name, text):
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    )
    row = cursor.fetchone()
    return bool(row and row[0] and text.lower() in row[0].lower())


def _create_winning_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {WIN_TABLE} (
            draw_no INTEGER PRIMARY KEY,
            draw_date TEXT,
            comb_idx INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            winner_count INTEGER,
            prize_amount INTEGER,
            inserted_at TEXT
        )
    """)


def _create_excluded_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {WIN_EXCLUDED_TABLE} (
            draw_no INTEGER NOT NULL,
            comb_idx INTEGER NOT NULL,
            comb_type TEXT NOT NULL,
            PRIMARY KEY (draw_no, comb_idx)
        )
    """)


def _migrate_legacy_table(cursor, table_name, create_sql, column_names):
    legacy_name = f"{table_name}__legacy"
    column_list = ", ".join(column_names)

    cursor.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")
    cursor.execute(create_sql)
    cursor.execute(f"""
        INSERT INTO {table_name} ({column_list})
        SELECT {column_list}
        FROM {legacy_name}
    """)
    cursor.execute(f"DROP TABLE {legacy_name}")


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()
    winning_create_sql = f"""
        CREATE TABLE {WIN_TABLE} (
            draw_no INTEGER PRIMARY KEY,
            draw_date TEXT,
            comb_idx INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            winner_count INTEGER,
            prize_amount INTEGER,
            inserted_at TEXT
        )
    """
    excluded_create_sql = f"""
        CREATE TABLE {WIN_EXCLUDED_TABLE} (
            draw_no INTEGER NOT NULL,
            comb_idx INTEGER NOT NULL,
            comb_type TEXT NOT NULL,
            PRIMARY KEY (draw_no, comb_idx)
        )
    """

    if _table_exists(cursor, WIN_TABLE):
        if _table_sql_contains(cursor, WIN_TABLE, LEGACY_COMB_TABLE):
            _migrate_legacy_table(
                cursor,
                WIN_TABLE,
                winning_create_sql,
                [
                    "draw_no",
                    "draw_date",
                    "comb_idx",
                    "bonus",
                    "winner_count",
                    "prize_amount",
                    "inserted_at",
                ],
            )
    else:
        _create_winning_table(cursor)

    if _table_exists(cursor, WIN_EXCLUDED_TABLE):
        if _table_sql_contains(cursor, WIN_EXCLUDED_TABLE, LEGACY_COMB_TABLE):
            _migrate_legacy_table(
                cursor,
                WIN_EXCLUDED_TABLE,
                excluded_create_sql,
                [
                    "draw_no",
                    "comb_idx",
                    "comb_type",
                ],
            )
    else:
        _create_excluded_table(cursor)

    if _table_exists(cursor, LEGACY_COMB_TABLE):
        cursor.execute(f"DROP TABLE {LEGACY_COMB_TABLE}")

    conn.commit()
    conn.close()


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
            w.bonus,
            w.winner_count,
            w.prize_amount
        FROM {WIN_TABLE} w
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
