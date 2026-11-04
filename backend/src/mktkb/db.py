"""数据库生命周期：SQLite 连接参数、外键、WAL、FTS5 能力与 Alembic 迁移入口。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_ROOT / "migrations"


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class Database:
    """项目数据库句柄。连接级 PRAGMA 在每次建立连接时设置。"""

    def __init__(
        self,
        url: str,
        *,
        busy_timeout_ms: int = 5000,
        enable_wal: bool = True,
    ) -> None:
        self.url = url
        self.busy_timeout_ms = busy_timeout_ms
        self.enable_wal = enable_wal and url.startswith("sqlite") and ":memory:" not in url
        connect_args: dict = {}
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False, "timeout": busy_timeout_ms / 1000}
        self.engine = create_engine(url, future=True, connect_args=connect_args)
        event.listen(self.engine, "connect", self._on_connect)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def _on_connect(self, dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
            if self.enable_wal:
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    def session(self) -> Session:
        """按契约返回一个新的 Session；调用方负责关闭。"""
        return self._factory()

    @contextmanager
    def session_scope(self) -> Session:
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()

    # ---- 只读能力检查（供启动自检与测试使用） ----

    def foreign_keys_enabled(self) -> bool:
        with self.engine.connect() as connection:
            return bool(connection.exec_driver_sql("PRAGMA foreign_keys").scalar())

    def journal_mode(self) -> str:
        with self.engine.connect() as connection:
            return str(connection.exec_driver_sql("PRAGMA journal_mode").scalar()).lower()

    def fts5_available(self) -> bool:
        if not self.url.startswith("sqlite"):
            return False
        with self.engine.connect() as connection:
            try:
                connection.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(body)")
                connection.exec_driver_sql("INSERT INTO _fts5_probe(body) VALUES ('市场部 宣传海报')")
                hit = connection.exec_driver_sql("SELECT count(*) FROM _fts5_probe WHERE _fts5_probe MATCH '宣传海报'").scalar()
                connection.exec_driver_sql("DROP TABLE _fts5_probe")
                return bool(hit)
            except Exception:
                return False


def run_migrations(database_url: str, script_location: Path | None = None) -> None:
    """用 Alembic 从当前版本升级到 head；空库即建表。"""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(script_location or MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def current_revision(database_url: str, script_location: Path | None = None) -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(script_location or MIGRATIONS_DIR))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def table_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars().all()
    return set(rows)
