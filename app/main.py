from __future__ import annotations

import logging
import hashlib
import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.logging_utils import setup_file_logging
from app.search_logging import search_hit_log_items
from app.time_utils import KST, as_kst, kst_naive_iso, now_kst
from app.schemas import (
    ChunkListResponse,
    DeleteResponse,
    DocumentListResponse,
    DocumentRegisterRequest,
    DocumentRegisterResponse,
    DocumentUploadResponse,
    DocumentUpdateRequest,
    HealthResponse,
    LogBatchIndexRequest,
    LogBatchIndexResponse,
    LogListResponse,
    LogIndexRequest,
    LogIndexResponse,
    LogRetentionDeleteRequest,
    LogRetentionDeleteResponse,
    MiddlewareAnalyzeRequest,
    MiddlewareAnalyzeResponse,
    MsgidSimilarityAnalyzeRequest,
    MsgidSimilarityAnalyzeResponse,
    MsgidSimilarityAttachmentResult,
    MsgidSimilarityBodyResult,
    MsgidSimilarityMatchResult,
    ReviewItem,
    ReviewListResponse,
    ReviewRequest,
    ReviewResponse,
    SearchDocumentsRequest,
    SearchLogsByTextRequest,
    SearchLogsRequest,
    SearchResponse,
    SimilarityHit,
    StatsResponse,
)
from app.similarity_engine import get_engine
from app.similarity_engine.config import load_config
from app.similarity_engine.document_extractor import (
    ARCHIVE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    UPLOAD_EXTENSIONS,
    detect_extension,
    extract_archive_documents,
    extract_text,
)
from app.similarity_engine.ems_source import build_ems_log_rows, read_ems_source
from app.version import APP_VERSION


setup_file_logging()
logger = logging.getLogger("similarity.api")

app = FastAPI(title="XCN Similarity", version=APP_VERSION)
ADMIN_DIR = Path(__file__).resolve().parent / "admin"
_SECURITY_INSIGHT_CACHE: dict[str, object] = {"ts": 0.0, "data": None}
_SECURITY_INSIGHT_WORKER_STARTED = False
_SECURITY_INSIGHT_WORKER_LOCK = threading.Lock()
_CLEANUP_WORKER_STARTED = False
_CLEANUP_WORKER_LOCK = threading.Lock()
if load_config().admin_ui_enabled and (ADMIN_DIR / "static").is_dir():
    app.mount("/admin/static", StaticFiles(directory=ADMIN_DIR / "static"), name="admin-static")


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http request failed request_id=%s method=%s path=%s client=%s elapsed_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            request.client.host if request.client else None,
            _elapsed_ms(started),
        )
        raise
    response.headers["x-request-id"] = request_id
    logger.info(
        "http request completed request_id=%s method=%s path=%s status=%d client=%s elapsed_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        request.client.host if request.client else None,
        _elapsed_ms(started),
    )
    return response


@app.on_event("startup")
def start_security_insight_worker():
    global _SECURITY_INSIGHT_WORKER_STARTED
    config = load_config()
    if not config.security_insight_enabled:
        logger.info("security insight worker disabled product_mode=%s", config.product_mode)
        return
    with _SECURITY_INSIGHT_WORKER_LOCK:
        if _SECURITY_INSIGHT_WORKER_STARTED:
            return
        _SECURITY_INSIGHT_WORKER_STARTED = True
    thread = threading.Thread(target=_security_insight_worker_loop, name="security-insight-worker", daemon=True)
    thread.start()


@app.on_event("startup")
def start_cleanup_worker():
    global _CLEANUP_WORKER_STARTED
    config = load_config()
    if not config.cleanup_enabled:
        logger.info("cleanup worker disabled")
        return
    with _CLEANUP_WORKER_LOCK:
        if _CLEANUP_WORKER_STARTED:
            return
        _CLEANUP_WORKER_STARTED = True
    thread = threading.Thread(target=_cleanup_worker_loop, name="cleanup-worker", daemon=True)
    thread.start()


@app.get("/admin", include_in_schema=False)
def admin():
    _require_admin_ui_enabled()
    return RedirectResponse(url="/admin/")


@app.get("/admin/", include_in_schema=False)
def admin_index():
    _require_admin_ui_enabled()
    return FileResponse(ADMIN_DIR / "index.html")


@app.get("/admin/{asset_path:path}", include_in_schema=False)
def admin_asset(asset_path: str):
    _require_admin_ui_enabled()
    path = (ADMIN_DIR / asset_path).resolve()
    try:
        path.relative_to(ADMIN_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not path.is_file() or path.name == "index.html":
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)


def _require_admin_ui_enabled() -> None:
    if not load_config().admin_ui_enabled:
        raise HTTPException(status_code=404, detail="admin UI disabled")


def _require_manual_review_enabled() -> None:
    if not load_config().manual_review_enabled:
        raise HTTPException(status_code=404, detail="manual review disabled")


def _require_security_insight_enabled() -> None:
    if not load_config().security_insight_enabled:
        raise HTTPException(status_code=404, detail="security insight disabled")


@app.get("/health", response_model=HealthResponse)
def health():
    config = load_config()
    checks: dict[str, str] = {}
    try:
        engine = get_engine()
        engine.catalog.ping()
        checks["mongodb"] = "ok"
        engine.store.ping()
        checks["milvus"] = "ok"
    except Exception as exc:
        logger.exception("health dependency check failed checks=%s", checks)
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "checks": checks, "error": str(exc)[:300]}) from exc
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        vector_backend="milvus",
        embedder_backend=config.embedder_backend,
        embedding_model=Path(config.embedding_model_path).name or config.embedding_model_path or "hash",
        embedding_dim=config.embedding_dim,
        catalog_backend="mongodb",
        catalog_database=config.catalog_database,
        checked_at=now_kst(),
        checks=checks,
    )


@app.post("/similarity/documents", response_model=DocumentRegisterResponse)
def register_document(req: DocumentRegisterRequest):
    engine = get_engine()
    info = engine.register_document(
        title=req.title,
        text=req.text,
        owner=None,
        department=None,
        security_level=_normalize_document_security_level(req.security_level),
        metadata=_strip_document_registration_metadata(req.metadata),
    )
    logger.info("document indexed document_id=%s chunks=%d title=%s", info.document_id, info.chunk_count, info.title)
    return DocumentRegisterResponse(success=True, status=200, data=info)


@app.post("/similarity/documents/upload", response_model=DocumentUploadResponse)
def upload_document(
    file: list[UploadFile] = File(...),
    title: str | None = Form(None),
    security_level: str | None = Form(None),
    retain_file: bool | None = Form(None),
    metadata_json: str = Form("{}"),
):
    op_started = time.perf_counter()
    config = load_config()
    retain_file = config.upload_retain_original if retain_file is None else bool(retain_file)
    files = [item for item in (file or []) if item and item.filename]
    if not files:
        raise HTTPException(status_code=400, detail="업로드할 파일을 선택하세요.")
    if len(files) > config.multi_upload_max_files:
        raise HTTPException(status_code=413, detail=f"한 번에 최대 {config.multi_upload_max_files}개 파일까지 업로드할 수 있습니다.")

    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Metadata JSON 형식이 올바르지 않습니다: {exc.msg}") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="Metadata JSON은 object 형식이어야 합니다.")

    upload_dir = Path(config.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    document_items: list[dict[str, object]] = []
    total_size = 0
    max_total_bytes = config.max_upload_mb * 1024 * 1024

    try:
        for index, upload in enumerate(files, 1):
            items, saved_path, upload_size = _save_and_extract_upload_documents(
                upload,
                upload_dir=upload_dir,
                prefix=f"{index:03d}",
                max_bytes=max_total_bytes - total_size,
                config=config,
            )
            total_size += upload_size
            if total_size > max_total_bytes:
                raise HTTPException(status_code=413, detail=f"업로드 파일 합계는 최대 {config.max_upload_mb}MB까지 가능합니다.")
            saved_paths.append(saved_path)
            document_items.extend(items)
    except HTTPException:
        if not retain_file:
            for path in saved_paths:
                _unlink_quietly(path)
        raise
    except ValueError as exc:
        if not retain_file:
            for path in saved_paths:
                _unlink_quietly(path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if not retain_file:
            for path in saved_paths:
                _unlink_quietly(path)
        logger.exception("document extraction failed files=%s", [item.filename for item in files])
        raise HTTPException(status_code=500, detail=f"문서 텍스트 추출 중 오류가 발생했습니다: {exc}") from exc

    if not document_items:
        if not retain_file:
            for path in saved_paths:
                _unlink_quietly(path)
        raise HTTPException(status_code=400, detail="문서에서 추출된 텍스트가 없습니다.")

    registered = []
    is_multi = len(document_items) > 1
    try:
        engine = get_engine()
        for index, item in enumerate(document_items, 1):
            item_meta = dict(item["metadata"])
            original_name = str(item_meta["file_name"])
            checksum_sha256 = str(item_meta.get("file_checksum_sha256") or "")
            item_title = (title or "").strip() if not is_multi else ""
            if not item_title:
                item_title = _stem_without_archive_suffix(original_name) or original_name
            merged_metadata = {
                **metadata,
                **item_meta,
                "source": "upload",
                "checksum_sha256": checksum_sha256,
                "file_retained": bool(retain_file),
                "upload_path": str(item["saved_path"]) if retain_file else None,
                "multi_file": is_multi,
                "file_count": len(document_items),
                "batch_index": index,
            }
            info = engine.register_document(
                title=item_title.strip(),
                text=str(item["text"]),
                owner=None,
                department=None,
                security_level=_normalize_document_security_level(security_level),
                metadata=_strip_document_registration_metadata(merged_metadata),
            )
            registered.append(info)
            logger.info(
                "document upload item indexed document_id=%s file=%s title=%s chars=%d chunks=%d text_filter=%s upload_path=%s",
                info.document_id,
                item_meta.get("file_name"),
                info.title,
                len(str(item["text"])),
                info.chunk_count,
                item_meta.get("text_filter"),
                item["saved_path"],
            )
    finally:
        if not retain_file:
            for path in saved_paths:
                _unlink_quietly(path)
    logger.info(
        "documents uploaded and indexed count=%d files=%d total_bytes=%d elapsed_ms=%.1f",
        len(registered),
        len(files),
        total_size,
        _elapsed_ms(op_started),
    )
    return DocumentUploadResponse(
        success=True,
        status=200,
        data=registered,
        primary_document_id=registered[0].document_id if registered else None,
    )


def _save_and_extract_upload_documents(
    file: UploadFile,
    *,
    upload_dir: Path,
    prefix: str,
    max_bytes: int,
    config,
) -> tuple[list[dict[str, object]], Path, int]:
    op_started = time.perf_counter()
    original_name = Path(file.filename or "").name
    suffix = detect_extension(original_name)
    if suffix not in UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {suffix or '(none)'}. 지원 형식: {_supported_upload_hint()}")
    if max_bytes <= 0:
        raise HTTPException(status_code=413, detail=f"업로드 파일 합계는 최대 {config.max_upload_mb}MB까지 가능합니다.")

    safe_stem = _safe_filename(_stem_without_archive_suffix(original_name) or "document")
    saved_name = f"{now_kst().strftime('%Y%m%d%H%M%S')}_{prefix}_{safe_stem}{suffix}"
    saved_path = upload_dir / saved_name
    size = _save_upload(file, saved_path, max_bytes=max_bytes)
    checksum_sha256 = _sha256_file(saved_path)
    logger.info(
        "upload file saved original=%s saved=%s ext=%s size=%d sha256=%s elapsed_ms=%.1f",
        original_name,
        saved_path,
        suffix,
        size,
        checksum_sha256,
        _elapsed_ms(op_started),
    )

    if suffix in ARCHIVE_EXTENSIONS:
        extract_started = time.perf_counter()
        archive_documents, archive_meta = extract_archive_documents(
            saved_path,
            max_files=config.archive_max_files,
            max_total_bytes=config.archive_max_total_mb * 1024 * 1024,
            max_member_bytes=config.archive_max_member_mb * 1024 * 1024,
        )
        items = []
        for doc in archive_documents:
            meta = {
                "file_name": doc["file_name"],
                "file_ext": doc["file_ext"],
                "file_size": doc["file_size"],
                "file_checksum_sha256": doc["file_checksum_sha256"],
                "archive": True,
                "archive_file_name": original_name,
                "archive_file_ext": suffix,
                "archive_file_size": size,
                "archive_checksum_sha256": checksum_sha256,
                "archive_member_name": doc["archive_member_name"],
                "text_filter": "xutf_8",
                **archive_meta,
            }
            items.append({"text": doc["text"], "metadata": meta, "saved_path": saved_path})
            logger.info(
                "archive member extracted archive=%s member=%s chars=%d ext=%s size=%s",
                original_name,
                doc["archive_member_name"],
                len(str(doc["text"])),
                doc["file_ext"],
                doc["file_size"],
            )
        logger.info(
            "archive extraction completed archive=%s members=%d elapsed_ms=%.1f skipped_failed=%s skipped_large=%s skipped_unsupported=%s",
            original_name,
            len(items),
            _elapsed_ms(extract_started),
            archive_meta.get("archive_skipped_failed"),
            archive_meta.get("archive_skipped_large"),
            archive_meta.get("archive_skipped_unsupported"),
        )
        return items, saved_path, size
    else:
        extract_started = time.perf_counter()
        text = extract_text(saved_path)
    if not text.strip():
        raise ValueError(f"{original_name} 파일에서 추출된 텍스트가 없습니다.")
    logger.info(
        "upload document extracted original=%s saved=%s chars=%d ext=%s text_filter=%s elapsed_ms=%.1f",
        original_name,
        saved_path,
        len(text),
        suffix,
        "xutf_8",
        _elapsed_ms(extract_started),
    )
    meta = {
        "file_name": original_name,
        "file_ext": suffix,
        "file_size": size,
        "file_checksum_sha256": checksum_sha256,
        "archive": False,
        "text_filter": "xutf_8",
    }
    return [{"text": text, "metadata": meta, "saved_path": saved_path}], saved_path, size


@app.get("/similarity/documents", response_model=DocumentListResponse)
def list_documents():
    return DocumentListResponse(success=True, status=200, data=get_engine().list_documents())


@app.get("/similarity/documents/search", response_model=DocumentListResponse)
def search_documents_catalog(
    query: str | None = None,
    limit: int = 30,
    offset: int = 0,
    security_level: str | None = None,
):
    docs, next_offset = get_engine().search_document_catalog(
        query=query,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        security_level=_normalize_document_security_level(security_level) if str(security_level or "").strip() else None,
    )
    return DocumentListResponse(success=True, status=200, data=docs, next_offset=next_offset)


@app.patch("/similarity/documents/{document_id}", response_model=DocumentRegisterResponse)
def update_document(document_id: str, req: DocumentUpdateRequest):
    info = get_engine().update_document(
        document_id,
        title=req.title.strip() if req.title is not None else None,
        owner=None,
        department=None,
        security_level=_normalize_document_security_level(req.security_level),
        metadata=_strip_document_registration_metadata(req.metadata),
    )
    if info is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    logger.info("document updated document_id=%s title=%s", info.document_id, info.title)
    return DocumentRegisterResponse(success=True, status=200, data=info)


def _extract_uploaded_text(file: UploadFile, *, prefix: str) -> tuple[str, dict[str, object]]:
    op_started = time.perf_counter()
    config = load_config()
    original_name = Path(file.filename or "").name
    suffix = detect_extension(original_name)
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {suffix or '(none)'}")
    upload_dir = Path(config.upload_dir) / "search"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _safe_filename(Path(original_name).stem or "query")
    saved_name = f"{now_kst().strftime('%Y%m%d%H%M%S')}_{prefix}_{safe_stem}{suffix}"
    saved_path = upload_dir / saved_name
    size = _save_upload(file, saved_path, max_bytes=config.max_upload_mb * 1024 * 1024)
    checksum_sha256 = _sha256_file(saved_path)
    try:
        text = extract_text(saved_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("search upload extraction failed filename=%s", original_name)
        raise HTTPException(status_code=500, detail=f"검색 파일 텍스트 추출 중 오류가 발생했습니다: {exc}") from exc
    finally:
        try:
            saved_path.unlink()
        except Exception:
            pass
    if not text.strip():
        raise HTTPException(status_code=400, detail="파일에서 추출된 텍스트가 없습니다.")
    logger.info(
        "search upload extracted prefix=%s file=%s ext=%s size=%d sha256=%s chars=%d elapsed_ms=%.1f",
        prefix,
        original_name,
        suffix,
        size,
        checksum_sha256,
        len(text),
        _elapsed_ms(op_started),
    )
    return text, {"file_name": original_name, "file_ext": suffix, "file_size": size, "file_checksum_sha256": checksum_sha256}


def _supported_upload_hint() -> str:
    single = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    archive = ", ".join(sorted(ARCHIVE_EXTENSIONS))
    return f"단일 문서({single}), 압축({archive})"


def _normalize_document_security_level(value: str | None) -> str:
    return "일반" if str(value or "").strip() == "일반" else "대외비"


def _strip_document_registration_metadata(metadata: dict[str, object] | None) -> dict[str, object]:
    cleaned = dict(metadata or {})
    for key in ("owner", "department", "description"):
        cleaned.pop(key, None)
    return cleaned


def _stem_without_archive_suffix(name: str) -> str:
    value = str(name or "")
    lower = value.lower()
    for suffix in sorted(ARCHIVE_EXTENSIONS, key=len, reverse=True):
        if lower.endswith(suffix):
            return value[: -len(suffix)]
    return Path(value).stem


def _save_upload(file: UploadFile, path: Path, *, max_bytes: int) -> int:
    total = 0
    try:
        with path.open("wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    try:
                        path.unlink()
                    except Exception:
                        pass
                    raise HTTPException(status_code=413, detail=f"업로드 파일은 최대 {max_bytes // 1024 // 1024}MB까지 가능합니다.")
                out.write(chunk)
    finally:
        file.file.close()
    return total


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9가-힣._-]+", "_", value).strip("._-")
    return cleaned[:120] or "document"


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, str(default))).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _review_store_path() -> Path:
    configured = os.getenv("SIM_REVIEW_STORE_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path(load_config().upload_dir).parent / "reviews" / "similarity_reviews.json"


def _load_legacy_review_file() -> list[dict[str, object]]:
    path = _review_store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("failed to load legacy review store path=%s", path)
        return []
    if not isinstance(data, dict):
        return []
    items: list[dict[str, object]] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        item = dict(value)
        item["match_key"] = str(item.get("match_key") or key)
        items.append(item)
    return items


def _migrate_legacy_reviews_to_mongo() -> None:
    items = _load_legacy_review_file()
    if not items:
        return
    try:
        imported = get_engine().catalog.import_reviews(items)
    except Exception:
        logger.exception("failed to migrate legacy review store to MongoDB")
        return
    if imported:
        logger.info("legacy review store migrated to MongoDB imported=%d", imported)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("failed to remove temporary upload file path=%s", path, exc_info=True)


@app.get("/similarity/documents/{document_id}/chunks", response_model=ChunkListResponse)
def list_document_chunks(document_id: str, limit: int = 50, offset: str | None = None):
    chunks, next_offset = get_engine().list_document_chunks(document_id, limit=max(1, min(limit, 200)), offset=offset)
    return ChunkListResponse(success=True, status=200, data=chunks, next_offset=next_offset)


@app.delete("/similarity/documents/{document_id}", response_model=DeleteResponse)
def delete_document(document_id: str):
    removed = get_engine().delete_document(document_id)
    if removed == 0:
        raise HTTPException(status_code=404, detail="document not found")
    logger.info("document deleted document_id=%s removed_chunks=%d", document_id, removed)
    return DeleteResponse(success=True, status=200, document_id=document_id)


@app.post("/similarity/logs", response_model=LogIndexResponse)
def index_log(req: LogIndexRequest):
    metadata = {
        **req.metadata,
        "svc": req.svc,
        "user_id": req.user_id,
        "ctime": kst_naive_iso(req.ctime) if req.ctime else None,
    }
    info = get_engine().index_log(log_id=req.log_id, text=req.text, metadata=metadata)
    logger.info("log indexed log_id=%s chunks=%d", info.log_id, info.chunk_count)
    return LogIndexResponse(success=True, status=200, data=info)


@app.post("/similarity/logs/batch", response_model=LogBatchIndexResponse)
def index_logs_batch(req: LogBatchIndexRequest):
    rows = [
        {
            "log_id": item.log_id,
            "text": item.text,
            "metadata": {
                **item.metadata,
                "svc": item.svc,
                "user_id": item.user_id,
                "ctime": kst_naive_iso(item.ctime) if item.ctime else None,
            },
        }
        for item in req.items
    ]
    infos = get_engine().index_logs(rows)
    logger.info("logs batch indexed count=%d chunks=%d", len(infos), sum(info.chunk_count for info in infos))
    return LogBatchIndexResponse(success=True, status=200, data=infos)


@app.post("/similarity/middleware/analyze", response_model=MiddlewareAnalyzeResponse)
def analyze_from_middleware(req: MiddlewareAnalyzeRequest):
    op_started = time.perf_counter()
    source_id = str(req.id or req.source_id or "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="_id or source_id is required")
    fetch_started = time.perf_counter()
    engine, rows = _ems_rows_for_source(
        svc=req.svc,
        source_id=source_id,
        source_payload=req.source_payload,
        metadata=req.metadata,
    )
    fetch_ms = _elapsed_ms(fetch_started)

    processing: dict[str, object] = {
        "partial": False,
        "timeout": False,
        "limit_reached": False,
        "timeout_sec": int(engine.config.middleware_timeout_sec or 60),
        "max_total_chars": int(engine.config.max_middleware_chars or 0),
        "max_total_chunks": int(engine.config.max_middleware_chunks or 0),
        "max_item_chars": int(engine.config.max_middleware_item_chars or 0),
        "source_chars": _rows_text_chars(rows),
        "source_rows": len(rows),
    }
    if not rows:
        result = _empty_middleware_similarity_result(source_id)
        infos = []
        index_ms = 0.0
    else:
        index_started = time.perf_counter()
        deadline = op_started + max(1, int(engine.config.middleware_timeout_sec or 60))
        infos, index_summary = engine.index_logs(
            rows,
            deadline=deadline,
            max_total_chunks=max(1, int(engine.config.max_middleware_chunks or engine.config.max_log_chunks)),
            max_total_chars=max(1, int(engine.config.max_middleware_chars or 2_000_000)),
            max_item_chars=max(1, int(engine.config.max_middleware_item_chars or 800_000)),
            return_summary=True,
        )
        processing.update(index_summary)
        index_ms = _elapsed_ms(index_started)
        result = engine.catalog.get_similarity_result(source_id) or _empty_middleware_similarity_result(source_id)
        _annotate_middleware_similarity_result(result, processing)
    response_result = _sanitize_middleware_similarity_result(result)
    delivered = False
    callback_url = _middleware_callback_url(req.callback_url, engine.config)
    if callback_url:
        delivered = _deliver_middleware_result(
            url=callback_url,
            payload=response_result,
            msgid=source_id,
            engine=engine,
        )
    logger.info(
        "middleware analyze processed svc=%s source_id=%s logs=%d chunks=%d chars=%d rows=%s delivered=%s partial=%s timeout=%s limit_reached=%s stop_reason=%s fetch_ms=%.1f index_ms=%.1f total_ms=%.1f",
        req.svc,
        source_id,
        len(infos),
        sum(info.chunk_count for info in infos),
        _rows_text_chars(rows),
        _rows_source_summary(rows),
        delivered,
        processing.get("partial"),
        processing.get("timeout"),
        processing.get("limit_reached"),
        processing.get("stop_reason"),
        fetch_ms,
        index_ms,
        _elapsed_ms(op_started),
    )
    message = "PARTIAL" if processing.get("partial") else ("NO_RESULT" if not rows else "OK")
    reason = None
    if processing.get("timeout"):
        reason = "middleware analysis exceeded timeout; partial processed data was saved"
    elif processing.get("limit_reached"):
        reason = "middleware analysis exceeded configured size/chunk limit; partial processed data was saved"
    elif not rows:
        reason = "EMS source message not found or no body/attachment text"
    return MiddlewareAnalyzeResponse(
        success=True,
        status=200,
        svc=req.svc,
        source_id=source_id,
        message=message,
        reason=reason,
        indexed_logs=len(infos),
        indexed_chunks=sum(info.chunk_count for info in infos),
        result_delivered=delivered,
        result=response_result,
    )


@app.post("/similarity/analyze/msgid", response_model=MsgidSimilarityAnalyzeResponse, response_model_exclude_none=True)
def analyze_similarity_by_msgid(req: MsgidSimilarityAnalyzeRequest):
    op_started = time.perf_counter()
    msgid = str(req.msgid or req.id or "").strip()
    if not msgid:
        raise HTTPException(status_code=400, detail="msgid or _id is required")
    fetch_started = time.perf_counter()
    engine, rows = _ems_rows_for_source(
        svc="",
        source_id=msgid,
        source_payload=req.source_payload,
        metadata=req.metadata,
    )
    fetch_ms = _elapsed_ms(fetch_started)
    if not rows:
        logger.info("msgid similarity analyze no source text msgid=%s fetch_ms=%.1f total_ms=%.1f", msgid, fetch_ms, _elapsed_ms(op_started))
        return MsgidSimilarityAnalyzeResponse(
            success=True,
            status=200,
            msgid=msgid,
            message="NO_RESULT",
            reason="EMS source message not found or no body/attachment text",
            body=None,
            attachments=[],
        )
    index_started = time.perf_counter()
    deadline = op_started + max(1, int(engine.config.middleware_timeout_sec or 60))
    infos, processing = engine.index_logs(
        rows,
        deadline=deadline,
        max_total_chunks=max(1, int(engine.config.max_middleware_chunks or engine.config.max_log_chunks)),
        max_total_chars=max(1, int(engine.config.max_middleware_chars or 2_000_000)),
        max_item_chars=max(1, int(engine.config.max_middleware_item_chars or 800_000)),
        return_summary=True,
    )
    index_ms = _elapsed_ms(index_started)
    result = engine.catalog.get_similarity_result(msgid) or _empty_middleware_similarity_result(msgid)
    processing.update(
        {
            "timeout_sec": int(engine.config.middleware_timeout_sec or 60),
            "max_total_chars": int(engine.config.max_middleware_chars or 0),
            "max_total_chunks": int(engine.config.max_middleware_chunks or 0),
            "max_item_chars": int(engine.config.max_middleware_item_chars or 0),
            "source_chars": _rows_text_chars(rows),
            "source_rows": len(rows),
        }
    )
    _annotate_middleware_similarity_result(result, processing)
    threshold = max(-1.0, min(float(engine.config.similarity_result_min_score), 1.0))
    split_result = _split_msgid_similarity_result(result, threshold=threshold)
    effective_svc = _rows_effective_svc(rows) or req.svc
    no_matches = int(split_result["match_count"]) <= 0
    logger.info(
        "msgid similarity analyze processed msgid=%s svc=%s logs=%d chunks=%d chars=%d rows=%s threshold=%.6f matches=%d partial=%s timeout=%s limit_reached=%s stop_reason=%s fetch_ms=%.1f index_ms=%.1f total_ms=%.1f",
        msgid,
        effective_svc,
        len(infos),
        sum(info.chunk_count for info in infos),
        _rows_text_chars(rows),
        _rows_source_summary(rows),
        threshold,
        split_result["match_count"],
        processing.get("partial"),
        processing.get("timeout"),
        processing.get("limit_reached"),
        processing.get("stop_reason"),
        fetch_ms,
        index_ms,
        _elapsed_ms(op_started),
    )
    message = "PARTIAL" if processing.get("partial") else ("NO_RESULT" if no_matches else "OK")
    reason = None
    if processing.get("timeout"):
        reason = "analysis exceeded timeout; partial processed data was saved"
    elif processing.get("limit_reached"):
        reason = "analysis exceeded configured size/chunk limit; partial processed data was saved"
    elif no_matches:
        reason = "No documents matched the configured similarity threshold"
    return MsgidSimilarityAnalyzeResponse(
        success=True,
        status=200,
        msgid=msgid,
        message=message,
        reason=reason,
        body=split_result["body"],
        attachments=split_result["attachments"],
        processing=processing,
    )


@app.get("/similarity/logs", response_model=LogListResponse)
def list_logs(
    limit: int = 100,
    offset: str | None = None,
    source_type: str | None = None,
    svc: str | None = None,
    user_id: str | None = None,
    order: str = "desc",
):
    normalized_source_type = _normalize_source_type(source_type)
    logs, next_offset = get_engine().list_logs(
        limit=max(1, min(limit, 1000)),
        offset=offset,
        source_type=normalized_source_type,
        svc=svc,
        user_id=user_id,
        order=order,
    )
    return LogListResponse(success=True, status=200, data=logs, next_offset=next_offset)


@app.post("/similarity/logs/delete-by-retention", response_model=LogRetentionDeleteResponse)
def delete_logs_by_retention(req: LogRetentionDeleteRequest):
    try:
        result = get_engine().delete_logs_by_retention(
            svc=req.svc,
            delete_before=req.delete_before,
            dry_run=req.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "logs retention delete dry_run=%s svc=%s delete_before=%s matched_logs=%d matched_chunks=%d catalog_deleted=%d vector_deleted=%d",
        result["dry_run"],
        ",".join(result["svc"]),
        result["delete_before"].isoformat(),
        result["matched_logs"],
        result["matched_chunks"],
        result["catalog_deleted"],
        result["vector_deleted"],
    )
    return LogRetentionDeleteResponse(success=True, status=200, **result)


@app.get("/similarity/logs/{log_id}/chunks", response_model=ChunkListResponse)
def list_log_chunks(log_id: str, limit: int = 50, offset: str | None = None):
    chunks, next_offset = get_engine().list_log_chunks(log_id, limit=max(1, min(limit, 200)), offset=offset)
    return ChunkListResponse(success=True, status=200, data=chunks, next_offset=next_offset)


@app.get("/similarity/results")
def list_similarity_results(
    limit: int = 50,
    offset: int = 0,
    detected: bool | None = None,
    delivery_status: str | None = None,
):
    rows, next_offset = get_engine().catalog.list_similarity_results(
        limit=limit,
        offset=offset,
        detected=detected,
        delivery_status=delivery_status,
    )
    return {"success": True, "status": 200, "data": rows, "next_offset": next_offset}


@app.get("/similarity/results/recent-matches", response_model=SearchResponse)
def recent_stored_similarity_matches(
    limit: int = 50,
    offset: int = 0,
    min_score: float | None = None,
    risk_level: str | None = "high",
):
    config = load_config()
    rows, _ = get_engine().list_recent_similarity_matches(
        limit=limit,
        offset=offset,
        min_score=max(-1.0, min(float(min_score if min_score is not None else config.recent_match_min_score), 1.0)),
        risk_level=risk_level,
    )
    return SearchResponse(success=True, status=200, data=[SimilarityHit(**row) for row in rows])


@app.get("/similarity/results/{msgid}")
def get_similarity_result(msgid: str):
    row = get_engine().catalog.get_similarity_result(msgid)
    if row is None:
        return {
            "success": True,
            "status": 200,
            "message": "NO_RESULT",
            "data": None,
            "summary": {
                "detected": False,
                "max_score": 0.0,
                "risk_level": "none",
                "match_count": 0,
                "reason": "similarity result not found",
            },
        }
    return {"success": True, "status": 200, "data": row}


@app.get("/similarity/stats", response_model=StatsResponse)
def stats():
    return StatsResponse(success=True, status=200, data=get_engine().stats())


@app.get("/similarity/settings")
def similarity_settings():
    config = load_config()
    return {
        "product_mode": config.product_mode,
        "admin_ui_enabled": config.admin_ui_enabled,
        "security_insight_enabled": config.security_insight_enabled,
        "llm_enabled": config.llm_enabled,
        "kafka_enabled": config.kafka_enabled,
        "manual_review_enabled": config.manual_review_enabled,
        "recent_match_cache_enabled": config.recent_match_cache_enabled,
        "recent_match_min_score": config.recent_match_min_score,
        "recent_match_log_limit": config.recent_match_log_limit,
        "recent_match_limit": config.recent_match_limit,
        "recent_match_days": config.recent_match_days,
        "recent_match_cache_ttl_sec": config.recent_match_cache_ttl_sec,
        "recent_match_include_default_partition": config.recent_match_include_default_partition,
        "recent_match_document_limit": config.recent_match_document_limit,
        "recent_match_document_recent_days": config.recent_match_document_recent_days,
        "search_logs_default_days": config.search_logs_default_days,
        "search_logs_max_document_chunks": config.search_logs_max_document_chunks,
        "search_logs_parallelism": config.search_logs_parallelism,
        "search_logs_cache_enabled": config.search_logs_cache_enabled,
        "search_logs_cache_ttl_sec": config.search_logs_cache_ttl_sec,
        "search_logs_include_default_partition": config.search_logs_include_default_partition,
        "similarity_result_enabled": config.similarity_result_enabled,
        "similarity_result_min_score": config.similarity_result_min_score,
        "similarity_result_top_k": config.similarity_result_top_k,
        "similarity_result_collection": config.similarity_result_collection,
        "grey_zone_low_score": _env_float("SIM_GREY_ZONE_LOW_SCORE", 0.62),
        "grey_zone_high_score": _env_float("SIM_GREY_ZONE_HIGH_SCORE", config.recent_match_min_score),
        "disk_warn_percent": config.disk_warn_percent,
        "disk_critical_percent": config.disk_critical_percent,
        "vector_row_warn_count": config.vector_row_warn_count,
        "retention_hot_days": config.retention_hot_days,
        "retention_warm_days": config.retention_warm_days,
        "retention_archive_days": config.retention_archive_days,
        "log_delete_before_days": config.log_delete_before_days,
        "log_retention_svc": config.log_retention_svc,
        "log_retention_policy": config.log_retention_policy,
        "log_retention_delete_results": config.log_retention_delete_results,
        "log_retention_delete_reviews": config.log_retention_delete_reviews,
        "log_retention_clear_match_cache": config.log_retention_clear_match_cache,
        "cleanup_enabled": config.cleanup_enabled,
        "cleanup_interval_sec": config.cleanup_interval_sec,
        "cleanup_dry_run": config.cleanup_dry_run,
        "upload_retain_original": config.upload_retain_original,
        "upload_deleted_retention_days": config.upload_deleted_retention_days,
        "search_upload_retention_days": config.search_upload_retention_days,
        "result_retention_days": config.result_retention_days,
        "match_cache_retention_days": config.match_cache_retention_days,
        "review_retention_days": config.review_retention_days,
    }


@app.post("/similarity/admin/cleanup")
def run_cleanup(dry_run: bool = True):
    result = get_engine().cleanup_operations(dry_run=dry_run)
    return {"success": True, "status": 200, "data": result}


@app.get("/similarity/reviews", response_model=ReviewListResponse)
def list_reviews(match_key: str | None = None, limit: int = 500):
    _require_manual_review_enabled()
    _migrate_legacy_reviews_to_mongo()
    items = get_engine().catalog.list_reviews(match_key=match_key, limit=limit)
    return ReviewListResponse(
        success=True,
        status=200,
        data=items,
    )


@app.post("/similarity/reviews", response_model=ReviewResponse)
def save_review(req: ReviewRequest):
    _require_manual_review_enabled()
    reviewed_at = now_kst()
    item = {
        "match_key": req.match_key,
        "decision": req.decision,
        "reason_code": req.reason_code,
        "comment": (req.comment or "").strip() or None,
        "reviewer": (req.reviewer or "").strip() or None,
        "review_scope": req.review_scope,
        "reviewed_at": reviewed_at.isoformat(),
        "match": req.match,
    }
    saved = get_engine().catalog.upsert_review(item)
    logger.info("match review saved match_key=%s decision=%s reason=%s", req.match_key, req.decision, req.reason_code)
    return ReviewResponse(success=True, status=200, data=saved)


@app.get("/similarity/insights/security")
def security_insight(force: bool = False):
    _require_security_insight_enabled()
    config = load_config()
    now = time.time()
    if not force and _SECURITY_INSIGHT_CACHE.get("data") and now - float(_SECURITY_INSIGHT_CACHE.get("ts") or 0) < 300:
        return _SECURITY_INSIGHT_CACHE["data"]
    if force:
        item = _generate_and_store_security_insight(reason="manual")
    else:
        item = _latest_stored_security_insight()
        if item is None:
            item = _generate_and_store_security_insight(reason="initial")
    data = {"success": True, "status": 200, "data": item}
    _SECURITY_INSIGHT_CACHE["ts"] = now
    _SECURITY_INSIGHT_CACHE["data"] = data
    return data


@app.get("/similarity/insights/security/history")
def security_insight_history(days: int | None = None, limit: int = 168):
    _require_security_insight_enabled()
    config = load_config()
    effective_days = max(1, min(int(days or config.insight_history_days), 30))
    effective_limit = max(1, min(int(limit or 168), 500))
    since = now_kst() - timedelta(days=effective_days)
    collection = _security_insight_collection()
    rows = list(
        collection.find(
            {"generated_at": {"$gte": since}},
            {"_id": 0},
        ).sort([("generated_at", -1)]).limit(effective_limit)
    )
    return {"success": True, "status": 200, "data": [_serialize_security_insight(row) for row in rows]}


@app.get("/similarity/matches/recent", response_model=SearchResponse)
def recent_matches(
    limit: int | None = None,
    log_limit: int | None = None,
    min_score: float | None = None,
    days: int | None = None,
    refresh: bool = False,
    cache_only: bool = False,
):
    config = load_config()
    effective_limit = config.recent_match_limit if limit is None else limit
    effective_log_limit = config.recent_match_log_limit if log_limit is None else log_limit
    effective_min_score = config.recent_match_min_score if min_score is None else min_score
    effective_days = max(1, min(int(days or config.recent_match_days), 365))
    hits = _recent_document_matches_cached(
        log_limit=max(1, min(effective_log_limit, 1000)),
        top_k=max(1, min(effective_limit, 100)),
        min_score=max(-1.0, min(effective_min_score, 1.0)),
        days=effective_days,
        refresh=refresh,
        cache_only=cache_only,
    )
    return SearchResponse(success=True, status=200, data=hits)


def _recent_document_matches_cached(
    *,
    log_limit: int,
    top_k: int,
    min_score: float,
    days: int,
    refresh: bool = False,
    cache_only: bool = False,
):
    config = load_config()
    engine = get_engine()
    since = now_kst() - timedelta(days=max(1, int(days)))
    params = {
        "log_limit": int(log_limit),
        "top_k": int(top_k),
        "min_score": round(float(min_score), 6),
        "days": int(days),
        "include_default_partition": bool(config.recent_match_include_default_partition),
        "document_limit": int(config.recent_match_document_limit),
        "document_recent_days": int(config.recent_match_document_recent_days),
        "version": "recent-match-cache-v1",
    }
    cache_key = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
    ttl = max(0, int(config.recent_match_cache_ttl_sec))
    if config.recent_match_cache_enabled and not refresh and ttl > 0:
        cached = engine.catalog.get_match_cache(cache_key, max_age_sec=ttl)
        if cached:
            return [SimilarityHit(**item) for item in cached.get("hits", []) if isinstance(item, dict)]
    if cache_only:
        return []
    hits = engine.recent_document_matches(
        log_limit=log_limit,
        top_k=top_k,
        min_score=min_score,
        since=since,
    )
    if config.recent_match_cache_enabled:
        engine.catalog.save_match_cache(
            cache_key,
            params=params,
            hits=[hit.model_dump(mode="json") for hit in hits],
        )
    return hits


def _security_insight_collection():
    config = load_config()
    engine = get_engine()
    collection = engine.catalog.db[config.insight_collection]
    collection.create_index([("generated_at", -1)], name="idx_generated_at")
    collection.create_index([("created_hour", -1)], name="idx_created_hour")
    return collection


def _latest_stored_security_insight() -> dict[str, object] | None:
    row = _security_insight_collection().find_one({}, {"_id": 0}, sort=[("generated_at", -1)])
    return _serialize_security_insight(row) if row else None


def _generate_and_store_security_insight(reason: str = "scheduled") -> dict[str, object]:
    config = load_config()
    engine = get_engine()
    stats_data = engine.stats()
    min_score = config.recent_match_min_score
    hits = _recent_document_matches_cached(
        log_limit=max(1, min(max(config.recent_match_log_limit, 1000), 1000)),
        top_k=100,
        min_score=max(-1.0, min(min_score, 1.0)),
        days=max(1, min(config.recent_match_days, 365)),
    )
    facts = _security_insight_facts(stats_data, hits, min_score)
    fallback = _fallback_security_insight(facts)
    insight = fallback
    llm_error = None
    use_llm = bool(config.llm_enabled and config.llm_url)
    if use_llm:
        try:
            insight = _generate_security_insight_with_llm(config, facts)
        except Exception as exc:
            llm_error = str(exc)[:500]
            logger.warning("security insight LLM fallback error=%s", llm_error)
    generated_at = now_kst()
    item = {
        **insight,
        "facts": facts,
        "source": "vllm" if llm_error is None and use_llm else "fallback",
        "model": config.llm_model if llm_error is None and use_llm else "rule-fallback",
        "llm_error": llm_error,
        "generated_at": generated_at,
        "created_hour": generated_at.replace(minute=0, second=0, microsecond=0),
        "reason": reason,
        "history_days": config.insight_history_days,
    }
    collection = _security_insight_collection()
    collection.insert_one(item)
    cutoff = generated_at - timedelta(days=max(1, int(config.insight_history_days or 7)))
    collection.delete_many({"generated_at": {"$lt": cutoff}})
    serialized = _serialize_security_insight(item)
    _SECURITY_INSIGHT_CACHE["ts"] = time.time()
    _SECURITY_INSIGHT_CACHE["data"] = {"success": True, "status": 200, "data": serialized}
    return serialized


def _serialize_security_insight(row: dict[str, object] | None) -> dict[str, object]:
    if not row:
        return {}
    item = dict(row)
    item.pop("_id", None)
    for key in ("generated_at", "created_hour"):
        value = item.get(key)
        if isinstance(value, datetime):
            item[key] = as_kst(value).isoformat()
    return item


def _security_insight_worker_loop() -> None:
    time.sleep(15)
    while True:
        config = load_config()
        if not config.security_insight_enabled:
            logger.info("security insight worker stopping because feature is disabled")
            return
        try:
            latest = _latest_stored_security_insight()
            latest_at = _parse_datetime((latest or {}).get("generated_at"))
            due = latest_at is None or now_kst() - latest_at >= timedelta(seconds=max(60, int(config.insight_interval_sec or 3600)))
            if due:
                _generate_and_store_security_insight(reason="scheduled")
        except Exception:
            logger.exception("scheduled security insight generation failed")
        time.sleep(max(60, min(int(config.insight_interval_sec or 3600), 3600)))


def _cleanup_worker_loop() -> None:
    time.sleep(30)
    while True:
        config = load_config()
        if not config.cleanup_enabled:
            logger.info("cleanup worker stopping because feature is disabled")
            return
        try:
            result = get_engine().cleanup_operations(dry_run=bool(config.cleanup_dry_run))
            logger.info("scheduled cleanup completed dry_run=%s result=%s", config.cleanup_dry_run, result)
        except Exception:
            logger.exception("scheduled cleanup failed")
        time.sleep(max(300, int(config.cleanup_interval_sec or 86400)))


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return as_kst(value) if value.tzinfo else value.replace(tzinfo=KST)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return as_kst(parsed) if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except Exception:
        return None


def _display_log_id(log_id: str) -> str:
    return re.sub(r":attach:\d+$", "", str(log_id or ""), flags=re.IGNORECASE)


def _security_insight_facts(stats_data, hits, min_score: float) -> dict[str, object]:
    unique_logs: dict[str, dict[str, object]] = {}
    service_counts: Counter[str] = Counter()
    user_counts: Counter[str] = Counter()
    doc_counts: Counter[str] = Counter()
    attachment_count = 0
    scores: list[float] = []
    latest_ts = ""
    for hit in hits:
        meta = dict(hit.metadata or {})
        log_meta = dict(meta.get("_match_log_metadata") or {})
        log_id = str(meta.get("_match_log_id") or "")
        group_id = _display_log_id(log_id)
        if not group_id:
            continue
        score = float(hit.score or 0)
        scores.append(score)
        service = str(log_meta.get("svc") or log_meta.get("channel") or "-")
        user = str(log_meta.get("user_id") or "-")
        doc_title = str(meta.get("title") or meta.get("file_name") or hit.target_id or "-")
        ctime = str(log_meta.get("ctime") or "")
        if ctime > latest_ts:
            latest_ts = ctime
        if str(log_meta.get("source_type") or "").lower() == "attachment":
            attachment_count += 1
        service_counts[service] += 1
        user_counts[user] += 1
        doc_counts[doc_title] += 1
        current = unique_logs.get(group_id)
        if current is None or score > float(current.get("score") or 0):
            unique_logs[group_id] = {
                "log_id": group_id,
                "score": round(score, 4),
                "user_id": user,
                "svc": service,
                "source_type": log_meta.get("source_type") or "-",
                "document": doc_title,
                "ctime": ctime,
            }
    high_logs = sorted(unique_logs.values(), key=lambda item: (str(item.get("ctime") or ""), float(item.get("score") or 0)), reverse=True)
    total_chunks = int(stats_data.document_chunks or 0) + int(stats_data.log_chunks or 0)
    avg_score = sum(scores) / len(scores) if scores else 0.0
    return {
        "threshold": round(float(min_score), 3),
        "documents": int(stats_data.documents or 0),
        "document_chunks": int(stats_data.document_chunks or 0),
        "logs": int(stats_data.logs or 0),
        "log_chunks": int(stats_data.log_chunks or 0),
        "document_index_bytes": int(stats_data.document_index_bytes or 0),
        "log_index_bytes": int(stats_data.log_index_bytes or 0),
        "index_chunks_total": total_chunks,
        "document_index_ratio": round((float(stats_data.document_chunks or 0) / total_chunks) * 100, 1) if total_chunks else 0.0,
        "log_index_ratio": round((float(stats_data.log_chunks or 0) / total_chunks) * 100, 1) if total_chunks else 0.0,
        "recent_match_count": len(hits),
        "unique_high_risk_logs": len(unique_logs),
        "attachment_match_count": attachment_count,
        "attachment_ratio": round((attachment_count / len(hits)) * 100, 1) if hits else 0.0,
        "avg_score": round(avg_score, 4),
        "max_score": round(max(scores), 4) if scores else 0.0,
        "latest_time": latest_ts,
        "top_services": service_counts.most_common(5),
        "top_users": user_counts.most_common(5),
        "top_documents": doc_counts.most_common(5),
        "recent_high_risk": high_logs[:8],
    }


def _fallback_security_insight(facts: dict[str, object]) -> dict[str, object]:
    high_count = int(facts.get("unique_high_risk_logs") or 0)
    match_count = int(facts.get("recent_match_count") or 0)
    max_score = float(facts.get("max_score") or 0)
    attach_ratio = float(facts.get("attachment_ratio") or 0)
    top_services = facts.get("top_services") or []
    top_users = facts.get("top_users") or []
    if high_count == 0:
        severity = "low"
        headline = "현재 임계치 이상 고위험 매칭은 없습니다."
        summary = "최근 로그와 등록문서 벡터 비교 결과가 설정 임계치 미만입니다. 신규 등록문서 또는 로그 적재 후 변화를 계속 확인하면 됩니다."
    elif max_score >= 0.95 or high_count >= 10:
        severity = "high"
        headline = "등록문서와 매우 유사한 로그가 확인되어 정보유출 검토가 필요합니다."
        summary = f"최근 고위험 매칭 {match_count}건 중 고유 로깅ID는 {high_count}건이며 최고 유사도는 {max_score:.3f}입니다. 첨부 기반 비중은 {attach_ratio:.1f}%로, 문서 원문 또는 첨부 재전송 가능성을 우선 확인해야 합니다."
    else:
        severity = "medium"
        headline = "일부 로그가 등록문서와 유사해 선별 검토가 필요합니다."
        summary = f"최근 고위험 매칭 {match_count}건 중 고유 로깅ID는 {high_count}건입니다. 최고 유사도 {max_score:.3f} 기준으로 상위 항목부터 검토하는 것이 효율적입니다."
    service_text = ", ".join([f"{name} {count}건" for name, count in top_services[:3]]) or "서비스 집중 없음"
    user_text = ", ".join([f"{name} {count}건" for name, count in top_users[:3]]) or "사용자 집중 없음"
    return {
        "severity": severity,
        "headline": headline,
        "summary": summary,
        "reasons": [
            f"서비스 집중도: {service_text}",
            f"사용자 집중도: {user_text}",
            f"첨부 기반 매칭 비중: {attach_ratio:.1f}%",
        ],
        "actions": [
            "고위험 매칭 목록에서 최고 유사도 항목의 등록문서와 로그 원문을 비교합니다.",
            "동일 사용자 또는 동일 서비스 반복 발생 여부를 로그확인에서 필터링합니다.",
            "첨부 기반 매칭이면 첨부파일명, 발신/수신 방향, 외부 전송 여부를 우선 확인합니다.",
        ],
    }


def _generate_security_insight_with_llm(config, facts: dict[str, object]) -> dict[str, object]:
    compact_facts = {
        key: facts.get(key)
        for key in [
            "threshold", "documents", "logs", "document_chunks", "log_chunks",
            "document_index_bytes", "log_index_bytes",
            "recent_match_count", "unique_high_risk_logs", "attachment_ratio", "avg_score", "max_score",
            "latest_time", "top_services", "top_users", "top_documents", "recent_high_risk",
        ]
    }
    system = (
        "/no_think\n"
        "너는 보안 관제 대시보드의 분석가다. 사고 과정은 출력하지 않는다. "
        "제공된 수치만 근거로 판단하고, 정보유출 유사도 관점으로만 설명한다. "
        "악성코드, 침해 확정, 계정 차단처럼 근거 없는 단정이나 과격한 조치는 쓰지 않는다. "
        "정해진 라벨 형식으로만 짧게 답한다."
    )
    user = (
        "/no_think\n"
        "다음은 등록문서와 로깅데이터 벡터 유사도 기반 정보유출 탐지 현황이다.\n"
        f"{json.dumps(compact_facts, ensure_ascii=False)}\n\n"
        "주의: recent_match_count는 로그-등록문서 매칭 쌍 수이고, unique_high_risk_logs는 같은 로깅ID를 중복 제거한 고유 로그 수다.\n"
        "아래 9개 라벨을 반드시 실제 분석 내용으로 채워라. 형식 설명을 반복하지 마라.\n"
        "severity 값은 반드시 low, medium, high 중 하나만 작성하라.\n"
        "severity:\n"
        "headline:\n"
        "summary:\n"
        "reason1:\n"
        "reason2:\n"
        "reason3:\n"
        "action1:\n"
        "action2:\n"
        "action3:"
    )
    payload = {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 420,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        config.llm_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(3, int(config.llm_timeout_sec or 20))) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    content = str(data["choices"][0]["message"]["content"])
    fallback = _fallback_security_insight(facts)
    parsed = _parse_labeled_insight(content)
    severity = _normalize_insight_severity(parsed.get("severity"))
    if severity not in {"low", "medium", "high"}:
        raise ValueError("LLM returned invalid severity")
    headline = str(parsed.get("headline") or "").strip()
    summary = str(parsed.get("summary") or "").strip()
    placeholder_terms = ("한 문장", "headline", "관제자가 바로 이해", "현재 보안 상황", "수치 기반 판단", "우선 확인할 조치")
    if not headline or any(term in headline for term in placeholder_terms) or not summary or any(term in summary for term in placeholder_terms):
        raise ValueError("LLM returned placeholder content")
    return {
        "severity": severity,
        "headline": headline[:300],
        "summary": summary[:1200],
        "reasons": [str(x)[:300] for x in (parsed.get("reasons") or fallback["reasons"]) if str(x).strip()][:4],
        "actions": [str(x)[:300] for x in (parsed.get("actions") or fallback["actions"]) if str(x).strip()][:4],
    }


def _parse_labeled_insight(content: str) -> dict[str, object]:
    fields: dict[str, str] = {}
    current: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip().strip("-*")
        if not line:
            continue
        match = re.match(r"^(severity|headline|summary|reason[123]|action[123])\s*[:：]\s*(.*)$", line, flags=re.I)
        if match:
            current = match.group(1).lower()
            fields[current] = match.group(2).strip()
        elif current:
            fields[current] = (fields.get(current, "") + " " + line).strip()
    return {
        "severity": fields.get("severity", ""),
        "headline": fields.get("headline", ""),
        "summary": fields.get("summary", ""),
        "reasons": [fields.get("reason1", ""), fields.get("reason2", ""), fields.get("reason3", "")],
        "actions": [fields.get("action1", ""), fields.get("action2", ""), fields.get("action3", "")],
    }


def _normalize_insight_severity(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    token = re.split(r"[\s,;/|()\[\]{}:：-]+", text, maxsplit=1)[0].strip()
    mapping = {
        "critical": "high",
        "urgent": "high",
        "severe": "high",
        "높음": "high",
        "고": "high",
        "고위험": "high",
        "즉시": "high",
        "즉시검토": "high",
        "주의": "medium",
        "중간": "medium",
        "보통": "medium",
        "중위험": "medium",
        "관찰": "medium",
        "낮음": "low",
        "저": "low",
        "저위험": "low",
        "안정": "low",
    }
    if token in {"low", "medium", "high"}:
        return token
    if token in mapping:
        return mapping[token]
    for key, normalized in mapping.items():
        if key in text:
            return normalized
    for key in ("high", "medium", "low"):
        if key in text:
            return key
    return token


def _normalize_source_type(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"body", "attachment"}:
        return normalized
    raise HTTPException(status_code=400, detail="source_type must be body or attachment")


def _empty_middleware_similarity_result(msgid: str) -> dict[str, object]:
    generated_at = now_kst().isoformat()
    return {
        "type": "similarity",
        "msgid": str(msgid),
        "data": {
            "similarity": {
                "success": True,
                "status": 200,
                "message": "NO_RESULT",
                "version": "similarity-result-v1",
                "generated_at": generated_at,
                "summary": {
                    "detected": False,
                    "max_score": 0.0,
                    "risk_level": "none",
                    "match_count": 0,
                    "reason": "EMS source message not found or no body/attachment text",
                },
                "results": [],
            }
        },
        "summary": {
            "detected": False,
            "max_score": 0.0,
            "risk_level": "none",
            "match_count": 0,
            "reason": "EMS source message not found or no body/attachment text",
        },
        "detected": False,
        "max_score": 0.0,
        "match_count": 0,
        "risk_level": "none",
        "generated_at": generated_at,
    }


def _annotate_middleware_similarity_result(result: dict[str, object] | None, processing: dict[str, object]) -> None:
    if not isinstance(result, dict):
        return
    result["processing"] = dict(processing)
    summary = result.get("summary")
    if isinstance(summary, dict):
        summary["processing"] = dict(processing)
        if processing.get("partial"):
            summary["reason"] = processing.get("stop_reason") or summary.get("reason") or "PARTIAL"
    data = result.get("data")
    if isinstance(data, dict):
        similarity = data.get("similarity")
        if isinstance(similarity, dict):
            similarity["processing"] = dict(processing)
            summary = similarity.get("summary")
            if isinstance(summary, dict):
                summary["processing"] = dict(processing)
                if processing.get("partial"):
                    summary["reason"] = processing.get("stop_reason") or summary.get("reason") or "PARTIAL"
            if processing.get("partial"):
                similarity["message"] = "PARTIAL"


def _sanitize_middleware_similarity_result(result: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(result, dict):
        return None
    sanitized = _remove_middleware_response_fields(result)
    if isinstance(sanitized, dict):
        sanitized.pop("summary", None)
    return sanitized if isinstance(sanitized, dict) else None


def _remove_middleware_response_fields(value):
    excluded = {"processing", "_match_document_text_preview", "_match_log_text_preview"}
    if isinstance(value, dict):
        return {
            str(key): _remove_middleware_response_fields(item)
            for key, item in value.items()
            if str(key) not in excluded
        }
    if isinstance(value, list):
        return [_remove_middleware_response_fields(item) for item in value]
    return value


def _ems_rows_for_source(
    *,
    svc: str,
    source_id: str,
    source_payload: dict[str, object] | None,
    metadata: dict[str, object],
):
    engine = get_engine()
    try:
        payload = source_payload or read_ems_source(
            mongo_uri=engine.config.ems_mongo_uri,
            minio_endpoint=engine.config.minio_endpoint,
            minio_access_key=engine.config.minio_access_key,
            minio_secret_key=engine.config.minio_secret_key,
            svc=svc,
            source_id=source_id,
        )
        rows = build_ems_log_rows(svc=svc, source_id=source_id, source=payload, request_metadata=metadata)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("EMS source fetch failed svc=%s source_id=%s", svc, source_id)
        raise HTTPException(status_code=502, detail=f"EMS source fetch failed: {exc}") from exc
    return engine, rows


def _split_msgid_similarity_result(row: dict[str, object], *, threshold: float) -> dict[str, object]:
    similarity = dict(dict(row.get("data") or {}).get("similarity") or {})
    body: MsgidSimilarityBodyResult | None = None
    attachments: list[MsgidSimilarityAttachmentResult] = []
    match_count = 0

    for item in similarity.get("results") or []:
        if not isinstance(item, dict):
            continue
        filtered_matches = [
            dict(match)
            for match in (item.get("matches") or [])
            if isinstance(match, dict) and float(match.get("score") or 0.0) >= float(threshold)
        ]
        if not filtered_matches:
            continue
        filtered_matches.sort(key=lambda match: float(match.get("score") or 0.0), reverse=True)
        part_max_score = max(float(match.get("score") or 0.0) for match in filtered_matches)
        match_count += len(filtered_matches)
        matches = [_simplify_msgid_match(match) for match in filtered_matches]
        if str(item.get("target") or "").lower() == "attach":
            attachments.append(
                MsgidSimilarityAttachmentResult(
                    attach_index=_safe_int(item.get("attach_index"), 0),
                    max_score=round(part_max_score, 6),
                    matches=matches,
                )
            )
        else:
            body = MsgidSimilarityBodyResult(
                max_score=round(part_max_score, 6),
                matches=matches,
            )

    attachments.sort(key=lambda part: (-float(part.max_score), part.attach_index if part.attach_index is not None else 0))
    return {
        "match_count": match_count,
        "body": body,
        "attachments": attachments,
    }


def _simplify_msgid_match(match: dict[str, object]) -> MsgidSimilarityMatchResult:
    score = float(match.get("score") or 0.0)
    return MsgidSimilarityMatchResult(
        document_title=str(match.get("document_title") or match.get("document_id") or ""),
        document_security_level=match.get("document_security_level"),
        score_percent=round(float(match.get("score_percent") or (score * 100.0)), 2),
        matched_keywords=[str(term) for term in (match.get("matched_keywords") or match.get("matched_terms") or []) if str(term).strip()],
        matched_terms_description=str(
            match.get("matched_terms_description")
            or "등록문서 매칭 청크와 EMS 본문/첨부 매칭 청크 양쪽에 공통으로 나타난 대표 핵심어입니다. 유사도 판정 사유 설명용이며 전체 공통 단어 목록은 아닙니다."
        ),
    )


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _rows_effective_svc(rows: list[dict[str, object]]) -> str | None:
    for row in rows:
        metadata = dict(row.get("metadata") or {})
        value = str(metadata.get("svc") or row.get("svc") or "").strip()
        if value:
            return value
    return None


def _rows_text_chars(rows: list[dict[str, object]]) -> int:
    return sum(len(str(row.get("text") or "")) for row in rows)


def _rows_source_summary(rows: list[dict[str, object]]) -> str:
    counts = Counter(str(dict(row.get("metadata") or {}).get("source_type") or "unknown") for row in rows)
    return ",".join(f"{key}:{counts[key]}" for key in sorted(counts))


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _similarity_risk_level(score: float, *, low: float, high: float) -> str:
    value = float(score or 0.0)
    if value <= 0:
        return "none"
    if value >= float(high):
        return "high"
    if value >= float(low):
        return "grey"
    return "low"


def _middleware_callback_url(callback_url: str | None, config) -> str:
    if callback_url:
        return str(callback_url).strip()
    base_url = str(config.middleware_base_url or "").rstrip("/")
    if not base_url:
        return ""
    return _join_url_path(base_url, config.middleware_result_path or "/similarity/result")


def _deliver_middleware_result(*, url: str, payload: dict[str, object], msgid: str, engine) -> bool:
    try:
        response = _post_json_url(url, payload, timeout=max(1, int(engine.config.middleware_timeout_sec or 30)))
    except Exception as exc:
        engine.catalog.mark_middleware_delivery(msgid=msgid, status="failed", url=url, error=str(exc))
        logger.warning("middleware result delivery failed msgid=%s url=%s error=%s", msgid, url, exc)
        return False
    engine.catalog.mark_middleware_delivery(msgid=msgid, status="sent", url=url, response=response)
    return True


def _join_url_path(base_url: str, path: str) -> str:
    return str(base_url).rstrip("/") + "/" + str(path or "").lstrip("/")


def _post_json_url(url: str, payload: dict[str, object], *, timeout: int) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        str(url),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, int(timeout))) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


@app.post("/similarity/search/documents", response_model=SearchResponse)
def search_documents(req: SearchDocumentsRequest):
    started = time.perf_counter()
    hits = get_engine().search_documents(
        text=req.text,
        top_k=req.top_k,
        min_score=req.min_score,
        metadata_filter=req.metadata_filter,
    )
    _log_search_result("document_text", started, hits, req.top_k, req.min_score, req.metadata_filter, query_chars=len(req.text))
    return SearchResponse(success=True, status=200, data=hits)


@app.post("/similarity/search/documents/upload", response_model=SearchResponse)
def search_documents_by_upload(
    file: UploadFile = File(...),
    top_k: int = Form(10),
    min_score: float = Form(0.0),
):
    started = time.perf_counter()
    text, file_meta = _extract_uploaded_text(file, prefix="docs")
    hits = get_engine().search_documents(
        text=text,
        top_k=max(1, min(int(top_k), 100)),
        min_score=max(-1.0, min(float(min_score), 1.0)),
        metadata_filter={},
    )
    _log_search_result("document_upload", started, hits, top_k, min_score, {}, query_chars=len(text), file_name=file_meta.get("file_name"))
    return SearchResponse(success=True, status=200, data=hits)


@app.post("/similarity/search/logs", response_model=SearchResponse)
def search_logs(req: SearchLogsRequest):
    started = time.perf_counter()
    hits = get_engine().search_logs_by_document(
        document_id=req.document_id,
        top_k=req.top_k,
        min_score=req.min_score,
        metadata_filter=req.metadata_filter,
    )
    _log_search_result("document_to_log", started, hits, req.top_k, req.min_score, req.metadata_filter, document_id=req.document_id)
    return SearchResponse(success=True, status=200, data=hits)


@app.post("/similarity/search/logs/text", response_model=SearchResponse)
def search_logs_by_text(req: SearchLogsByTextRequest):
    started = time.perf_counter()
    hits = get_engine().search_logs_by_text(
        text=req.text,
        top_k=req.top_k,
        min_score=req.min_score,
        metadata_filter=req.metadata_filter,
    )
    top_hits = search_hit_log_items(hits, limit=5)
    logger.info(
        "log text search completed query_chars=%d top_k=%d min_score=%.6f filter_keys=%s hits=%d max_score=%.6f top_hits=%s elapsed_ms=%.1f",
        len(req.text),
        req.top_k,
        req.min_score,
        ",".join(sorted(str(key) for key in req.metadata_filter)) or "-",
        len(hits),
        max((float(hit.score) for hit in hits), default=0.0),
        json.dumps(top_hits, ensure_ascii=False, separators=(",", ":")),
        _elapsed_ms(started),
    )
    return SearchResponse(success=True, status=200, data=hits)


@app.post("/similarity/search/logs/upload", response_model=SearchResponse)
def search_logs_by_upload(
    file: UploadFile = File(...),
    top_k: int = Form(20),
    min_score: float = Form(0.0),
    source_type: str | None = Form(None),
    svc: str | None = Form(None),
    user_id: str | None = Form(None),
):
    started = time.perf_counter()
    text, file_meta = _extract_uploaded_text(file, prefix="logs")
    metadata_filter: dict[str, object] = {}
    normalized_source_type = _normalize_source_type(source_type)
    if normalized_source_type:
        metadata_filter["source_type"] = normalized_source_type
    if svc:
        metadata_filter["svc"] = svc.strip()
    if user_id:
        metadata_filter["user_id"] = user_id.strip()
    hits = get_engine().search_logs_by_text(
        text=text,
        top_k=max(1, min(int(top_k), 200)),
        min_score=max(-1.0, min(float(min_score), 1.0)),
        metadata_filter=metadata_filter,
    )
    _log_search_result("log_upload", started, hits, top_k, min_score, metadata_filter, query_chars=len(text), file_name=file_meta.get("file_name"))
    return SearchResponse(success=True, status=200, data=hits)


def _log_search_result(
    operation: str,
    started: float,
    hits,
    top_k: int,
    min_score: float,
    metadata_filter: dict[str, object],
    **context,
) -> None:
    safe_context = {str(key): value for key, value in context.items() if value not in (None, "")}
    logger.info(
        "similarity search completed operation=%s top_k=%d min_score=%.6f filter_keys=%s hits=%d max_score=%.6f top_hits=%s context=%s elapsed_ms=%.1f",
        operation,
        int(top_k),
        float(min_score),
        ",".join(sorted(str(key) for key in metadata_filter)) or "-",
        len(hits),
        max((float(hit.score) for hit in hits), default=0.0),
        json.dumps(search_hit_log_items(hits, limit=5), ensure_ascii=False, separators=(",", ":")),
        json.dumps(safe_context, ensure_ascii=False, separators=(",", ":")),
        _elapsed_ms(started),
    )
