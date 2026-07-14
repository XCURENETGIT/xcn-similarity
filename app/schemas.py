from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


IndexStatus = Literal["PENDING", "PROCESSING", "INDEXED", "FAILED", "DELETED", "SKIPPED"]


class DocumentRegisterRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=20_000_000)
    security_level: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentInfo(BaseModel):
    document_id: str
    title: str
    owner: str | None = None
    department: str | None = None
    security_level: str | None = None
    status: IndexStatus
    chunk_count: int
    created_at: datetime
    deleted_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    security_level: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] | None = None


class DocumentRegisterResponse(BaseModel):
    success: bool
    status: int
    data: DocumentInfo


class DocumentUploadResponse(BaseModel):
    success: bool
    status: int
    data: list[DocumentInfo]
    primary_document_id: str | None = None


class DocumentListResponse(BaseModel):
    success: bool
    status: int
    data: list[DocumentInfo]
    next_offset: int | None = None


class DeleteResponse(BaseModel):
    success: bool
    status: int
    document_id: str


class LogRetentionDeleteRequest(BaseModel):
    svc: str | list[str] = Field(min_length=1)
    delete_before: datetime | None = None
    dry_run: bool = True


class LogRetentionDeleteResponse(BaseModel):
    success: bool
    status: int
    dry_run: bool
    svc: list[str]
    delete_before: datetime
    matched_logs: int
    matched_chunks: int
    catalog_deleted: int = 0
    vector_deleted: int = 0


class LogIndexRequest(BaseModel):
    log_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=20_000_000)
    svc: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=255)
    ctime: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogBatchIndexRequest(BaseModel):
    items: list[LogIndexRequest] = Field(min_length=1, max_length=200)


class LogInfo(BaseModel):
    log_id: str
    status: IndexStatus
    chunk_count: int
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogIndexResponse(BaseModel):
    success: bool
    status: int
    data: LogInfo


class LogBatchIndexResponse(BaseModel):
    success: bool
    status: int
    data: list[LogInfo]


class MiddlewareAnalyzeRequest(BaseModel):
    svc: str = Field(min_length=1, max_length=64)
    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    id: str | None = Field(default=None, alias="_id", min_length=1, max_length=255)
    callback_url: str | None = Field(default=None, max_length=2048)
    source_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MiddlewareAnalyzeResponse(BaseModel):
    success: bool
    status: int
    svc: str
    source_id: str
    message: str = "OK"
    reason: str | None = None
    indexed_logs: int
    indexed_chunks: int
    result_delivered: bool = False
    result: dict[str, Any] | None = None


class MsgidSimilarityAnalyzeRequest(BaseModel):
    msgid: str | None = Field(default=None, min_length=1, max_length=255)
    id: str | None = Field(default=None, alias="_id", min_length=1, max_length=255)
    svc: str | None = Field(default=None, max_length=64)
    source_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MsgidSimilarityMatchResult(BaseModel):
    document_title: str | None = None
    document_security_level: str | None = None
    score_percent: float
    matched_keywords: list[str] = Field(default_factory=list)
    matched_terms_description: str | None = None


class MsgidSimilarityBodyResult(BaseModel):
    max_score: float
    matches: list[MsgidSimilarityMatchResult] = Field(default_factory=list)


class MsgidSimilarityAttachmentResult(BaseModel):
    attach_index: int
    max_score: float
    matches: list[MsgidSimilarityMatchResult] = Field(default_factory=list)


class MsgidSimilarityAnalyzeResponse(BaseModel):
    success: bool
    status: int
    msgid: str
    message: str = "OK"
    reason: str | None = None
    body: MsgidSimilarityBodyResult | None = None
    attachments: list[MsgidSimilarityAttachmentResult] = Field(default_factory=list)
    processing: dict[str, Any] = Field(default_factory=dict)


class SearchDocumentsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    top_k: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)


class SearchLogsRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=255)
    top_k: int = Field(default=20, ge=1, le=200)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)


class SearchLogsByTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    top_k: int = Field(default=20, ge=1, le=200)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)


class SimilarityHit(BaseModel):
    score: float
    target_type: Literal["document", "log"]
    target_id: str
    chunk_id: str
    text_preview: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    success: bool
    status: int
    data: list[SimilarityHit]


class ReviewRequest(BaseModel):
    match_key: str = Field(min_length=1, max_length=512)
    decision: Literal["true_positive", "false_positive", "pending"]
    reason_code: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=255)
    review_scope: Literal["grey_zone", "high_risk", "low_risk", "manual"] = "manual"
    match: dict[str, Any] = Field(default_factory=dict)


class ReviewItem(BaseModel):
    match_key: str
    decision: Literal["true_positive", "false_positive", "pending"]
    reason_code: str
    comment: str | None = None
    reviewer: str | None = None
    review_scope: str = "manual"
    reviewed_at: datetime
    match: dict[str, Any] = Field(default_factory=dict)


class ReviewListResponse(BaseModel):
    success: bool
    status: int
    data: list[ReviewItem]


class ReviewResponse(BaseModel):
    success: bool
    status: int
    data: ReviewItem


class CollectionStats(BaseModel):
    document_chunks: int
    log_chunks: int
    documents: int
    logs: int
    documents_today: int = 0
    logs_today: int = 0
    document_index_bytes: int = 0
    log_index_bytes: int = 0
    total_index_bytes: int = 0
    storage_paths: list[dict[str, Any]] = Field(default_factory=list)
    monitor_alerts: list[dict[str, Any]] = Field(default_factory=list)
    retention_policy: dict[str, Any] = Field(default_factory=dict)
    recent_match_policy: dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    success: bool
    status: int
    data: CollectionStats


class ChunkItem(BaseModel):
    target_type: Literal["document", "log"]
    target_id: str
    chunk_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkListResponse(BaseModel):
    success: bool
    status: int
    data: list[ChunkItem]
    next_offset: str | None = None


class LogListItem(BaseModel):
    log_id: str
    chunk_count: int
    sample_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogListResponse(BaseModel):
    success: bool
    status: int
    data: list[LogListItem]
    next_offset: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    vector_backend: str
    embedder_backend: str
    embedding_model: str
    embedding_dim: int
    catalog_backend: str = "mongodb"
    catalog_database: str | None = None
    checked_at: datetime
    checks: dict[str, str] = Field(default_factory=dict)
