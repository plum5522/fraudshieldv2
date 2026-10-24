"""Shared test fixtures. Every test gets a brand-new, empty in-memory database,
so tests never depend on each other or on leftover data."""

import os

# Must be set before the app is imported, so startup never touches a real database file.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")  # set in CI to a real Postgres


@pytest.fixture
def session_factory():
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(engine)  # clean slate for every test
    else:
        # StaticPool keeps one connection open, so the in-memory DB survives across sessions.
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def client(session_factory):
    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
