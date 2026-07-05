"""Run a small RAG quality evaluation against the candidate dataset.

This is intentionally a rule-based evaluator, not an LLM judge. It checks
whether known questions retrieve the expected source documents, return valid
source cards, and mention expected evidence concepts. In live mode it also
checks answer concepts where the golden file supplies them.

Run from the repository root:

    python scripts/evaluate_rag.py --mode mock
    python scripts/evaluate_rag.py --mode live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
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

# Keep app.main import safe even if a local backend/.env contains a strict auth
# mode. The evaluator passes its own explicit Settings object below.
os.environ["AUTH_MODE"] = "disabled"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.database import _normalise_async_database_url  # noqa: E402

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
    score: float
    passed: bool
    latency_ms: int
    checks: list[Check]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval and answer quality.")
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default="mock",
        help="mock checks the local pipeline; live uses Gemini for semantic answer quality.",
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
    logging.getLogger("market_access_evidence_assistant").setLevel(logging.WARNING)

    with tempfile.TemporaryDirectory(
        prefix="rag-eval-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        async with temporary_postgres_database(args.database_url) as database_url:
            temp_root = Path(temp_dir)
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
async def temporary_postgres_database(explicit_url: str | None):
    base_url = make_url(_normalise_async_database_url(_base_evaluation_database_url(explicit_url)))
    database_name = f"eval_{uuid4().hex}"
    maintenance_database = os.environ.get("EVAL_POSTGRES_MAINTENANCE_DB", "postgres")
    maintenance_url = base_url.set(database=maintenance_database)
    evaluation_url = base_url.set(database=database_name)

    admin_engine = create_async_engine(str(maintenance_url), isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f"CREATE DATABASE {_quote_identifier(database_name)}"))
    except Exception as exc:
        await admin_engine.dispose()
        raise SystemExit(f"Evaluation requires reachable Postgres: {exc}") from exc

    try:
        yield str(evaluation_url)
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


async def seed_dataset(client: AsyncClient, headers: dict[str, str], dataset_path: Path) -> None:
    print("Seeding candidate dataset through POST /documents")
    for filename, country, country_code, language in DATASET_FILES:
        content = read_dataset_file(dataset_path, filename)
        mime_type = "application/pdf" if filename.endswith(".pdf") else "text/plain"
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

    return CaseResult(
        case_id=str(case["id"]),
        score=score,
        passed=required_ok,
        latency_ms=latency_ms,
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


def print_report(
    results: list[CaseResult],
    *,
    min_average_score: float,
    min_case_score: float,
    verbose: bool,
) -> bool:
    average = sum(result.score for result in results) / len(results)
    case_failures = [result for result in results if result.score < min_case_score or not result.passed]
    passed = average >= min_average_score and not case_failures

    print("\nRAG evaluation report")
    print("---------------------")
    print(f"Cases: {len(results)}")
    print(f"Average score: {average:.1f}%")
    print(f"Minimum average score: {min_average_score:.1f}%")
    print(f"Minimum case score: {min_case_score:.1f}%")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    print("")

    for result in results:
        status = "PASS" if result.score >= min_case_score and result.passed else "FAIL"
        print(f"{status} {result.case_id}: {result.score:.1f}% ({result.latency_ms} ms)")
        if verbose or status == "FAIL":
            for check in result.checks:
                marker = "ok" if check.passed else "fail"
                print(f"  - {marker} {check.name}: {check.detail}")

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
