"""Pytest fixtures. Runs the app against an isolated temp SQLite DB so tests never
touch real data. Env is set before importing the app so its engine/settings pick it up."""
import os
import tempfile

import pytest

# Force test-only env BEFORE importing the app, so tests never touch real data and
# the admin is always bootstrapped (overrides any empty values from the container).
_TMP = tempfile.mkdtemp(prefix="xyberah-test-")
os.environ["XYBERAH_DATA_DIR"] = _TMP
os.environ["XYBERAH_SECRET_KEY"] = "test-secret-key-0123456789abcdef0123456789"
os.environ["XYBERAH_ADMIN_USERNAME"] = "admin@test.local"
os.environ["XYBERAH_ADMIN_PASSWORD"] = "testpassword123"
os.environ["XYBERAH_COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, Role, User  # noqa: E402
from sqlmodel import select  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _startup():
    # Entering the context runs startup events (init_db, migrate, bootstrap admin).
    with TestClient(app):
        yield


def _client() -> TestClient:
    c = TestClient(app)
    c.headers["X-Requested-With"] = "xyberah"  # CSRF header for mutations
    return c


@pytest.fixture
def client() -> TestClient:
    return _client()


@pytest.fixture
def admin_client() -> TestClient:
    c = _client()
    r = c.post("/api/auth/login", json={"email": "admin@test.local", "password": "testpassword123"})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def db():
    with Session(engine) as s:
        yield s


def make_company(name: str) -> int:
    with Session(engine) as s:
        slug = name.lower().replace(" ", "-")
        existing = s.exec(select(Company).where(Company.slug == slug)).first()
        if existing:
            return existing.id
        c = Company(name=name, slug=slug)
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


def make_user(email: str, company_id, role: Role, password: str = "userpassword123") -> int:
    with Session(engine) as s:
        u = User(email=email, username=email, company_id=company_id, role=role,
                 password_hash=hash_password(password))
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def login(email: str, password: str = "userpassword123") -> TestClient:
    c = _client()
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c
