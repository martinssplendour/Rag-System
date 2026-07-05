"""API tests for /auth/register, /auth/login, and JWT-mode route protection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def jwt_client(tmp_path: Path, postgres_database_url: str) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        database_url=postgres_database_url,
        storage_backend="local",
        local_storage_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        auth_mode="jwt",
        jwt_secret="integration-test-secret-not-for-real-use",
        admin_emails="upload-admin@example.com,isolation-alice@example.com,isolation-bob@example.com",
        embedding_provider="mock",
        llm_provider="mock",
        ingestion_worker_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest_asyncio.fixture
async def api_key_client(tmp_path: Path, postgres_database_url: str) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        database_url=postgres_database_url,
        storage_backend="local",
        local_storage_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        auth_mode="api_key",
        app_api_key="integration-test-api-key",
        embedding_provider="mock",
        llm_provider="mock",
        ingestion_worker_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_register_returns_a_token_and_workspace(jwt_client: AsyncClient):
    response = await jwt_client.post(
        "/auth/register", json={"email": "alice@example.com", "password": "correct-horse-battery"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["workspace_id"]
    assert body["is_admin"] is False


async def test_register_configured_admin_returns_admin_flag(jwt_client: AsyncClient):
    response = await jwt_client.post(
        "/auth/register", json={"email": "upload-admin@example.com", "password": "correct-password"}
    )
    assert response.status_code == 201
    assert response.json()["is_admin"] is True


async def test_register_with_duplicate_email_is_rejected(jwt_client: AsyncClient):
    await jwt_client.post("/auth/register", json={"email": "bob@example.com", "password": "first-password"})
    response = await jwt_client.post(
        "/auth/register", json={"email": "bob@example.com", "password": "second-password"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_email_is_case_insensitive_for_duplicates(jwt_client: AsyncClient):
    await jwt_client.post("/auth/register", json={"email": "Carol@Example.com", "password": "password123"})
    response = await jwt_client.post(
        "/auth/register", json={"email": "carol@example.com", "password": "different-password"}
    )
    assert response.status_code == 409


async def test_register_rejects_short_password(jwt_client: AsyncClient):
    response = await jwt_client.post(
        "/auth/register", json={"email": "dave@example.com", "password": "short"}
    )
    assert response.status_code == 422
    assert '"input"' not in response.text
    errors = response.json()["error"]["details"]["errors"]
    assert all("input" not in error for error in errors)


async def test_login_with_correct_password_returns_a_token(jwt_client: AsyncClient):
    await jwt_client.post(
        "/auth/register", json={"email": "erin@example.com", "password": "correct-password"}
    )
    response = await jwt_client.post(
        "/auth/login", json={"email": "erin@example.com", "password": "correct-password"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_with_wrong_password_is_rejected(jwt_client: AsyncClient):
    await jwt_client.post(
        "/auth/register", json={"email": "frank@example.com", "password": "correct-password"}
    )
    response = await jwt_client.post(
        "/auth/login", json={"email": "frank@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_with_unknown_email_is_rejected_with_the_same_error_as_wrong_password(
    jwt_client: AsyncClient,
):
    """Security checklist: do not let an attacker distinguish "no such
    account" from "wrong password" -- that would enable email enumeration."""
    response = await jwt_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_documents_endpoint_rejects_missing_token(jwt_client: AsyncClient):
    response = await jwt_client.get("/documents")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MISSING_TOKEN"


async def test_documents_endpoint_rejects_invalid_token(jwt_client: AsyncClient):
    response = await jwt_client.get("/documents", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_documents_endpoint_accepts_valid_token(jwt_client: AsyncClient):
    register = await jwt_client.post(
        "/auth/register", json={"email": "grace@example.com", "password": "correct-password"}
    )
    token = register.json()["access_token"]
    response = await jwt_client.get("/documents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_non_admin_cannot_upload_documents(jwt_client: AsyncClient):
    register = await jwt_client.post(
        "/auth/register", json={"email": "reader@example.com", "password": "correct-password"}
    )
    token = register.json()["access_token"]
    response = await jwt_client.post(
        "/documents",
        files={"file": ("reader_doc.txt", b"Reader cannot upload.", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


async def test_configured_admin_can_upload_documents(jwt_client: AsyncClient):
    register = await jwt_client.post(
        "/auth/register", json={"email": "upload-admin@example.com", "password": "correct-password"}
    )
    token = register.json()["access_token"]
    response = await jwt_client.post(
        "/documents",
        files={"file": ("admin_doc.txt", b"Admin upload evidence.", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 202
    assert response.json()["filename"] == "admin_doc.txt"


async def test_two_users_documents_do_not_collide(jwt_client: AsyncClient):
    """The actual proof this feature exists for: two different registered
    users each upload a document, and neither can see the other's."""
    alice = await jwt_client.post(
        "/auth/register", json={"email": "isolation-alice@example.com", "password": "alice-password"}
    )
    bob = await jwt_client.post(
        "/auth/register", json={"email": "isolation-bob@example.com", "password": "bob-password"}
    )
    alice_token = alice.json()["access_token"]
    bob_token = bob.json()["access_token"]
    assert alice.json()["workspace_id"] != bob.json()["workspace_id"]

    alice_upload = await jwt_client.post(
        "/documents",
        files={"file": ("alice_doc.txt", b"Alice's private evidence document.", "text/plain")},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    bob_upload = await jwt_client.post(
        "/documents",
        files={"file": ("bob_doc.txt", b"Bob's private evidence document, totally different.", "text/plain")},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert alice_upload.status_code == 202
    assert bob_upload.status_code == 202

    alice_documents = await jwt_client.get("/documents", headers={"Authorization": f"Bearer {alice_token}"})
    bob_documents = await jwt_client.get("/documents", headers={"Authorization": f"Bearer {bob_token}"})

    alice_filenames = {item["filename"] for item in alice_documents.json()["items"]}
    bob_filenames = {item["filename"] for item in bob_documents.json()["items"]}

    assert alice_filenames == {"alice_doc.txt"}
    assert bob_filenames == {"bob_doc.txt"}
    assert alice_filenames.isdisjoint(bob_filenames)


async def test_jwt_mode_without_secret_refuses_to_start(tmp_path: Path):
    settings = Settings(
        chroma_persist_dir=tmp_path / "chroma2",
        local_storage_dir=tmp_path / "uploads2",
        auth_mode="jwt",
        jwt_secret=None,
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(settings)


async def test_api_key_mode_without_real_key_refuses_to_start(tmp_path: Path):
    settings = Settings(
        chroma_persist_dir=tmp_path / "chroma3",
        local_storage_dir=tmp_path / "uploads3",
        auth_mode="api_key",
        app_api_key="change-me",
    )
    with pytest.raises(RuntimeError, match="APP_API_KEY"):
        create_app(settings)


async def test_api_key_mode_rejects_missing_key(api_key_client: AsyncClient):
    response = await api_key_client.get("/documents")

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "UNAUTHORIZED"
    assert error["message"] == "Authentication required."


async def test_api_key_mode_rejects_wrong_key(api_key_client: AsyncClient):
    response = await api_key_client.get("/documents", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "UNAUTHORIZED"
    assert error["message"] == "Authentication required."


async def test_api_key_mode_uses_same_public_error_for_missing_and_wrong_key(
    api_key_client: AsyncClient,
):
    missing = await api_key_client.get("/documents")
    wrong = await api_key_client.get("/documents", headers={"X-API-Key": "wrong-key"})

    missing_error = missing.json()["error"]
    wrong_error = wrong.json()["error"]
    assert missing.status_code == wrong.status_code == 401
    assert missing_error["code"] == wrong_error["code"] == "UNAUTHORIZED"
    assert missing_error["message"] == wrong_error["message"] == "Authentication required."


async def test_api_key_mode_accepts_valid_key_and_allows_upload(api_key_client: AsyncClient):
    response = await api_key_client.post(
        "/documents",
        files={"file": ("api_key_doc.txt", b"API key protected upload.", "text/plain")},
        headers={"X-API-Key": "integration-test-api-key"},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "api_key_doc.txt"
