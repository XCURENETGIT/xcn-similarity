# XCN Similarity 외부 API

## Health

```http
GET /health
```

## 문서 등록

```http
POST /similarity/documents
Content-Type: application/json
```

```json
{
  "title": "영업전략.pdf",
  "text": "문서 추출 텍스트",
  "security_level": "대외비",
  "metadata": {
    "source": "manual-upload"
  }
}
```

입력 파라미터는 `title`, `text`, `security_level`, `metadata`만 사용한다. 과거 `owner`, `department` 입력은 공개 API에서 제외했다.

## 문서 삭제

```http
DELETE /similarity/documents/{document_id}
```

## 로그 본문 인덱싱

```http
POST /similarity/logs
Content-Type: application/json
```

```json
{
  "log_id": "20260501000428.TVUB...",
  "text": "복호화 본문 텍스트",
  "svc": "FGIR",
  "user_id": "test01",
  "ctime": "2026-05-01T00:04:28",
  "metadata": {
    "host": "example.com"
  }
}
```

## 로그 기준 유사 문서 검색

```http
POST /similarity/search/documents
Content-Type: application/json
```

```json
{
  "text": "외부 전송 로그 본문",
  "top_k": 10,
  "min_score": 0.7
}
```

## 문서 기준 유사 로그 검색

```http
POST /similarity/search/logs
Content-Type: application/json
```

```json
{
  "document_id": "doc_...",
  "top_k": 20,
  "min_score": 0.7,
  "metadata_filter": {
    "ctime": {
      "$gte": "2000-01-01T00:00:00+00:00",
      "$lte": "2099-12-31T23:59:59+00:00"
    }
  }
}
```

`metadata_filter.ctime`을 생략하면 운영 기본값으로 최근 `SIM_SEARCH_LOGS_DEFAULT_DAYS`일만 검색한다. 전체 기간 검색이 필요할 때만 위처럼 넓은 `ctime` 범위를 명시한다.
