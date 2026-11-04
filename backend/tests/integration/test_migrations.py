"""T02 迁移与数据库能力检查：空库升级、幂等、外键、FTS5、隔离与持久化。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from mktkb.auth.models import LoginSession, User
from mktkb.auth.service import account_count, bootstrap_accounts
from mktkb.db import Database, run_migrations, table_names


def _database(tmp_path: Path, name: str = "db.sqlite3") -> tuple[Database, str]:
    root = tmp_path / name.replace(".sqlite3", "")
    root.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(root / name).as_posix()}"
    return Database(url), url


def _bootstrap(database: Database, admin_password: str = "AdminPass-1") -> list[str]:
    with database.session_scope() as session:
        return bootstrap_accounts(
            session,
            admin_username="admin",
            admin_password=admin_password,
            admin_display_name="演示管理员",
            employee_username="employee",
            employee_password="EmployeePass-1",
            employee_display_name="演示员工",
            rounds=4,
        )


def test_migrations_from_empty_database(tmp_path: Path):
    database, url = _database(tmp_path)
    try:
        run_migrations(url)
        tables = table_names(database.engine)
        assert {"users", "login_sessions", "alembic_version"} <= tables
        with database.session_scope() as session:
            assert session.scalar(select(User.id).limit(1)) is None, "新库不应自带账号"
    finally:
        database.dispose()


def test_upgrade_twice_keeps_single_head_and_data(tmp_path: Path):
    database, url = _database(tmp_path)
    try:
        run_migrations(url)
        _bootstrap(database)
        before = None
        with database.session_scope() as session:
            before = account_count(session)
        run_migrations(url)  # 重复升级
        with database.session_scope() as session:
            assert account_count(session) == before
            version_rows = session.execute(text("SELECT count(*) FROM alembic_version")).scalar()
        assert version_rows == 1
    finally:
        database.dispose()


def test_bootstrap_is_idempotent(tmp_path: Path):
    database, url = _database(tmp_path)
    try:
        run_migrations(url)
        assert sorted(_bootstrap(database)) == ["admin", "employee"]
        assert _bootstrap(database) == []
        with database.session_scope() as session:
            users = session.scalars(select(User)).all()
            assert len(users) == 2
            hashes = {user.username: user.password_hash for user in users}
            assert hashes["admin"].startswith("$2")
        assert _bootstrap(database) == []
        with database.session_scope() as session:
            again = {user.username: user.password_hash for user in session.scalars(select(User)).all()}
        assert again == hashes, "重复初始化不得重置密码摘要"
    finally:
        database.dispose()


def test_foreign_keys_are_enforced(tmp_path: Path):
    database, url = _database(tmp_path)
    try:
        run_migrations(url)
        assert database.foreign_keys_enabled() is True
        with database.session_scope() as session:
            session.add(
                LoginSession(
                    user_id=uuid.uuid4(),
                    token_hash="0" * 64,
                    expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                )
            )
    except IntegrityError:
        pass
    else:  # pragma: no cover
        pytest.fail("外键未生效：应拒绝指向不存在用户的会话")
    finally:
        database.dispose()


def test_fts5_and_wal_are_available(tmp_path: Path):
    database, url = _database(tmp_path)
    try:
        run_migrations(url)
        assert database.fts5_available() is True, "SQLite 应支持 FTS5（本步不实现中文检索）"
        assert database.journal_mode() == "wal"
    finally:
        database.dispose()


def test_two_databases_are_isolated(tmp_path: Path):
    first, first_url = _database(tmp_path, "a.sqlite3")
    second, second_url = _database(tmp_path, "b.sqlite3")
    try:
        for url in (first_url, second_url):
            run_migrations(url)
        with first.session_scope() as session:
            session.add(User(username="only-in-a", display_name="A", role="employee", password_hash="x" * 60, password_algo="bcrypt$4"))
        with first.session_scope() as session:
            assert session.scalar(select(User.id).where(User.username == "only-in-a")) is not None
        with second.session_scope() as session:
            assert session.scalar(select(User.id).where(User.username == "only-in-a")) is None
    finally:
        first.dispose()
        second.dispose()


def test_settings_database_url_is_project_local(settings):
    from pathlib import Path as _Path

    url = settings.resolved_database_url()
    assert url.startswith("sqlite:///")
    path = _Path(url.removeprefix("sqlite:///"))
    assert path.is_absolute()
    assert settings.data_dir in path.parents or path.parent == settings.data_dir
