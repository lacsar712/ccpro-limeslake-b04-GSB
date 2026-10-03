"""轻量 schema 兜底：db.create_all() 不会给已存在的表补列，
线上持久卷里的旧库启动时需要幂等地 ADD COLUMN。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.extensions import db

# 表名 -> [(列名, 列类型 DDL, 建列时回填旧行的 server_default 或 None)]
_PENDING_COLUMNS = {
    "plants": [
        ("peak_cap_enabled", "BOOLEAN NOT NULL DEFAULT false", None),
        ("peak_cap_c", "FLOAT", None),
    ],
    "slake_batches": [
        ("version", "INTEGER NOT NULL DEFAULT 1", None),
    ],
}


def ensure_schema() -> None:
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _PENDING_COLUMNS.items():
        if table not in existing_tables:
            # create_all 会按模型建全列，无需处理。
            continue
        present = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl, _server_default in columns:
            if name in present:
                continue
            try:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                db.session.commit()
            except Exception:
                # 多 worker/多进程并发启动时，可能已被另一进程加上该列
                # （Postgres 42701 duplicate_column / SQLite duplicate column name）。
                db.session.rollback()
                inspector = inspect(db.engine)
                cols_now = {c["name"] for c in inspector.get_columns(table)}
                if name not in cols_now:
                    raise
