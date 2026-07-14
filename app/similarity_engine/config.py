from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_feature_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip().lower() in {"", "auto"}:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _product_mode() -> str:
    mode = os.getenv("SIM_PRODUCT_MODE", "standalone").strip().lower()
    if mode not in {"standalone", "integrated", "ops"}:
        return "standalone"
    return mode


_PRODUCT_MODE = _product_mode()
_OPS_DEFAULT = _PRODUCT_MODE == "ops"


@dataclass(frozen=True)
class SimilarityConfig:
    product_mode: str = _PRODUCT_MODE
    admin_ui_enabled: bool = _env_feature_bool("SIM_ADMIN_UI_ENABLED", _OPS_DEFAULT)
    security_insight_enabled: bool = _env_feature_bool("SIM_SECURITY_INSIGHT_ENABLED", _OPS_DEFAULT)
    llm_enabled: bool = _env_bool("SIM_LLM_ENABLED", False)
    manual_review_enabled: bool = _env_feature_bool("SIM_MANUAL_REVIEW_ENABLED", _OPS_DEFAULT)
    recent_match_cache_enabled: bool = _env_feature_bool("SIM_RECENT_MATCH_CACHE_ENABLED", _OPS_DEFAULT)
    milvus_url: str = os.getenv("SIM_MILVUS_URL", "http://milvus:19530").strip().rstrip("/")
    milvus_object_root: str = os.getenv("SIM_MILVUS_OBJECT_ROOT", "").strip()
    storage_stats_ttl_sec: int = _env_int("SIM_STORAGE_STATS_TTL_SEC", 60)
    embedder_backend: str = os.getenv("SIM_EMBEDDER_BACKEND", "hash").strip().lower()
    embedding_model_path: str = os.getenv("SIM_EMBEDDING_MODEL_PATH", "").strip()
    embedding_dim: int = _env_int("SIM_EMBEDDING_DIM", 384)
    chunk_size: int = _env_int("SIM_CHUNK_SIZE", 1800)
    chunk_overlap: int = _env_int("SIM_CHUNK_OVERLAP", 250)
    min_chunk_chars: int = _env_int("SIM_MIN_CHUNK_CHARS", 50)
    max_document_chunks: int = _env_int("SIM_MAX_DOCUMENT_CHUNKS", 5000)
    max_log_chunks: int = _env_int("SIM_MAX_LOG_CHUNKS", 100)
    max_middleware_chars: int = _env_int("SIM_MAX_MIDDLEWARE_CHARS", 2_000_000)
    max_middleware_chunks: int = _env_int("SIM_MAX_MIDDLEWARE_CHUNKS", 100)
    max_middleware_item_chars: int = _env_int("SIM_MAX_MIDDLEWARE_ITEM_CHARS", 800_000)
    default_min_score: float = _env_float("SIM_DEFAULT_MIN_SCORE", 0.0)
    recent_match_min_score: float = _env_float("SIM_RECENT_MATCH_MIN_SCORE", 0.82)
    recent_match_log_limit: int = _env_int("SIM_RECENT_MATCH_LOG_LIMIT", 50)
    recent_match_limit: int = _env_int("SIM_RECENT_MATCH_LIMIT", 20)
    recent_match_days: int = _env_int("SIM_RECENT_MATCH_DAYS", 30)
    recent_match_cache_ttl_sec: int = _env_int("SIM_RECENT_MATCH_CACHE_TTL_SEC", 300)
    recent_match_include_default_partition: bool = _env_bool("SIM_RECENT_MATCH_INCLUDE_DEFAULT_PARTITION", True)
    recent_match_document_limit: int = _env_int("SIM_RECENT_MATCH_DOCUMENT_LIMIT", 0)
    recent_match_document_recent_days: int = _env_int("SIM_RECENT_MATCH_DOCUMENT_RECENT_DAYS", 365)
    search_logs_default_days: int = _env_int("SIM_SEARCH_LOGS_DEFAULT_DAYS", 30)
    search_logs_max_document_chunks: int = _env_int("SIM_SEARCH_LOGS_MAX_DOCUMENT_CHUNKS", 8)
    search_logs_parallelism: int = _env_int("SIM_SEARCH_LOGS_PARALLELISM", 4)
    search_logs_cache_enabled: bool = _env_bool("SIM_SEARCH_LOGS_CACHE_ENABLED", True)
    search_logs_cache_ttl_sec: int = _env_int("SIM_SEARCH_LOGS_CACHE_TTL_SEC", 300)
    search_logs_include_default_partition: bool = _env_bool("SIM_SEARCH_LOGS_INCLUDE_DEFAULT_PARTITION", True)
    similarity_result_enabled: bool = _env_bool("SIM_SIMILARITY_RESULT_ENABLED", True)
    similarity_result_min_score: float = _env_float("SIM_SIMILARITY_RESULT_MIN_SCORE", _env_float("SIM_RECENT_MATCH_MIN_SCORE", 0.82))
    similarity_result_top_k: int = _env_int("SIM_SIMILARITY_RESULT_TOP_K", 5)
    similarity_result_search_retries: int = _env_int("SIM_SIMILARITY_RESULT_SEARCH_RETRIES", 5)
    similarity_result_search_retry_delay_sec: float = _env_float("SIM_SIMILARITY_RESULT_SEARCH_RETRY_DELAY_SEC", 0.5)
    similarity_result_recent_document_window_sec: int = _env_int("SIM_SIMILARITY_RESULT_RECENT_DOCUMENT_WINDOW_SEC", 30)
    kafka_enabled: bool = _env_bool("SIM_KAFKA_ENABLED", False)
    kafka_bootstrap_servers: str = os.getenv("SIM_KAFKA_BOOTSTRAP_SERVERS", "kafka:9092").strip()
    kafka_topic: str = os.getenv("SIM_KAFKA_TOPIC", "analysis_result").strip()
    kafka_client_id: str = os.getenv("SIM_KAFKA_CLIENT_ID", "xcn-similarity").strip()
    kafka_timeout_sec: int = _env_int("SIM_KAFKA_TIMEOUT_SEC", 5)
    ems_mongo_uri: str = os.getenv(
        "EMS_MONGO_URI",
        "mongodb://mongodb:27017/venus?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000",
    ).strip()
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "http://minio:9000").strip()
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin").strip()
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin").strip()
    middleware_base_url: str = os.getenv("SIM_MIDDLEWARE_BASE_URL", "").strip().rstrip("/")
    middleware_result_path: str = os.getenv("SIM_MIDDLEWARE_RESULT_PATH", "/similarity/result").strip()
    middleware_timeout_sec: int = _env_int("SIM_MIDDLEWARE_TIMEOUT_SEC", 60)
    grey_zone_low_score: float = _env_float("SIM_GREY_ZONE_LOW_SCORE", 0.62)
    grey_zone_high_score: float = _env_float("SIM_GREY_ZONE_HIGH_SCORE", _env_float("SIM_RECENT_MATCH_MIN_SCORE", 0.82))
    monitor_paths: str = os.getenv("SIM_MONITOR_PATHS", "/,/logs,/minio_data").strip()
    disk_warn_percent: float = _env_float("SIM_DISK_WARN_PERCENT", 80.0)
    disk_critical_percent: float = _env_float("SIM_DISK_CRITICAL_PERCENT", 90.0)
    milvus_memory_warn_mb: int = _env_int("SIM_MILVUS_MEMORY_WARN_MB", 65536)
    vector_row_warn_count: int = _env_int("SIM_VECTOR_ROW_WARN_COUNT", 50_000_000)
    retention_hot_days: int = _env_int("SIM_RETENTION_HOT_DAYS", 90)
    retention_warm_days: int = _env_int("SIM_RETENTION_WARM_DAYS", 365)
    retention_archive_days: int = _env_int("SIM_RETENTION_ARCHIVE_DAYS", 1095)
    log_delete_before_days: int = _env_int("SIM_LOG_DELETE_BEFORE_DAYS", 365)
    log_retention_svc: str = os.getenv("SIM_LOG_RETENTION_SVC", "").strip()
    log_retention_policy: str = os.getenv("SIM_LOG_RETENTION_POLICY", "*=365").strip()
    log_retention_delete_results: bool = _env_bool("SIM_LOG_RETENTION_DELETE_RESULTS", True)
    log_retention_delete_reviews: bool = _env_bool("SIM_LOG_RETENTION_DELETE_REVIEWS", False)
    log_retention_clear_match_cache: bool = _env_bool("SIM_LOG_RETENTION_CLEAR_MATCH_CACHE", False)
    cleanup_enabled: bool = _env_bool("SIM_CLEANUP_ENABLED", True)
    cleanup_interval_sec: int = _env_int("SIM_CLEANUP_INTERVAL_SEC", 86400)
    cleanup_dry_run: bool = _env_bool("SIM_CLEANUP_DRY_RUN", False)
    upload_retain_original: bool = _env_bool("SIM_UPLOAD_RETAIN_ORIGINAL", True)
    upload_deleted_retention_days: int = _env_int("SIM_UPLOAD_DELETED_RETENTION_DAYS", 0)
    search_upload_retention_days: int = _env_int("SIM_SEARCH_UPLOAD_RETENTION_DAYS", 7)
    result_retention_days: int = _env_int("SIM_RESULT_RETENTION_DAYS", 0)
    match_cache_retention_days: int = _env_int("SIM_MATCH_CACHE_RETENTION_DAYS", 7)
    review_retention_days: int = _env_int("SIM_REVIEW_RETENTION_DAYS", 0)
    llm_url: str = os.getenv("SIM_LLM_URL", "").strip()
    llm_model: str = os.getenv("SIM_LLM_MODEL", "qwen3.5-27b-fp8").strip()
    llm_timeout_sec: int = _env_int("SIM_LLM_TIMEOUT_SEC", 60)
    insight_interval_sec: int = _env_int("SIM_INSIGHT_INTERVAL_SEC", 3600)
    insight_history_days: int = _env_int("SIM_INSIGHT_HISTORY_DAYS", 7)
    insight_collection: str = os.getenv("SIM_INSIGHT_COLLECTION", "SIM_SECURITY_INSIGHT").strip()
    catalog_mongo_uri: str = os.getenv(
        "SIM_CATALOG_MONGO_URI",
        "mongodb://mongodb:27017/xcn_similarity?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000",
    ).strip()
    catalog_database: str = os.getenv("SIM_CATALOG_DATABASE", "xcn_similarity").strip()
    log_catalog_collection: str = os.getenv("SIM_LOG_CATALOG_COLLECTION", "SIM_LOG_CATALOG").strip()
    document_catalog_collection: str = os.getenv("SIM_DOCUMENT_CATALOG_COLLECTION", "SIM_DOCUMENT_CATALOG").strip()
    review_collection: str = os.getenv("SIM_REVIEW_COLLECTION", "SIM_MATCH_REVIEW").strip()
    match_cache_collection: str = os.getenv("SIM_MATCH_CACHE_COLLECTION", "SIM_MATCH_CACHE").strip()
    similarity_result_collection: str = os.getenv("SIM_SIMILARITY_RESULT_COLLECTION", "SIM_SIMILARITY_RESULT").strip()
    upload_dir: str = os.getenv("SIM_UPLOAD_DIR", "/logs/uploads").strip()
    max_upload_mb: int = _env_int("SIM_MAX_UPLOAD_MB", 300)
    multi_upload_max_files: int = _env_int("SIM_MULTI_UPLOAD_MAX_FILES", 50)
    archive_max_files: int = _env_int("SIM_ARCHIVE_MAX_FILES", 500)
    archive_max_total_mb: int = _env_int("SIM_ARCHIVE_MAX_TOTAL_MB", 1024)
    archive_max_member_mb: int = _env_int("SIM_ARCHIVE_MAX_MEMBER_MB", 100)


def load_config() -> SimilarityConfig:
    return SimilarityConfig()
