import pytest

from app.config import DEV_SECRET, Settings, check_production_safety


def test_real_database_with_dev_secret_refuses_to_start():
    with pytest.raises(RuntimeError):
        check_production_safety(Settings(database_url="postgresql+psycopg://u:p@h/db", reporter_secret=DEV_SECRET))


def test_real_database_with_secret_ok():
    check_production_safety(Settings(database_url="postgresql+psycopg://u:p@h/db", reporter_secret="x" * 32))


def test_sqlite_with_dev_secret_ok():
    check_production_safety(Settings(database_url="sqlite:///./x.db", reporter_secret=DEV_SECRET))
