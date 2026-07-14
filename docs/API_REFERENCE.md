# XCN Similarity API Reference

이 문서는 `xcn-similarity` FastAPI 서비스의 HTTP API 기준 문서다.

삭제/옵션 처리된 파라미터와 공개/운영 API 구분은 `docs/API_CLEANUP_20260701.md`를 함께 참조한다.

## 기본 정보

- 서비스명: `XCN Similarity`
- 현재 버전: `0.1.0`
- 기본 로컬 URL: `http://127.0.0.1:8010`
- 52번 서버 적용 시 기본 확인 URL: `http://127.0.0.1:8010/health`
- 주요 기능: 등록 문서 인덱싱, 로그 인덱싱, 문서-로그 벡터 유사도 검색, 최근 고위험 매칭, 수동 리뷰, 보안 인사이트
- 인증: 현재 API 레벨 인증 없음. 운영망 접근 제어는 네트워크/프록시/방화벽 기준으로 처리해야 한다.
- API에서 생성하는 모든 업무 타임스탬프는 `Asia/Seoul` 기준 ISO 8601(`+09:00`)로 반환한다. EMS 원천의 timezone 없는 `ctime`/`ltime`은 KST로 해석한다.

## 공통 응답 형식

대부분의 API는 아래 구조를 따른다.

```json
{
  "success": true,
  "status": 200,
  "data": {}
}
```

오류는 FastAPI 기본 오류 형식으로 반환된다.

```json
{
  "detail": "오류 메시지"
}
```

## 주요 데이터 모델

### DocumentInfo

```json
{
  "document_id": "doc_xxx",
  "title": "문서 제목",
  "owner": null,
  "department": null,
  "security_level": "대외비",
  "status": "INDEXED",
  "chunk_count": 12,
  "created_at": "2026-06-11T00:00:00Z",
  "deleted_at": null,
  "metadata": {}
}
```

`status` 값은 `PENDING`, `PROCESSING`, `INDEXED`, `FAILED`, `DELETED`, `SKIPPED` 중 하나다.

### LogInfo

```json
{
  "log_id": "20260610000604.xxxxx",
  "status": "INDEXED",
  "chunk_count": 3,
  "created_at": "2026-06-11T00:00:00Z",
  "metadata": {
    "svc": "EMMS",
    "user_id": "user01",
    "ctime": "2026-06-10T00:06:04"
  }
}
```

### SimilarityHit

```json
{
  "score": 0.9321,
  "target_type": "document",
  "target_id": "doc_xxx",
  "chunk_id": "doc_xxx:000001",
  "text_preview": "본문 일부",
  "metadata": {}
}
```

`score`는 벡터 유사도 점수다. 운영 화면의 고위험 기본 임계값은 환경변수 `SIM_RECENT_MATCH_MIN_SCORE` 기준이며 기본값은 `0.82`다.

## Health

### GET `/health`

서비스 상태와 벡터/임베딩 설정을 확인한다.

```bash
curl -sS http://127.0.0.1:8010/health
```

응답 예시:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "vector_backend": "milvus",
  "embedder_backend": "hf_transformer",
  "embedding_model": "upskyy_bge_m3_korean",
  "embedding_dim": 1024,
  "catalog_backend": "mongodb",
  "catalog_database": "xcn_similarity"
}
```

## 문서 API

문서 API는 기밀문서, 기준문서, 비교 대상 문서를 벡터 인덱스에 등록하고 조회한다.

### POST `/similarity/documents`

텍스트를 직접 전달해 문서를 등록한다.

요청:

```json
{
  "title": "영업전략.pdf",
  "text": "문서에서 추출한 전체 텍스트",
  "security_level": "대외비",
  "metadata": {
    "source": "manual"
  }
}
```

필드:

|필드|타입|필수|설명|
|---|---|---:|---|
|`title`|string|Y|문서 제목, 1~512자|
|`text`|string|Y|인덱싱할 문서 텍스트, 최대 20MB 문자 길이|
|`security_level`|string|null|N|보안 등급. `대외비`, `일반`만 사용|
|`metadata`|object|N|추가 메타데이터|

curl:

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/documents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "영업전략.pdf",
    "text": "문서에서 추출한 전체 텍스트",
    "security_level": "대외비",
    "metadata": {"source": "manual"}
  }'
```

응답: `DocumentRegisterResponse`

### POST `/similarity/documents/upload`

파일을 업로드해 텍스트를 추출하고 문서로 등록한다.

Content-Type: `multipart/form-data`

폼 필드:

|필드|타입|필수|기본값|설명|
|---|---|---:|---|---|
|`file`|file|Y|-|업로드 파일|
|`title`|string|N|파일명|문서 제목|
|`security_level`|string|N|`대외비`|보안 등급. `대외비`, `일반`만 사용|
|`retain_file`|bool|N|`true`|업로드 원본 보관 여부|
|`metadata_json`|string|N|`{}`|추가 메타데이터 JSON 문자열|

지원 확장자:

### 단일 문건 지원 확장자

|구분|지원 확장자|
|---|---|
|문서/오피스|`.pdf`, `.doc`, `.docx`, `.odt`, `.hwp`, `.hwpx`, `.rtf`, `.xls`, `.xlsx`, `.csv`, `.tsv`, `.ppt`, `.pptx`|
|일반 텍스트/마크업|`.txt`, `.text`, `.log`, `.md`, `.markdown`, `.rst`, `.json`, `.jsonl`, `.xml`, `.yaml`, `.yml`, `.toml`, `.ini`, `.conf`, `.cfg`, `.properties`, `.env`, `.sql`, `.graphql`, `.proto`, `.html`, `.htm`|
|소스/스크립트|`.css`, `.scss`, `.sass`, `.less`, `.py`, `.pyw`, `.ipynb`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`, `.java`, `.kt`, `.kts`, `.go`, `.rs`, `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.cs`, `.php`, `.rb`, `.pl`, `.pm`, `.r`, `.scala`, `.swift`, `.dart`, `.lua`, `.groovy`, `.gradle`, `.sh`, `.bash`, `.zsh`, `.fish`, `.ps1`, `.bat`, `.cmd`, `.vue`, `.svelte`|

### 압축파일 지원 확장자

|구분|지원 확장자|처리 기준|
|---|---|---|
|ZIP|`.zip`|압축 내부의 지원 단일 문건만 추출|
|TAR|`.tar`|압축 내부의 지원 단일 문건만 추출|
|Gzip TAR|`.tar.gz`, `.tgz`|압축 내부의 지원 단일 문건만 추출|

압축파일 안에 있는 파일도 위 "단일 문건 지원 확장자"에 포함된 경우에만 인덱싱한다. 지원하지 않는 내부 파일은 건너뛰며, 추출 가능한 텍스트가 없으면 `400`을 반환한다.

curl:

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/documents/upload \
  -F "file=@./sample.pdf" \
  -F "title=sample.pdf" \
  -F "security_level=대외비" \
  -F 'metadata_json={"source":"upload"}'
```

주의:

- 파일 크기는 `SIM_MAX_UPLOAD_MB` 기준이며 기본값은 `300MB`다.
- 같은 `file` 필드를 여러 번 보내면 파일별로 각각 별도 문서로 등록한다. 기본 최대 파일 수는 `50`개다.
- 압축파일은 내부에서 지원되는 단일 문건을 각각 별도 문서로 등록한다.
- 압축 해제 제한 기본값은 내부 파일 `500`개, 해제 총량 `1024MB`, 내부 파일 1개당 `100MB`다.
- 추출 텍스트가 비어 있으면 `400`을 반환한다.
- 지원하지 않는 확장자는 `400`을 반환한다.
- 운영 배포에서 문서 업로드 전체 기능은 `Dockerfile.offline` 기반 단일 이미지 구성을 기준으로 한다.

### GET `/similarity/documents`

등록된 문서 목록을 조회한다.

```bash
curl -sS http://127.0.0.1:8010/similarity/documents
```

응답: `DocumentListResponse`

### GET `/similarity/documents/search`

문서 카탈로그를 조건으로 검색한다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`query`|string|null|제목/메타데이터 검색어|
|`limit`|int|30|1~100으로 보정|
|`offset`|int|0|페이지 오프셋|
|`security_level`|string|null|보안 등급 필터|

```bash
curl -sS "http://127.0.0.1:8010/similarity/documents/search?query=영업&limit=20&security_level=대외비"
```

응답: `DocumentListResponse`

### PATCH `/similarity/documents/{document_id}`

문서 카탈로그 메타데이터를 수정한다. 벡터 본문은 재인덱싱하지 않는다.

요청:

```json
{
  "title": "수정된 제목",
  "security_level": "일반",
  "metadata": {
    "tag": "reclassified"
  }
}
```

응답: `DocumentRegisterResponse`

없는 문서면 `404`를 반환한다.

### GET `/similarity/documents/{document_id}/chunks`

문서의 벡터 청크를 조회한다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`limit`|int|50|1~200으로 보정|
|`offset`|string|null|다음 페이지 오프셋|

```bash
curl -sS "http://127.0.0.1:8010/similarity/documents/doc_xxx/chunks?limit=50"
```

응답:

```json
{
  "success": true,
  "status": 200,
  "data": [
    {
      "target_type": "document",
      "target_id": "doc_xxx",
      "chunk_id": "doc_xxx:000001",
      "text": "청크 본문",
      "metadata": {}
    }
  ],
  "next_offset": null
}
```

### DELETE `/similarity/documents/{document_id}`

문서를 삭제 처리하고 관련 벡터 청크를 제거한다.

```bash
curl -sS -X DELETE http://127.0.0.1:8010/similarity/documents/doc_xxx
```

응답:

```json
{
  "success": true,
  "status": 200,
  "document_id": "doc_xxx"
}
```

없는 문서면 `404`를 반환한다.

## 로그 API

로그 API는 EMS 본문/첨부 텍스트 또는 외부 로그 텍스트를 벡터 인덱스에 적재한다.

### POST `/similarity/logs`

로그 텍스트를 직접 인덱싱한다.

요청:

```json
{
  "log_id": "20260610000604.32OQ73T7TH6FTDPTL2LPQLC3H2VBOKWZ",
  "text": "로그 본문 또는 첨부 추출 텍스트",
  "svc": "EMMS",
  "user_id": "user01",
  "ctime": "2026-06-10T00:06:04",
  "metadata": {
    "source_type": "body"
  }
}
```

필드:

|필드|타입|필수|설명|
|---|---|---:|---|
|`log_id`|string|Y|로그 식별자|
|`text`|string|Y|인덱싱할 텍스트, 최대 20MB 문자 길이|
|`svc`|string|null|N|서비스 타입, 예: `EMMS`|
|`user_id`|string|null|N|사용자 식별자|
|`ctime`|datetime|null|N|로그 발생 시각|
|`metadata`|object|N|추가 메타데이터|

응답: `LogIndexResponse`

### POST `/similarity/middleware/analyze`

middleware가 `svc`, `_id`를 전달해 EMS 원천 1건의 본문/첨부 유사도 분석을 요청한다.

기본 흐름:

1. middleware는 `svc`, `_id`만 전달한다.
2. `xcn-similarity`가 기존 EMS 원천 MongoDB/MinIO 조회 규칙으로 해당 단건의 본문/첨부 텍스트를 직접 읽는다.
3. 읽은 본문/첨부 텍스트를 기존 로그 색인 및 유사도 분석 로직으로 처리한다.
4. 생성된 `SIM_SIMILARITY_RESULT` 결과를 API 응답으로 반환하고, `callback_url` 또는 `SIM_MIDDLEWARE_BASE_URL + SIM_MIDDLEWARE_RESULT_PATH`가 있으면 middleware로 POST한다.

요청:

```json
{
  "svc": "EMMS",
  "_id": "20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A",
  "callback_url": "http://middleware:8080/similarity/result",
  "metadata": {
    "request_id": "mw-001"
  }
}
```

테스트/비상용으로 요청에 `source_payload`를 넣으면 원천 DB/MinIO 조회 대신 해당 payload를 사용한다. 운영 기본은 `svc`, `_id` 기반 직접 원천 조회다.

```json
{
  "source_payload": {
    "message": {"_id": "20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A", "svc": "EMMS"},
    "body": {
      "text": "메일 본문 텍스트"
    },
    "attachments": [
      {
        "name": "attach.txt",
        "text": "첨부 추출 텍스트",
        "textPath": "msg/..."
      }
    ]
  }
}
```

응답:

```json
{
  "success": true,
  "status": 200,
  "svc": "EMMS",
  "source_id": "20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A",
  "indexed_logs": 2,
  "indexed_chunks": 8,
  "result_delivered": true,
  "result": {}
}
```

원천 메시지를 찾을 수 없거나 본문/첨부 텍스트가 없으면 404가 아니라 `200`으로 응답하고,
`result.summary.detected=false`, `result.summary.reason`으로 미탐지 사유를 반환한다.

### POST `/similarity/analyze/msgid`

`msgid` 또는 `_id`를 전달해 EMS 원천 1건의 본문/첨부를 읽고, 등록문서와 유사도를 즉시 분석한다.
Kafka 실시간 분석과 동일한 등록문서 검색 임계치(`SIM_SIMILARITY_RESULT_MIN_SCORE`)를 사용하며, 응답에는 임계치 이상 match만 포함한다.

요청:

```json
{
  "msgid": "20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A",
  "svc": "EMMS",
  "metadata": {
    "request_id": "manual-001"
  }
}
```

`msgid` 대신 `_id`를 사용할 수 있다. 테스트/비상용으로 `source_payload`를 넣으면 원천 DB/MinIO 조회 대신 해당 payload를 사용한다.

응답:

```json
{
  "success": true,
  "status": 200,
  "msgid": "20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A",
  "message": "OK",
  "body": null,
  "attachments": [
    {
      "attach_index": 0,
      "max_score": 0.91,
      "matches": [
        {
          "document_title": "등록문서 제목",
          "document_security_level": "대외비",
          "score_percent": 91.0
        }
      ]
    }
  ]
}
```

본문에서 임계치 이상 match가 없으면 `body`는 `null`이다. 첨부에서 임계치 이상 match가 없으면 `attachments`는 빈 배열이다.
원천 메시지를 찾을 수 없거나 본문/첨부 텍스트가 없으면 404가 아니라 `200`으로 응답하고,
`message=NO_RESULT`, `reason`으로 미탐지 사유를 반환한다.

```json
{
  "success": true,
  "status": 200,
  "msgid": "20990101000000.NOTFOUND",
  "message": "NO_RESULT",
  "reason": "EMS source message not found or no body/attachment text",
  "body": null,
  "attachments": []
}
```

### GET `/similarity/logs`

인덱싱된 로그 카탈로그를 조회한다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`limit`|int|100|1~1000으로 보정|
|`offset`|string|null|다음 페이지 오프셋|
|`source_type`|string|null|`body` 또는 `attachment`만 허용|
|`svc`|string|null|서비스 타입 부분 검색|
|`user_id`|string|null|사용자 ID 부분 검색|
|`order`|string|`desc`|정렬 방향|

```bash
curl -sS "http://127.0.0.1:8010/similarity/logs?limit=50&source_type=attachment&svc=EMMS"
```

응답: `LogListResponse`

### POST `/similarity/logs/delete-by-retention`

원천 데이터 삭제 정책과 맞춰, 지정한 `svc`이고 `ctime`이 기준 시각보다 오래된 로그 인덱스를 삭제한다. 삭제 대상은 Milvus `log_body_chunks`와 MongoDB `SIM_LOG_CATALOG`다.

기본값은 `dry_run=true`이므로 대상 건수만 확인한다. 실제 삭제는 `dry_run=false`를 명시해야 한다.

요청:

```json
{
  "svc": ["EMMS"],
  "delete_before": "2026-06-01T00:00:00+09:00",
  "dry_run": true
}
```

필드:

|필드|타입|필수|설명|
|---|---|---:|---|
|`svc`|string/list|Y|삭제 대상 서비스 코드. 정확히 일치하는 값만 삭제|
|`delete_before`|datetime|null|N|`metadata.ctime < delete_before` 조건. 생략 시 `SIM_LOG_DELETE_BEFORE_DAYS` 기준으로 계산|
|`dry_run`|bool|N|기본 `true`. `false`일 때만 실제 삭제|

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/logs/delete-by-retention \
  -H "Content-Type: application/json" \
  -d '{"svc":["EMMS"],"delete_before":"2026-06-01T00:00:00+09:00","dry_run":true}'
```

응답:

```json
{
  "success": true,
  "status": 200,
  "dry_run": true,
  "svc": ["EMMS"],
  "delete_before": "2026-06-01T00:00:00+09:00",
  "matched_logs": 120,
  "matched_chunks": 340,
  "catalog_deleted": 0,
  "vector_deleted": 0
}
```

Milvus 삭제 API는 삭제 건수를 정확히 반환하지 않을 수 있어 `vector_deleted`가 `-1`일 수 있다.

### GET `/similarity/logs/{log_id}/chunks`

로그의 벡터 청크를 조회한다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`limit`|int|50|1~200으로 보정|
|`offset`|string|null|다음 페이지 오프셋|

```bash
curl -sS "http://127.0.0.1:8010/similarity/logs/20260610000604.xxxx/chunks?limit=50"
```

응답: `ChunkListResponse`

## 검색 API

검색 API는 등록문서와 로그 벡터를 비교한다.

### POST `/similarity/search/documents`

입력 텍스트와 유사한 등록문서를 검색한다.

요청:

```json
{
  "text": "외부 전송 로그 본문 또는 첨부 텍스트",
  "top_k": 10,
  "min_score": 0.7,
  "metadata_filter": {
    "security_level": "대외비"
  }
}
```

필드:

|필드|타입|기본값|범위|설명|
|---|---|---|---|---|
|`text`|string|-|1~2,000,000자|검색 기준 텍스트|
|`top_k`|int|10|1~100|반환 개수|
|`min_score`|float|0.0|-1.0~1.0|최소 유사도|
|`metadata_filter`|object|`{}`|-|벡터 메타데이터 필터|

응답: `SearchResponse`

### POST `/similarity/search/documents/upload`

업로드 파일에서 텍스트를 추출해 유사한 등록문서를 검색한다.

Content-Type: `multipart/form-data`

폼 필드:

|필드|타입|필수|기본값|설명|
|---|---|---:|---|---|
|`file`|file|Y|-|검색 기준 파일|
|`top_k`|int|N|10|1~100으로 보정|
|`min_score`|float|N|0.0|-1.0~1.0으로 보정|

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/search/documents/upload \
  -F "file=@./suspect.docx" \
  -F "top_k=10" \
  -F "min_score=0.75"
```

### POST `/similarity/search/logs`

등록문서 ID를 기준으로 유사한 로그를 검색한다.

요청:

```json
{
  "document_id": "doc_xxx",
  "top_k": 20,
  "min_score": 0.7,
  "metadata_filter": {
    "source_type": "attachment",
    "svc": "EMMS"
  }
}
```

필드:

|필드|타입|기본값|범위|설명|
|---|---|---|---|---|
|`document_id`|string|-|1~255자|기준 문서 ID|
|`top_k`|int|20|1~200|반환 개수|
|`min_score`|float|0.0|-1.0~1.0|최소 유사도|
|`metadata_filter`|object|`{}`|-|로그 벡터 메타데이터 필터|

`metadata_filter.ctime`을 생략하면 운영 기본값으로 최근 `SIM_SEARCH_LOGS_DEFAULT_DAYS`일만 검색한다. 전체 기간 검색이 필요하면 `ctime` 범위를 명시한다.

전체 기간 검색 예시:

```json
{
  "document_id": "doc_xxx",
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

응답: `SearchResponse`

### POST `/similarity/search/logs/text`

입력 텍스트와 유사한 로그를 검색한다.

요청:

```json
{
  "text": "기밀문서 일부 텍스트",
  "top_k": 20,
  "min_score": 0.7,
  "metadata_filter": {
    "user_id": "user01"
  }
}
```

응답: `SearchResponse`

### POST `/similarity/search/logs/upload`

업로드 파일에서 텍스트를 추출해 유사한 로그를 검색한다.

Content-Type: `multipart/form-data`

폼 필드:

|필드|타입|필수|기본값|설명|
|---|---|---:|---|---|
|`file`|file|Y|-|검색 기준 파일|
|`top_k`|int|N|20|1~200으로 보정|
|`min_score`|float|N|0.0|-1.0~1.0으로 보정|
|`source_type`|string|N|null|`body` 또는 `attachment`|
|`svc`|string|N|null|서비스 타입 필터|
|`user_id`|string|N|null|사용자 ID 필터|

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/search/logs/upload \
  -F "file=@./confidential.pdf" \
  -F "top_k=20" \
  -F "min_score=0.82" \
  -F "source_type=attachment" \
  -F "svc=EMMS"
```

## 최근 고위험 매칭 API

### GET `/similarity/matches/recent`

최근 로그와 등록문서를 비교해 임계값 이상 매칭을 반환한다. 운영 화면의 유사도 탐지 목록에서 주로 사용한다.

Query Parameters:

|파라미터|타입|기본값|보정 범위|설명|
|---|---|---|---|---|
|`limit`|int|`SIM_RECENT_MATCH_LIMIT`|1~100|반환 매칭 수|
|`log_limit`|int|`SIM_RECENT_MATCH_LOG_LIMIT`|1~1000|최근 로그 후보 수|
|`min_score`|float|`SIM_RECENT_MATCH_MIN_SCORE`|-1.0~1.0|최소 유사도|
|`days`|int|`SIM_RECENT_MATCH_DAYS`|1~365|조회 기간|
|`refresh`|bool|false|-|true면 캐시 무시 후 재계산|

```bash
curl -sS "http://127.0.0.1:8010/similarity/matches/recent?limit=20&log_limit=1000&min_score=0.82&days=30&refresh=false"
```

특징:

- 결과는 `SearchResponse` 형식의 `SimilarityHit[]`다.
- `target_type`은 `document`로 반환된다.
- `metadata._match_log_id`에 매칭된 로그 ID가 들어간다.
- `metadata._match_log_chunk_id`에 매칭된 로그 청크 ID가 들어간다.
- `metadata._match_log_metadata`에 로그 측 메타데이터가 들어간다.
- `metadata._match_log_text_preview`에 로그 청크 미리보기가 들어간다.
- `SIM_RECENT_MATCH_CACHE_TTL_SEC` 동안 MongoDB `SIM_MATCH_CACHE`에 캐시된다.
- `refresh=true`를 주면 캐시를 무시하고 재계산한다.

## 통계 및 설정 API

### GET `/similarity/stats`

인덱싱 통계를 조회한다.

```bash
curl -sS http://127.0.0.1:8010/similarity/stats
```

응답:

```json
{
  "success": true,
  "status": 200,
  "data": {
    "document_chunks": 1000,
    "log_chunks": 5000,
    "documents": 25,
    "logs": 300,
    "documents_today": 1,
    "logs_today": 30,
    "document_index_bytes": 123456,
    "log_index_bytes": 456789,
    "total_index_bytes": 580245,
    "storage_paths": [],
    "monitor_alerts": [],
    "retention_policy": {},
    "recent_match_policy": {}
  }
}
```

### GET `/similarity/results`

로그 배치 색인 후 생성된 `msgid` 단위 유사도 분석 결과를 조회한다. Kafka 전송은 아직 수행하지 않으며, 이 API는 Kafka payload로 사용할 내부 저장 결과를 확인하는 용도다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`limit`|int|50|1~500으로 보정|
|`offset`|int|0|페이지 오프셋|
|`detected`|bool|null|탐지 여부 필터|
|`delivery_status`|string|null|전송 상태 예약 필드. 현재 기본 `pending`|

```bash
curl -sS "http://127.0.0.1:8010/similarity/results?limit=20&detected=true"
```

### GET `/similarity/results/{msgid}`

특정 EMS `msgid`의 유사도 분석 결과를 조회한다.

```bash
curl -sS "http://127.0.0.1:8010/similarity/results/20260507143827.xxxx"
```

저장된 결과가 없으면 404가 아니라 `200`으로 응답하고, `data=null`, `summary.detected=false`로 결과 없음 상태를 반환한다.

### GET `/similarity/results/recent-matches`

이미 생성되어 `SIM_SIMILARITY_RESULT`에 저장된 결과에서 최근 고위험 매칭만 조회한다. 대시보드는 이 API를 사용하며, 호출 시 유사도 재계산을 수행하지 않는다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`limit`|int|50|1~500으로 보정|
|`offset`|int|0|페이지 오프셋|
|`min_score`|float|`SIM_RECENT_MATCH_MIN_SCORE`|최소 유사도|
|`risk_level`|string|null|기본 `high`. 비우면 위험도 제한 없음|

```bash
curl -sS "http://127.0.0.1:8010/similarity/results/recent-matches?limit=50&min_score=0.82&risk_level=high"
```

### GET `/similarity/settings`

최근 매칭, 등록문서 기준 로그 검색, 수동 리뷰, grey zone 관련 런타임 설정을 조회한다.

```bash
curl -sS http://127.0.0.1:8010/similarity/settings
```

응답 예시:

```json
{
  "product_mode": "standalone",
  "admin_ui_enabled": false,
  "security_insight_enabled": false,
  "llm_enabled": false,
  "kafka_enabled": false,
  "manual_review_enabled": false,
  "recent_match_cache_enabled": false,
  "recent_match_min_score": 0.82,
  "recent_match_log_limit": 50,
  "recent_match_limit": 20,
  "recent_match_days": 30,
  "recent_match_cache_ttl_sec": 300,
  "recent_match_include_default_partition": true,
  "search_logs_default_days": 30,
  "search_logs_max_document_chunks": 8,
  "search_logs_parallelism": 4,
  "search_logs_cache_enabled": true,
  "search_logs_cache_ttl_sec": 300,
  "search_logs_include_default_partition": true,
  "grey_zone_low_score": 0.62,
  "grey_zone_high_score": 0.82
}
```

## 수동 리뷰 API

유사도 매칭 결과를 정탐/오탐/보류로 저장한다.

### GET `/similarity/reviews`

저장된 리뷰 목록을 조회한다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`match_key`|string|null|특정 매칭 키만 조회|
|`limit`|int|500|조회 개수|

```bash
curl -sS "http://127.0.0.1:8010/similarity/reviews?limit=100"
```

응답: `ReviewListResponse`

### POST `/similarity/reviews`

매칭 리뷰를 저장하거나 갱신한다. `match_key`는 unique key다.

요청:

```json
{
  "match_key": "log_id:doc_id",
  "decision": "true_positive",
  "reason_code": "confidential_document_leak",
  "comment": "등록문서와 첨부 내용이 매우 유사함",
  "reviewer": "security01",
  "review_scope": "high_risk",
  "match": {
    "score": 0.94,
    "log_id": "20260610000604.xxxx",
    "document_id": "doc_xxx"
  }
}
```

필드:

|필드|타입|필수|설명|
|---|---|---:|---|
|`match_key`|string|Y|매칭 식별자, unique|
|`decision`|enum|Y|`true_positive`, `false_positive`, `pending`|
|`reason_code`|string|Y|사유 코드|
|`comment`|string|null|N|리뷰 코멘트|
|`reviewer`|string|null|N|리뷰 담당자|
|`review_scope`|enum|N|`grey_zone`, `high_risk`, `low_risk`, `manual`|
|`match`|object|N|원본 매칭 데이터 스냅샷|

응답: `ReviewResponse`

## 보안 인사이트 API

보안 인사이트는 최근 고위험 유사도 매칭과 인덱스 통계를 기반으로 생성된다. `SIM_SECURITY_INSIGHT_ENABLED=true`일 때만 API와 worker가 동작한다. `SIM_LLM_ENABLED=true`이고 `SIM_LLM_URL`이 설정되어 있으면 LLM 요약을 시도하고, 실패하거나 미설정이면 규칙 기반 fallback을 사용한다.

### GET `/similarity/insights/security`

최신 보안 인사이트를 조회한다.

Query Parameters:

|파라미터|타입|기본값|설명|
|---|---|---|---|
|`force`|bool|false|true면 즉시 재생성|

```bash
curl -sS "http://127.0.0.1:8010/similarity/insights/security"
curl -sS "http://127.0.0.1:8010/similarity/insights/security?force=true"
```

응답 예시:

```json
{
  "success": true,
  "status": 200,
  "data": {
    "severity": "high",
    "headline": "등록문서와 매우 유사한 로그가 확인되어 정보유출 검토가 필요합니다.",
    "summary": "최근 고위험 매칭이 확인되었습니다.",
    "reasons": ["서비스 집중도: EMMS 10건"],
    "actions": ["고위험 매칭 목록에서 최고 유사도 항목을 확인합니다."],
    "facts": {},
    "source": "fallback",
    "model": "rule-fallback",
    "generated_at": "2026-06-11T00:00:00+00:00",
    "reason": "scheduled"
  }
}
```

### GET `/similarity/insights/security/history`

보안 인사이트 생성 이력을 조회한다.

Query Parameters:

|파라미터|타입|기본값|보정 범위|설명|
|---|---|---|---|---|
|`days`|int|`SIM_INSIGHT_HISTORY_DAYS`|1~30|조회 기간|
|`limit`|int|168|1~500|반환 개수|

```bash
curl -sS "http://127.0.0.1:8010/similarity/insights/security/history?days=7&limit=168"
```

## Admin UI

### GET `/admin`

관리 UI로 redirect한다.

### GET `/admin/`

관리 UI HTML을 반환한다.

### GET `/admin/{asset_path}`

관리 UI 정적 리소스를 반환한다.

이 세 API는 `include_in_schema=False`이며 OpenAPI 문서에는 노출되지 않는다. `SIM_ADMIN_UI_ENABLED=false`이면 404를 반환한다.

## 제품 모드

배포별 기능 구성은 `docs/PRODUCT_MODES.md`를 기준으로 한다. 기본값은 `SIM_PRODUCT_MODE=standalone`이며 UI, LLM, Kafka, 리뷰, 최근매칭 캐시는 비활성화된다.

## 운영 환경 변수

주요 API 동작에 영향을 주는 환경 변수:

|환경변수|기본값|설명|
|---|---|---|
|`SIM_MILVUS_URL`|`http://milvus:19530`|Milvus REST endpoint|
|`SIM_EMBEDDER_BACKEND`|`hash`|임베딩 백엔드|
|`SIM_EMBEDDING_MODEL_PATH`|빈 값|HF/SentenceTransformer 모델 경로|
|`SIM_EMBEDDING_DIM`|`384`|임베딩 차원|
|`SIM_PRODUCT_MODE`|`standalone`|제품 모드. `standalone`, `integrated`, `ops`|
|`SIM_ADMIN_UI_ENABLED`|`auto`|Admin UI 제공 여부. `auto`는 `ops`에서 on, 그 외 off|
|`SIM_SECURITY_INSIGHT_ENABLED`|`auto`|보안 인사이트 API/worker 사용 여부. `auto`는 `ops`에서 on, 그 외 off|
|`SIM_LLM_ENABLED`|`false`|보안 인사이트 LLM 호출 여부|
|`SIM_MANUAL_REVIEW_ENABLED`|`auto`|수동 검토 API 사용 여부. `auto`는 `ops`에서 on, 그 외 off|
|`SIM_RECENT_MATCH_CACHE_ENABLED`|`auto`|최근 매칭 계산 결과를 `SIM_MATCH_CACHE`에 저장할지 여부. `auto`는 `ops`에서 on, 그 외 off|
|`SIM_CHUNK_SIZE`|`1800`|청크 크기|
|`SIM_CHUNK_OVERLAP`|`250`|청크 overlap|
|`SIM_MIN_CHUNK_CHARS`|`50`|최소 청크 문자 수|
|`SIM_MAX_DOCUMENT_CHUNKS`|`5000`|문서별 최대 청크 수|
|`SIM_MAX_LOG_CHUNKS`|`100`|로그별 최대 청크 수|
|`SIM_MAX_UPLOAD_MB`|`300`|업로드 파일 최대 크기|
|`SIM_MULTI_UPLOAD_MAX_FILES`|`50`|한 번에 업로드 가능한 최대 파일 수|
|`SIM_ARCHIVE_MAX_FILES`|`500`|압축파일 내부 처리 최대 파일 수|
|`SIM_ARCHIVE_MAX_TOTAL_MB`|`1024`|압축파일 내부 해제 총량 제한|
|`SIM_ARCHIVE_MAX_MEMBER_MB`|`100`|압축파일 내부 단일 파일 크기 제한|
|`SIM_UPLOAD_DIR`|`/logs/uploads`|업로드 저장 경로|
|`SIM_RECENT_MATCH_MIN_SCORE`|`0.82`|최근 매칭 기본 임계값|
|`SIM_RECENT_MATCH_LOG_LIMIT`|`50`|최근 매칭 로그 후보 수|
|`SIM_RECENT_MATCH_LIMIT`|`20`|최근 매칭 반환 수|
|`SIM_RECENT_MATCH_DAYS`|`30`|최근 매칭 조회 기간|
|`SIM_RECENT_MATCH_CACHE_TTL_SEC`|`300`|최근 매칭 캐시 TTL|
|`SIM_RECENT_MATCH_DOCUMENT_LIMIT`|`0`|최근 매칭 계산 대상 등록문서 수 제한. `0`이면 제한 없음|
|`SIM_RECENT_MATCH_DOCUMENT_RECENT_DAYS`|`365`|최근 등록 문서 우선순위 판단 기간|
|`SIM_SIMILARITY_RESULT_ENABLED`|`true`|로그 배치 색인 후 유사도 결과 생성 여부|
|`SIM_SIMILARITY_RESULT_MIN_SCORE`|`0.82`|결과에 포함할 최소 유사도|
|`SIM_SIMILARITY_RESULT_TOP_K`|`5`|본문/첨부별 저장할 등록문서 매칭 최대 개수|
|`SIM_SIMILARITY_RESULT_SEARCH_RETRIES`|`5`|최근 등록 문서가 있을 때 결과 생성 검색을 재시도하는 횟수|
|`SIM_SIMILARITY_RESULT_SEARCH_RETRY_DELAY_SEC`|`0.5`|결과 생성 검색 재시도 간격 초|
|`SIM_SIMILARITY_RESULT_RECENT_DOCUMENT_WINDOW_SEC`|`30`|이 시간 안에 등록된 문서가 있을 때만 결과 생성 검색 재시도 활성화|
|`SIM_KAFKA_ENABLED`|`false`|유사도 분석 결과 Kafka 전송 여부|
|`SIM_KAFKA_BOOTSTRAP_SERVERS`|`kafka:9092`|Kafka bootstrap server 목록|
|`SIM_KAFKA_TOPIC`|`analysis_result`|유사도 분석 결과 전송 토픽|
|`SIM_KAFKA_CLIENT_ID`|`xcn-similarity`|Kafka producer client id|
|`SIM_KAFKA_TIMEOUT_SEC`|`5`|Kafka 전송 타임아웃 초|
|`SIM_MIDDLEWARE_BASE_URL`|빈 값|middleware 결과 전달 기본 URL|
|`SIM_MIDDLEWARE_RESULT_PATH`|`/similarity/result`|유사도 분석 결과를 전달할 middleware path|
|`SIM_MIDDLEWARE_TIMEOUT_SEC`|`30`|middleware HTTP 호출 타임아웃 초|
|`SIM_MONITOR_PATHS`|`/,/logs,/minio_data`|대시보드 디스크 사용량 확인 경로|
|`SIM_DISK_WARN_PERCENT`|`80`|디스크 경고 임계치|
|`SIM_DISK_CRITICAL_PERCENT`|`90`|디스크 위험 임계치|
|`SIM_VECTOR_ROW_WARN_COUNT`|`50000000`|문서/로그 벡터 row count 경고 임계치|
|`SIM_RETENTION_HOT_DAYS`|`90`|보관 정책 hot 구간 일수|
|`SIM_RETENTION_WARM_DAYS`|`365`|보관 정책 warm 구간 일수|
|`SIM_RETENTION_ARCHIVE_DAYS`|`1095`|보관 정책 archive 기준 일수|
|`SIM_LOG_DELETE_BEFORE_DAYS`|`0`|로그 보관 삭제 API에서 `delete_before` 생략 시 사용할 기준 일수. `0`이면 생략 불가|
|`SIM_CATALOG_MONGO_URI`|`mongodb://mongodb:27017/xcn_similarity?...`|카탈로그 MongoDB URI|
|`SIM_CATALOG_DATABASE`|`xcn_similarity`|카탈로그 DB|
|`SIM_LOG_CATALOG_COLLECTION`|`SIM_LOG_CATALOG`|로그 카탈로그 컬렉션|
|`SIM_DOCUMENT_CATALOG_COLLECTION`|`SIM_DOCUMENT_CATALOG`|문서 카탈로그 컬렉션|
|`SIM_REVIEW_COLLECTION`|`SIM_MATCH_REVIEW`|리뷰 컬렉션|
|`SIM_MATCH_CACHE_COLLECTION`|`SIM_MATCH_CACHE`|최근 매칭 캐시 컬렉션|
|`SIM_SIMILARITY_RESULT_COLLECTION`|`SIM_SIMILARITY_RESULT`|유사도 분석 결과 컬렉션|
|`SIM_LLM_URL`|빈 값|보안 인사이트 LLM endpoint. `SIM_LLM_ENABLED=true`일 때만 사용|
|`SIM_LLM_MODEL`|`qwen3.5-27b-fp8`|보안 인사이트 LLM 모델|
|`SIM_INSIGHT_INTERVAL_SEC`|`3600`|보안 인사이트 주기 생성 간격|
|`SIM_INSIGHT_HISTORY_DAYS`|`7`|보안 인사이트 보관 일수|

## 상태 코드

|상태 코드|상황|
|---:|---|
|`200`|정상|
|`400`|잘못된 요청, 지원하지 않는 파일 형식, 잘못된 `metadata_json`, 잘못된 `source_type`|
|`404`|문서 없음 또는 Admin 정적 파일 없음|
|`413`|업로드 파일 크기 초과|
|`422`|Pydantic 요청 검증 실패|
|`500`|텍스트 추출, 인덱싱, 외부 LLM 등 내부 처리 오류|

## 대표 사용 흐름

### 1. 기밀문서 등록 후 유사 로그 검색

```bash
DOC_ID=$(
  curl -sS -X POST http://127.0.0.1:8010/similarity/documents \
    -H "Content-Type: application/json" \
    -d '{"title":"기밀문서","text":"기밀 문서 본문","security_level":"대외비"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['document_id'])"
)

curl -sS -X POST http://127.0.0.1:8010/similarity/search/logs \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"$DOC_ID\",\"top_k\":20,\"min_score\":0.82}"
```

### 2. 로그 인덱싱 후 유사 문서 검색

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/logs \
  -H "Content-Type: application/json" \
  -d '{
    "log_id":"20260610000604.sample",
    "text":"외부 전송 로그 본문",
    "svc":"EMMS",
    "user_id":"user01",
    "ctime":"2026-06-10T00:06:04",
    "metadata":{"source_type":"body"}
  }'

curl -sS -X POST http://127.0.0.1:8010/similarity/search/documents \
  -H "Content-Type: application/json" \
  -d '{"text":"외부 전송 로그 본문","top_k":10,"min_score":0.82}'
```

### 3. 운영 대시보드용 최근 고위험 매칭 조회

```bash
curl -sS "http://127.0.0.1:8010/similarity/matches/recent?limit=20&log_limit=1000&min_score=0.82&days=30"
```

강제 재계산:

```bash
curl -sS "http://127.0.0.1:8010/similarity/matches/recent?limit=20&log_limit=1000&min_score=0.82&days=30&refresh=true"
```
