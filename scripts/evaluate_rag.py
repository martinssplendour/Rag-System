"""Run a small RAG quality evaluation against the candidate dataset.

This is intentionally a rule-based evaluator, not an LLM judge. It checks
whether known questions retrieve the expected source documents, return valid
source cards, and mention expected evidence concepts. In live mode it also
checks answer concepts where the golden file supplies them.

Run from the repository root:

    python scripts/evaluate_rag.py --mode live
    python scripts/evaluate_rag.py --mode mock

The script loads .env and backend/.env, uses the configured database URL,
creates an isolated temporary evaluation database, and drops it when finished.
Chroma uses a temporary local directory for each run. If the configured
database is localhost:5433 and it is not running, the script starts a temporary
local PostgreSQL server with the installed PostgreSQL tools automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_CASES_PATH = REPO_ROOT / "eval" / "golden_questions.jsonl"
DATASET_ZIP_PATH = REPO_ROOT / "kintiga_market_access_candidate_dataset.zip"
EVAL_API_KEY = "local-evaluation-api-key-not-a-secret"
DEFAULT_POSTGRES_START_TIMEOUT_SECONDS = 60
DEFAULT_DOCKER_START_TIMEOUT_SECONDS = 30


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").lstrip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


# Keep app.main import safe even if a local backend/.env contains a strict auth
# mode. The evaluator passes its own explicit Settings object below.
load_env_file(REPO_ROOT / ".env")
load_env_file(BACKEND_ROOT / ".env")
os.environ["AUTH_MODE"] = "disabled"
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from app.core.config import Settings  # noqa: E402
    from app.main import create_app  # noqa: E402
    from app.repositories.database import _normalise_async_database_url  # noqa: E402
except ModuleNotFoundError as exc:
    missing = exc.name or "unknown"
    raise SystemExit(
        f"Missing backend Python dependency: {missing}. Run this once from the repo root: "
        'cd backend; python -m pip install -e ".[dev]"; cd ..'
    ) from exc

DATASET_FILES: tuple[tuple[str, str, str, str], ...] = (
    ("uk_nice_oncology_drug_summary.txt", "United Kingdom", "UK", "en"),
    ("germany_amnog_digital_therapeutic_note_de.txt", "Germany", "DE", "de"),
    ("france_has_medtech_reimbursement_summary.pdf", "France", "FR", "en"),
    ("italy_pricing_reimbursement_pathway_note.pdf", "Italy", "IT", "en"),
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str
    weight: int
    required: bool = False


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    question: str
    country: str | None
    score: float
    passed: bool
    status_code: int
    latency_ms: int
    confidence: str
    answer: str
    source_ids: list[str]
    source_count: int
    expected_documents: list[str]
    expected_source_ids: list[str]
    checks: list[Check]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval and answer quality.")
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default="live",
        help="live uses Gemini for semantic answer quality; mock is only an explicit offline smoke check.",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to JSONL golden questions.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET_ZIP_PATH,
        help="Path to kintiga_market_access_candidate_dataset.zip.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Base Postgres URL used to create a temporary evaluation database. "
            "Defaults to EVAL_DATABASE_URL, DATABASE_URL, then Settings().database_url."
        ),
    )
    parser.add_argument(
        "--start-postgres",
        action="store_true",
        help="Force-start the bundled Docker Compose development Postgres service before connecting.",
    )
    parser.add_argument(
        "--no-start-postgres",
        action="store_true",
        help="Never start a local Postgres server automatically.",
    )
    parser.add_argument(
        "--postgres-start-timeout",
        type=int,
        default=DEFAULT_POSTGRES_START_TIMEOUT_SECONDS,
        help="Seconds to wait for the configured Postgres database to accept connections.",
    )
    parser.add_argument(
        "--min-average-score",
        type=float,
        default=None,
        help="Minimum average score. Defaults to 70 in mock mode and 80 in live mode.",
    )
    parser.add_argument(
        "--min-case-score",
        type=float,
        default=None,
        help="Minimum score for each case. Defaults to 55 in mock mode and 70 in live mode.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every check for every case.",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                cases.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}: {exc}") from exc
    if not cases:
        raise ValueError(f"No evaluation cases found in {path}")
    return cases


async def run_evaluation(args: argparse.Namespace) -> list[CaseResult]:
    if not args.dataset.exists():
        raise SystemExit(
            f"Dataset zip not found at {args.dataset}. Place the provided candidate dataset "
            "zip at the repository root or pass --dataset."
    )
    cases = load_cases(args.cases)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("kintiga_evidence_assistant").setLevel(logging.WARNING)

    with tempfile.TemporaryDirectory(
        prefix="rag-eval-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        temp_root = Path(temp_dir)
        with prepared_postgres(args, temp_root) as database_url:
            async with temporary_postgres_database(
                database_url,
                startup_timeout_seconds=args.postgres_start_timeout,
            ) as database_url:
                settings = build_settings(args.mode, temp_root, database_url)
                app = create_app(settings)
                transport = ASGITransport(app=app)
                headers = {"X-API-Key": EVAL_API_KEY}

                async with app.router.lifespan_context(app):
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        await seed_dataset(client, headers, args.dataset)
                        return [
                            await evaluate_case(client, headers, case, args.mode) for case in cases
                        ]


def build_settings(mode: str, temp_root: Path, database_url: str) -> Settings:
    base = Settings()
    common: dict[str, Any] = {
        "database_url": database_url,
        "storage_backend": "local",
        "local_storage_dir": temp_root / "uploads",
        "chroma_persist_dir": temp_root / "chroma",
        "auth_mode": "api_key",
        "app_api_key": EVAL_API_KEY,
        "default_workspace_id": base.default_workspace_id,
        "log_level": "WARNING",
        "ingestion_worker_enabled": True,
        "retrieval_cache_enabled": False,
        "retrieval_candidate_count": 32,
        "retrieval_context_count": 8,
        "retrieval_max_chunks_per_document": 4,
        "retrieval_min_similarity": 0.0 if mode == "mock" else base.retrieval_min_similarity,
    }

    if mode == "mock":
        return Settings(
            **common,
            embedding_provider="mock",
            llm_provider="mock",
        )

    api_key = base.gemini_api_key or base.google_api_key or os.environ.get("GEMINI_API_KEY")
    api_key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("Live evaluation requires GEMINI_API_KEY or GOOGLE_API_KEY.")

    embedding_model = os.environ.get("EMBEDDING_MODEL") or base.embedding_model
    if "gemini" not in embedding_model.lower():
        embedding_model = "models/gemini-embedding-001"

    return Settings(
        **common,
        embedding_provider="gemini",
        embedding_model=embedding_model,
        llm_provider="gemini",
        chat_model=os.environ.get("CHAT_MODEL") or base.chat_model or "gemini-3.5-flash",
        gemini_api_key=api_key,
        google_api_key=api_key,
    )


@contextmanager
def prepared_postgres(args: argparse.Namespace, temp_root: Path):
    database_url = _base_evaluation_database_url(args.database_url)
    postgres_process: subprocess.Popen[str] | None = None
    data_dir = temp_root / "postgres"

    if should_auto_start_local_postgres(database_url, args.no_start_postgres):
        print(
            "\nPostgres: no server is listening on localhost:5433; "
            "starting a temporary local Postgres server.",
            flush=True,
        )
        postgres_process = start_temporary_pg_ctl_postgres(
            database_url,
            data_dir,
            timeout_seconds=args.postgres_start_timeout,
        )
        if postgres_process is None:
            raise SystemExit(
                "Postgres is not running on localhost:5433 and local PostgreSQL tools were not found. "
                "Install PostgreSQL locally or pass --start-postgres to use Docker Compose."
            )
    elif args.start_postgres:
        start_docker_postgres()

    try:
        yield database_url
    finally:
        if postgres_process is not None:
            stop_temporary_postgres(data_dir, postgres_process)


def should_auto_start_local_postgres(database_url: str, disabled: bool) -> bool:
    if disabled:
        return False

    try:
        url = make_url(_normalise_async_database_url(database_url))
    except Exception:
        return False

    host = (url.host or "").casefold()
    port = url.port or 5432
    if host not in {"localhost", "127.0.0.1"} or port != 5433:
        return False

    return not _tcp_port_accepts_connection(host, port)


def _tcp_port_accepts_connection(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def start_temporary_pg_ctl_postgres(
    database_url: str,
    data_dir: Path,
    *,
    timeout_seconds: int,
) -> subprocess.Popen[str] | None:
    initdb = shutil.which("initdb")
    postgres = shutil.which("postgres")
    if not initdb or not postgres:
        print("Postgres: initdb/postgres not found on PATH.")
        return None

    url = make_url(_normalise_async_database_url(database_url))
    username = url.username or "postgres"
    host = url.host or "localhost"
    port = str(url.port or 5432)
    log_path = data_dir.parent / "postgres.log"
    data_dir_arg = data_dir.name

    print(f"Postgres: initializing temporary cluster at {data_dir}", flush=True)
    try:
        subprocess.run(
            [
                initdb,
                "-D",
                data_dir_arg,
                "-U",
                username,
                "--auth=trust",
                "--encoding=UTF8",
            ],
            cwd=data_dir.parent,
            check=True,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 1),
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(f"Failed to initialize temporary local Postgres: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            f"Timed out while initializing temporary local Postgres. Log: {log_path}"
        ) from exc

    print("Postgres: initialization complete; starting server.", flush=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                postgres,
                "-D",
                data_dir_arg,
                "-h",
                host,
                "-p",
                port,
            ],
            cwd=data_dir.parent,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    wait_for_temporary_postgres(
        process,
        host=host,
        port=int(port),
        timeout_seconds=timeout_seconds,
        log_path=log_path,
    )
    print(f"Postgres: temporary local server is running on {host}:{port}.", flush=True)
    return process


def wait_for_temporary_postgres(
    process: subprocess.Popen[str],
    *,
    host: str,
    port: int,
    timeout_seconds: int,
    log_path: Path,
) -> None:
    deadline = time.monotonic() + max(timeout_seconds, 1)
    while time.monotonic() < deadline:
        if _tcp_port_accepts_connection(host, port):
            return

        return_code = process.poll()
        if return_code is not None:
            raise SystemExit(
                "Temporary local Postgres exited before accepting connections "
                f"(exit={return_code}). Log: {log_path}"
            )
        time.sleep(0.25)

    raise SystemExit(
        f"Timed out while waiting for temporary local Postgres on {host}:{port}. Log: {log_path}"
    )


def stop_temporary_postgres(data_dir: Path, process: subprocess.Popen[str]) -> None:
    pg_ctl = shutil.which("pg_ctl")
    if pg_ctl:
        subprocess.run(
            [pg_ctl, "-D", data_dir.name, "-m", "fast", "-w", "stop"],
            cwd=data_dir.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def start_docker_postgres() -> None:
    command = [
        "docker-compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.dev.yml",
        "up",
        "-d",
        "postgres",
    ]
    print("\nPostgres", flush=True)
    print("Starting local Docker Compose Postgres service...", flush=True)
    try:
        subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=DEFAULT_DOCKER_START_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "docker-compose was not found. Install Docker Desktop, start Postgres another way "
            "and pass --no-start-postgres, or pass --database-url pointing at a running Postgres."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            "Timed out while starting local Postgres with docker-compose. "
            "Make sure Docker Desktop is running, start Postgres another way with "
            "--no-start-postgres, or pass --database-url pointing at a running Postgres."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(f"Failed to start local Postgres with docker-compose: {detail}") from exc
    print("Local Postgres requested on localhost:5433.", flush=True)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _base_evaluation_database_url(explicit_url: str | None) -> str:
    return (
        explicit_url
        or os.environ.get("EVAL_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or Settings().database_url
    )


@asynccontextmanager
async def temporary_postgres_database(
    base_database_url: str,
    *,
    startup_timeout_seconds: int,
):
    base_url = make_url(_normalise_async_database_url(base_database_url))
    database_name = f"eval_{uuid4().hex}"
    maintenance_database = os.environ.get("EVAL_POSTGRES_MAINTENANCE_DB", "postgres")
    maintenance_url = base_url.set(database=maintenance_database)
    evaluation_url = base_url.set(database=database_name)

    admin_engine = create_async_engine(
        maintenance_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        connect_args={"timeout": min(max(startup_timeout_seconds, 1), 5)},
    )
    print(
        f"\nPostgres: connecting to {base_url.render_as_string(hide_password=True)}",
        flush=True,
    )
    try:
        await create_temporary_database(
            admin_engine,
            database_name,
            timeout_seconds=startup_timeout_seconds,
        )
    except Exception as exc:
        await admin_engine.dispose()
        raise SystemExit(f"Evaluation requires reachable Postgres: {exc}") from exc

    try:
        yield evaluation_url.render_as_string(hide_password=False)
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "select pg_terminate_backend(pid) "
                    "from pg_stat_activity "
                    "where datname = :database_name and pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await conn.execute(
                text(
                    f"DROP DATABASE IF EXISTS {_quote_identifier(database_name)} "
                    "WITH (FORCE)"
                )
            )
        await admin_engine.dispose()


async def create_temporary_database(
    admin_engine: Any,
    database_name: str,
    *,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + max(timeout_seconds, 1)
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            async with admin_engine.connect() as conn:
                await conn.execute(text(f"CREATE DATABASE {_quote_identifier(database_name)}"))
            print("Postgres is ready; temporary evaluation database created.")
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)

    raise TimeoutError(
        f"Postgres did not become ready within {timeout_seconds} seconds: {last_error}"
    )


async def seed_dataset(client: AsyncClient, headers: dict[str, str], dataset_path: Path) -> None:
    print("\nDataset seeding")
    for filename, country, country_code, language in DATASET_FILES:
        content = read_dataset_file(dataset_path, filename)
        mime_type = "application/pdf" if filename.endswith(".pdf") else "text/plain"
        print(f"- Uploading {filename} ({country})")
        response = await client.post(
            "/documents",
            headers=headers,
            data={
                "country": country,
                "country_code": country_code,
                "language": language,
            },
            files={"file": (filename, content, mime_type)},
        )
        if response.status_code != 202:
            raise RuntimeError(f"Failed to upload {filename}: {response.status_code} {response.text}")
        document_id = response.json()["document_id"]
        await wait_for_document_ready(client, headers, document_id, filename)


def read_dataset_file(dataset_path: Path, filename: str) -> bytes:
    with zipfile.ZipFile(dataset_path) as archive:
        for name in archive.namelist():
            base_name = Path(name).name
            if name.endswith("/") or base_name != filename:
                continue
            if any(part.startswith("__MACOSX") for part in Path(name).parts):
                continue
            if base_name.startswith("._"):
                continue
            return archive.read(name)
    raise FileNotFoundError(f"{filename} not found in {dataset_path}")


async def wait_for_document_ready(
    client: AsyncClient,
    headers: dict[str, str],
    document_id: str,
    filename: str,
) -> None:
    deadline = time.monotonic() + 20
    last_status = "missing"
    while time.monotonic() < deadline:
        response = await client.get("/documents", headers=headers)
        response.raise_for_status()
        for item in response.json()["items"]:
            if item["document_id"] != document_id:
                continue
            last_status = item["status"]
            if last_status == "ready":
                print(f"  ready: {filename}")
                return
            if last_status == "failed":
                raise RuntimeError(f"Ingestion failed for {filename}: {item}")
        await asyncio.sleep(0.1)
    raise TimeoutError(f"{filename} did not reach ready status; last_status={last_status}")


async def evaluate_case(
    client: AsyncClient,
    headers: dict[str, str],
    case: dict[str, Any],
    mode: str,
) -> CaseResult:
    started = time.perf_counter()
    response = await client.post(
        "/ask",
        headers=headers,
        json={
            "question": case["question"],
            "country": case.get("country"),
        },
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    body: dict[str, Any] = {}
    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()

    checks = score_response(case, body, response.status_code, mode)
    total_weight = sum(check.weight for check in checks)
    earned_weight = sum(check.weight for check in checks if check.passed)
    score = (earned_weight / total_weight) * 100 if total_weight else 0.0
    required_ok = all(check.passed for check in checks if check.required)
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []

    return CaseResult(
        case_id=str(case["id"]),
        question=str(case["question"]),
        country=case.get("country"),
        score=score,
        passed=required_ok,
        status_code=response.status_code,
        latency_ms=latency_ms,
        confidence=str(body.get("confidence") or "n/a"),
        answer=_response_answer(body, response.text),
        source_ids=_retrieved_source_ids(sources),
        source_count=len(sources),
        expected_documents=[str(item) for item in case.get("expected_documents") or []],
        expected_source_ids=[str(item) for item in case.get("expected_source_ids") or []],
        checks=checks,
    )


def score_response(
    case: dict[str, Any],
    body: dict[str, Any],
    status_code: int,
    mode: str,
) -> list[Check]:
    checks = [
        Check(
            name="api_response",
            passed=status_code == 200,
            detail=f"status={status_code}",
            weight=10,
            required=True,
        )
    ]
    if status_code != 200:
        return checks

    answerable = bool(case.get("answerable", True))
    answer = str(body.get("answer") or "")
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []
    confidence = str(body.get("confidence") or "")

    if not answerable:
        insufficient = "could not find sufficient evidence" in _normalise(answer)
        checks.extend(
            [
                Check("low_confidence", confidence == "low", f"confidence={confidence}", 25, True),
                Check("insufficient_evidence", insufficient, answer[:140], 45, True),
                Check("no_sources", not sources, f"sources={len(sources)}", 20),
            ]
        )
        return checks

    checks.append(
        Check("sources_present", bool(sources), f"sources={len(sources)}", 15, required=True)
    )
    checks.append(score_source_shape(sources))
    checks.append(score_expected_documents(case, sources))
    if case.get("expected_source_ids"):
        checks.append(score_expected_source_ids(case, sources))
        checks.append(score_source_id_precision(case, sources))

    source_text = " ".join(str(source.get("snippet") or "") for source in sources)
    source_groups = case.get("expected_source_concepts") or []
    checks.append(
        score_concepts(
            name="source_concepts",
            text=source_text,
            groups=source_groups,
            minimum=int(case.get("min_source_concepts_found", 1)),
            weight=20,
            required=False,
        )
    )

    answer_groups = case.get("expected_answer_concepts") or []
    if answer_groups:
        answer_check_text = answer if mode == "live" else f"{answer} {source_text}"
        check_name = "answer_concepts" if mode == "live" else "answer_concepts_in_sources"
        checks.append(
            score_concepts(
                name=check_name,
                text=answer_check_text,
                groups=answer_groups,
                minimum=int(case.get("min_answer_concepts_found", 1)),
                weight=20,
                required=mode == "live",
            )
        )
    else:
        checks.append(Check("answer_concepts", True, "not configured for this case", 5))

    checks.append(
        Check(
            name="confidence_present",
            passed=confidence in {"high", "medium", "low"},
            detail=f"confidence={confidence}",
            weight=5,
        )
    )
    return checks


def score_source_shape(sources: list[Any]) -> Check:
    if not sources:
        return Check("source_shape", False, "no sources", 10, required=True)

    invalid: list[str] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            invalid.append(f"S{index}: not an object")
            continue
        if not source.get("source_id"):
            invalid.append(f"S{index}: missing source_id")
        if not source.get("document_id"):
            invalid.append(f"S{index}: missing document_id")
        if not source.get("snippet"):
            invalid.append(f"S{index}: missing snippet")
        score = source.get("relevance_score")
        if not isinstance(score, int | float) or not 0.0 <= float(score) <= 1.0:
            invalid.append(f"S{index}: invalid relevance_score")

    return Check(
        name="source_shape",
        passed=not invalid,
        detail="valid" if not invalid else "; ".join(invalid[:3]),
        weight=10,
        required=True,
    )


def score_expected_documents(case: dict[str, Any], sources: list[Any]) -> Check:
    expected = [str(item) for item in case.get("expected_documents") or []]
    if not expected:
        return Check("expected_documents", True, "not configured", 20)

    found = [
        document_id
        for document_id in expected
        if any(source_matches_document(source, document_id) for source in sources)
    ]
    minimum = int(case.get("min_expected_documents_found", len(expected)))
    passed = len(found) >= minimum
    return Check(
        name="expected_documents",
        passed=passed,
        detail=f"found={found or []}; expected={expected}; minimum={minimum}",
        weight=25,
        required=True,
    )


def score_expected_source_ids(case: dict[str, Any], sources: list[Any]) -> Check:
    expected = [str(item) for item in case.get("expected_source_ids") or []]
    if not expected:
        return Check("source_id_recall", True, "not configured", 0)

    retrieved = _retrieved_source_ids(sources)
    found = [source_id for source_id in expected if source_id in retrieved]
    minimum = int(case.get("min_expected_source_ids_found", len(expected)))
    passed = len(found) >= minimum
    return Check(
        name="source_id_recall",
        passed=passed,
        detail=f"found={found or []}; expected={expected}; minimum={minimum}",
        weight=20,
        required=False,
    )


def score_source_id_precision(case: dict[str, Any], sources: list[Any]) -> Check:
    relevant = {
        str(item)
        for item in (
            (case.get("expected_source_ids") or [])
            + (case.get("acceptable_source_ids") or [])
            + (case.get("relevant_source_ids") or [])
        )
    }
    if not relevant:
        return Check("source_id_precision", True, "not configured", 0)

    retrieved = _retrieved_source_ids(sources)
    if not retrieved:
        return Check("source_id_precision", False, "no retrieved/cited source IDs", 10)

    relevant_retrieved = [source_id for source_id in retrieved if source_id in relevant]
    precision = len(relevant_retrieved) / len(retrieved)
    threshold = float(case.get("min_source_id_precision", 0.5))
    return Check(
        name="source_id_precision",
        passed=precision >= threshold,
        detail=(
            f"precision={precision:.2f}; relevant_retrieved={relevant_retrieved}; "
            f"retrieved={retrieved}; threshold={threshold:.2f}"
        ),
        weight=10,
        required=False,
    )


def source_matches_document(source: Any, expected_document: str) -> bool:
    if not isinstance(source, dict):
        return False
    expected = _normalise(expected_document)
    candidates = [
        source.get("external_document_id"),
        source.get("document_title"),
        source.get("document_id"),
    ]
    return any(expected in _normalise(str(candidate or "")) for candidate in candidates)


def _retrieved_source_ids(sources: list[Any]) -> list[str]:
    source_ids: list[str] = []
    for source in sources:
        if isinstance(source, dict) and source.get("source_id"):
            source_ids.append(str(source["source_id"]))
    return source_ids


def score_concepts(
    *,
    name: str,
    text: str,
    groups: list[Any],
    minimum: int,
    weight: int,
    required: bool,
) -> Check:
    if not groups:
        return Check(name, True, "not configured", weight, required=False)

    matched = 0
    missing: list[str] = []
    for group in groups:
        variants = [str(item) for item in group]
        if any(_contains_variant(text, variant) for variant in variants):
            matched += 1
        else:
            missing.append(" / ".join(variants[:3]))

    passed = matched >= minimum
    return Check(
        name=name,
        passed=passed,
        detail=f"matched={matched}/{len(groups)}; minimum={minimum}; missing={missing[:3]}",
        weight=weight,
        required=required,
    )


def _contains_variant(text: str, variant: str) -> bool:
    return _normalise(variant) in _normalise(text)


def _normalise(value: str) -> str:
    lowered = value.casefold()
    lowered = lowered.replace("-", " ")
    lowered = lowered.replace("_", " ")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _response_answer(body: dict[str, Any], fallback_text: str) -> str:
    answer = body.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer

    detail = body.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail
    if detail is not None:
        return json.dumps(detail, sort_keys=True)

    return fallback_text


def _short_text(value: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if not compact:
        return "n/a"
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


def _format_items(items: list[Any], *, limit: int = 6, empty: str = "none") -> str:
    if not items:
        return empty

    values = [str(item) for item in items]
    visible = ", ".join(values[:limit])
    remaining = len(values) - limit
    if remaining > 0:
        return f"{visible}, +{remaining} more"
    return visible


def _case_status(result: CaseResult, min_case_score: float) -> str:
    return "PASS" if result.score >= min_case_score and result.passed else "FAIL"


def _case_failure_reason(result: CaseResult, min_case_score: float) -> str:
    reasons: list[str] = []
    if result.score < min_case_score:
        reasons.append(f"score below {min_case_score:.1f}%")
    if not result.passed:
        reasons.append("required check failed")
    return "; ".join(reasons) if reasons else "meets thresholds"


def print_report(
    results: list[CaseResult],
    *,
    min_average_score: float,
    min_case_score: float,
    verbose: bool,
) -> bool:
    average = sum(result.score for result in results) / len(results)
    case_failures = [
        result for result in results if _case_status(result, min_case_score) == "FAIL"
    ]
    case_passes = len(results) - len(case_failures)
    passed = average >= min_average_score and not case_failures

    print("\nRAG evaluation report")
    print("=====================")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    print(f"Cases: {len(results)} ({case_passes} pass, {len(case_failures)} fail)")
    print(f"Average score: {average:.1f}% (required >= {min_average_score:.1f}%)")
    print(f"Case score threshold: {min_case_score:.1f}%")
    if case_failures:
        print(f"Failed cases: {_format_items([result.case_id for result in case_failures])}")

    print("\nCase results")
    print("------------")

    for result in results:
        status = _case_status(result, min_case_score)
        passed_checks = sum(1 for check in result.checks if check.passed)
        failed_checks = [check for check in result.checks if not check.passed]

        print(f"\n[{status}] {result.case_id}")
        print(
            f"  Score: {result.score:.1f}% | latency: {result.latency_ms} ms | "
            f"checks: {passed_checks}/{len(result.checks)}"
        )
        if status == "FAIL":
            print(f"  Reason: {_case_failure_reason(result, min_case_score)}")
        print(f"  Question: {_short_text(result.question, 160)}")
        if result.country:
            print(f"  Country: {result.country}")
        print(
            f"  Response: status {result.status_code}, confidence {result.confidence}, "
            f"sources {result.source_count}"
        )
        print(f"  Retrieved source IDs: {_format_items(result.source_ids)}")
        if result.expected_documents:
            print(f"  Expected documents: {_format_items(result.expected_documents)}")
        if result.expected_source_ids:
            print(f"  Expected source IDs: {_format_items(result.expected_source_ids)}")
        print(f"  Answer: {_short_text(result.answer)}")

        checks_to_print = result.checks if verbose else failed_checks
        if checks_to_print:
            label = "Checks" if verbose else "Failed checks"
            print(f"  {label}:")
            for check in checks_to_print:
                marker = "ok" if check.passed else "fail"
                required = ", required" if check.required else ""
                print(
                    f"    - {marker} {check.name}{required}: "
                    f"{_short_text(check.detail, 180)}"
                )
        elif not verbose:
            print("  Checks: all passed")

    return passed


def main() -> int:
    args = parse_args()
    min_average = args.min_average_score
    if min_average is None:
        min_average = 70.0 if args.mode == "mock" else 80.0
    min_case = args.min_case_score
    if min_case is None:
        min_case = 55.0 if args.mode == "mock" else 70.0

    results = asyncio.run(run_evaluation(args))
    passed = print_report(
        results,
        min_average_score=min_average,
        min_case_score=min_case,
        verbose=args.verbose,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
