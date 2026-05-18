import pytest
from httpx import AsyncClient


SETUP_URL = "/api/auth/setup"
LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
ME_URL = "/api/auth/me"
NEEDS_SETUP_URL = "/api/auth/needs-setup"
CATEGORIES_URL = "/api/categories"

USER = {"username": "admin", "password": "hunter2"}


@pytest.fixture
async def authed_client(client: AsyncClient):
    await client.post(SETUP_URL, json=USER)
    return client


class TestNeedsSetup:
    async def test_needs_setup_true_initially(self, client: AsyncClient):
        r = await client.get(NEEDS_SETUP_URL)
        assert r.status_code == 200
        assert r.json() == {"needs_setup": True}

    async def test_needs_setup_false_after_user_created(self, authed_client: AsyncClient):
        r = await authed_client.get(NEEDS_SETUP_URL)
        assert r.status_code == 200
        assert r.json() == {"needs_setup": False}


class TestSetup:
    async def test_setup_creates_user(self, client: AsyncClient):
        r = await client.post(SETUP_URL, json=USER)
        assert r.status_code == 201
        body = r.json()
        assert body["username"] == "admin"
        assert "session" in r.cookies

    async def test_double_setup_rejected(self, authed_client: AsyncClient):
        r = await authed_client.post(SETUP_URL, json={"username": "other", "password": "pass"})
        assert r.status_code == 409


class TestLogin:
    async def test_login_success(self, authed_client: AsyncClient):
        r = await authed_client.post(LOGIN_URL, json=USER)
        assert r.status_code == 200
        assert r.json()["username"] == "admin"
        assert "session" in r.cookies

    async def test_login_wrong_password(self, authed_client: AsyncClient):
        r = await authed_client.post(LOGIN_URL, json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    async def test_login_unknown_user(self, authed_client: AsyncClient):
        r = await authed_client.post(LOGIN_URL, json={"username": "nobody", "password": "x"})
        assert r.status_code == 401


class TestLogout:
    async def test_logout_clears_cookie(self, authed_client: AsyncClient):
        r = await authed_client.post(LOGOUT_URL)
        assert r.status_code == 204


class TestMe:
    async def test_me_authenticated(self, authed_client: AsyncClient):
        r = await authed_client.get(ME_URL)
        assert r.status_code == 200
        assert r.json()["username"] == "admin"

    async def test_me_unauthenticated(self, client: AsyncClient):
        r = await client.get(ME_URL)
        assert r.status_code == 401


class TestProtectedRoutes:
    async def test_categories_requires_auth(self, client: AsyncClient):
        r = await client.get(CATEGORIES_URL)
        assert r.status_code == 401

    async def test_categories_accessible_when_authed(self, authed_client: AsyncClient):
        r = await authed_client.get(CATEGORIES_URL)
        assert r.status_code == 200
