# Milvus 벡터 스키마 정의서

이 문서는 `xcn-similarity`가 Milvus에 생성하고 사용하는 벡터 컬렉션, 필드, 파티션, 검색 필터 규칙을 정의한다. MongoDB 카탈로그와 자체 MinIO 기준은 `docs/INTERNAL_STORAGE_SCHEMA.md`를 참조한다.

## 저장소 역할

|항목|내용|
|---|---|
|역할|문서/로그 청크 벡터와 청크 원문 저장|
|접속 환경변수|`SIM_MILVUS_URL`|
|기본 endpoint|`http://milvus:19530`|
|운영 컨테이너|`xcn-similarity-milvus`|
|Milvus 이미지|`xcn-similarity/milvus:v2.6.18`|
|실행 모드|standalone|
|메트릭|`COSINE`|
|인덱스 타입|`AUTOINDEX`|
|임베딩 차원|`SIM_EMBEDDING_DIM` 및 실제 embedder 차원|

Milvus는 벡터 검색의 원천이고, MongoDB `SIM_LOG_CATALOG`/`SIM_DOCUMENT_CATALOG`는 목록, 통계, 관리 화면용 카탈로그다. 두 저장소는 논리적으로 한 세트이므로 한쪽만 삭제하면 검색/목록/통계가 불일치한다.

관리 UI의 문서/로그 인덱스 용량은 청크 수 기반 추정치가 아니라 Milvus 내부 MinIO object storage의 실제 파일 크기 합산값이다. API 컨테이너는 `SIM_MILVUS_OBJECT_ROOT` 경로를 읽어 `insert_log`, `stats_log`, `delta_log`, `index_files`를 컬렉션 ID/파티션 ID 기준으로 합산한다. 운영 기본값은 `/minio_data/a-bucket/files`이며 `docker-compose.offline.yml`은 `/data01/xcn-similarity/data/minio`를 API에 read-only로 마운트한다.

운영 compose는 Docker named volume 대신 `/data01/xcn-similarity/data/{mongodb,etcd,minio,milvus}` bind mount를 사용한다. 대용량 로그 인덱스 증가 시 Docker 저장소가 root 파티션에 남아 먼저 차는 문제를 피하기 위한 기준이다. Docker 29.x/containerd snapshotter 환경에서는 Docker `data-root`뿐 아니라 containerd `root`도 데이터 디스크로 지정해야 하며, 75번 서버 기준은 `/data/docker-volumes`와 `/data/docker-volumes/containerd`다.

대시보드는 `/similarity/stats` 응답의 `total_index_bytes`, `storage_paths`, `monitor_alerts`, `recent_match_policy`, `retention_policy`를 사용해 전체 벡터 저장소 용량, 문서/로그별 물리 용량, 디스크 여유율, row count 임계치 상태를 표시한다. 기본 모니터링 경로는 `SIM_MONITOR_PATHS=/,/logs,/minio_data`이며, API 컨테이너 내부 경로 기준이다. 운영 서버에서는 `/logs`와 `/minio_data`가 `/data01/xcn-similarity` 하위 bind mount이므로 `/data01` 여유율 확인 용도로 사용한다.

최근 고위험 매칭은 UI 조회 시 캐시 전용으로 읽는다. 캐시 미스가 발생하면 대시보드 조회가 전체 재계산을 직접 유발하지 않으며, 스케줄러 또는 `refresh=true` 호출이 캐시를 갱신한다. `SIM_RECENT_MATCH_DOCUMENT_LIMIT=0`이면 등록문서 전체를 대상으로 계산한다. 0보다 큰 값으로 설정하고 등록문서 수가 제한값을 초과하면 보안등급, `metadata.priority`/`metadata.importance`, 최근 등록 여부, 문서형 파일 여부, 청크 수를 기준으로 우선순위를 매겨 일부 문서만 샘플링한다.

middleware 연동 흐름의 `/similarity/middleware/analyze` 호출은 middleware가 제공한 `svc`, `_id`로 xcn-similarity가 원천 MongoDB/MinIO에서 본문/첨부 텍스트를 직접 조회한 뒤 로그 본문/첨부를 청킹, 임베딩, Milvus upsert, MongoDB 로그 카탈로그 저장까지 수행한다. 이후 같은 배치에서 생성된 로그 청크 벡터로 등록문서 컬렉션을 검색하고, `msgid` 단위 유사도 결과를 `SIM_SIMILARITY_RESULT`에 저장한 뒤 middleware로 callback 전송한다.

레거시 EMS indexer의 `/similarity/logs/batch` 호출도 같은 내부 색인/결과 생성 로직을 사용하지만, 신규 운영 기본값에서는 `EMS_INDEX_DIRECT_ENABLED=false`로 원천 직접 스캔을 수행하지 않는다. 결과 payload는 `docs/SIMILARITY_KAFKA_RESULT_SCHEMA.md` 구조를 따른다.

보관 정책은 `SIM_RETENTION_HOT_DAYS`, `SIM_RETENTION_WARM_DAYS`, `SIM_RETENTION_ARCHIVE_DAYS`로 대시보드에 기준을 노출한다. 자동 삭제 또는 cold/archive 물리 이동은 데이터 유실 위험이 있으므로 기본 동작에 포함하지 않는다.

## 컬렉션 목록

|컬렉션|상수|용도|
|---|---|---|
|`document_chunks`|`DOCUMENT_COLLECTION`|등록 문서 청크 벡터|
|`log_body_chunks`|`LOG_COLLECTION`|EMS 본문/첨부 및 외부 로그 청크 벡터|

현재 코드는 로그 본문과 첨부를 모두 `log_body_chunks` 컬렉션에 저장한다. 첨부 여부는 컬렉션이 아니라 `metadata.source_type = "attachment"`로 구분한다.

## 공통 컬렉션 스키마

두 컬렉션은 동일한 Milvus schema를 사용한다.

|필드|Milvus 타입|필수|설명|
|---|---|---|---|
|`id`|`VarChar`|Y|Primary key. 최대 512 bytes|
|`vector`|`FloatVector`|Y|임베딩 벡터. 차원은 embedder 차원과 동일|
|`text`|`VarChar`|Y|청크 원문 또는 표시용 텍스트. 최대 65535 bytes|
|`metadata`|`JSON`|Y|검색 필터와 결과 표시용 메타데이터|

### 생성 파라미터

```json
{
  "autoID": false,
  "enableDynamicField": false,
  "fields": [
    {"fieldName": "id", "dataType": "VarChar", "isPrimary": true, "elementTypeParams": {"max_length": "512"}},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": "<embedder_dim>"}},
    {"fieldName": "text", "dataType": "VarChar", "elementTypeParams": {"max_length": "65535"}},
    {"fieldName": "metadata", "dataType": "JSON"}
  ]
}
```

### 벡터 인덱스

|필드|값|
|---|---|
|`fieldName`|`vector`|
|`indexName`|`vector_index`|
|`indexType`|`AUTOINDEX`|
|`metricType`|`COSINE`|

## `document_chunks`

등록 문서를 청킹한 결과를 저장한다.

### ID 규칙

|항목|값|
|---|---|
|문서 ID|`doc_` + `sha256(title + "\n" + normalized_text)` 앞 24 hex|
|청크 ID|chunker가 생성한 청크 ID|
|Milvus `id`|`<document_id>:<chunk_id>`|

예:

```text
doc_0123456789abcdef01234567:chunk_000001
```

### `metadata` 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`target_type`|string|Y|항상 `document`|
|`document_id`|string|Y|문서 식별자|
|`chunk_id`|string|Y|문서 내 청크 식별자|
|`title`|string|Y|문서명|
|`owner`|string/null|N|문서 소유자|
|`department`|string/null|N|부서|
|`security_level`|string/null|N|보안 등급|
|`file_name`|string|N|업로드 파일명|
|`file_ext`|string|N|파일 확장자|
|`file_size`|int|N|파일 크기|
|`file_checksum_sha256`|string|N|파일 체크섬|
|`checksum_sha256`|string|N|파일 체크섬 별칭|
|`description`|string|N|문서 설명|
|`file_retained`|bool|N|`false`이면 결과 응답에서 원문을 숨긴다.|

등록 요청의 `metadata`는 위 필드 외에도 JSON 값으로 보존될 수 있다. 단, Milvus collection은 `enableDynamicField=false`이므로 최상위 Milvus 필드는 `id`, `vector`, `text`, `metadata`로 고정된다.

### 텍스트 저장 규칙

|조건|`text` 저장값|
|---|---|
|`metadata.file_retained is false`|빈 문자열|
|그 외|청크 원문|

문서 원문을 숨긴 경우에도 `vector`는 저장되므로 검색은 가능하다.

## `log_body_chunks`

EMS 본문, EMS 첨부 추출 텍스트, 외부 로그 텍스트를 청킹한 결과를 저장한다.

### ID 규칙

|로그 유형|로그 ID|Milvus `id`|
|---|---|---|
|EMS 본문|`<msg_id>:body`|`<msg_id>:body:<chunk_id>`|
|EMS 첨부|`<msg_id>:attach:<index>`|`<msg_id>:attach:<index>:<chunk_id>`|
|외부 로그 API 입력|요청 `log_id`|`<log_id>:<chunk_id>`|

### `metadata` 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`target_type`|string|Y|항상 `log`|
|`log_id`|string|Y|로그 식별자|
|`chunk_id`|string|Y|로그 내 청크 식별자|
|`source`|string|N|대개 `ems`|
|`source_type`|string|N|`body`, `attachment` 등|
|`msg_id`|string|N|EMS 메시지 `_id`|
|`fileName`, `file_name`|string|N|EMS 본문 파일명 또는 첨부 파일명|
|`svc`|string|N|EMS 서비스 코드|
|`user_id`, `user_email`, `user_name`|string|N|사용자 정보|
|`src_ip`, `dst_ip`, `dst_port`, `host`|string/int|N|네트워크/HTTP 정보|
|`direction`, `directionSvc`|string|N|송수신 방향|
|`ctime`|string|N|원천 로그 생성 시각 ISO 문자열|
|`attachment_index`, `attach_index`|int|N|첨부 순번|
|`attach_id`|string|N|첨부 ID|
|`attach_name`, `attachment_name`|string|N|첨부 파일명|
|`attach_ext`, `attach_size`|string/int|N|첨부 확장자/크기|
|`attach_path`, `attach_textPath`|string|N|EMS 원천 MinIO object 경로|

## 파티션 규칙

### 문서 컬렉션

`document_chunks`는 별도 월별 파티션을 사용하지 않는다. 모든 문서 청크는 기본 파티션에 저장된다.

### 로그 컬렉션

`log_body_chunks`는 `metadata.target_type == "log"`이고 `metadata.ctime`을 ISO datetime으로 파싱할 수 있으면 월별 파티션에 저장한다.

|조건|파티션|
|---|---|
|`metadata.ctime` 파싱 가능|`m_YYYYMM`|
|`metadata.ctime` 없음 또는 파싱 실패|Milvus 기본 파티션|

예:

|`metadata.ctime`|파티션|
|---|---|
|`2026-06-11T17:12:44`|`m_202606`|
|`2026-05-31T23:59:52`|`m_202605`|

최근 매칭 API는 조회 기간의 월별 파티션명을 계산해 검색한다. `SIM_RECENT_MATCH_INCLUDE_DEFAULT_PARTITION=true`이면 기본 파티션도 함께 검색한다.

## 검색 및 필터 규칙

### 벡터 검색

|API 동작|검색 컬렉션|검색 벡터|
|---|---|---|
|텍스트로 유사 문서 검색|`document_chunks`|입력 텍스트 임베딩|
|문서로 유사 로그 검색|`log_body_chunks`|문서 청크 벡터 또는 문서 텍스트 임베딩|
|텍스트로 유사 로그 검색|`log_body_chunks`|입력 텍스트 청크 임베딩|
|최근 문서-로그 매칭|`log_body_chunks`|등록 문서 청크 벡터|

### score 기준

Milvus 검색 결과의 `distance` 또는 `score` 값을 유사도 score로 사용한다. `score < min_score`인 결과는 애플리케이션에서 제외한다. 기본 메트릭은 `COSINE`이다.

### JSON metadata filter 변환

API의 `metadata_filter`는 Milvus JSON 필터 문자열로 변환된다.

|입력|Milvus filter 예|
|---|---|
|`{"log_id": "A"}`|`metadata["log_id"] == "A"`|
|`{"document_id": "doc_1"}`|`metadata["document_id"] == "doc_1"`|
|`{"ctime": {"$gte": "2026-06-01T00:00:00+00:00"}}`|`metadata["ctime"] >= "2026-06-01T00:00:00+00:00"`|
|`{"svc": {"$in": ["EMMS", "ICLS"]}}`|`metadata["svc"] in ["EMMS", "ICLS"]`|

지원 연산자:

|연산자|의미|
|---|---|
|`$gte`, `gte`|크거나 같음|
|`$gt`, `gt`|큼|
|`$lte`, `lte`|작거나 같음|
|`$lt`, `lt`|작음|
|`$ne`, `ne`|같지 않음|
|`$in`, `in`|목록 포함|

지원하지 않는 연산자는 필터 문자열에 반영되지 않는다.

## 청킹 및 적재 제한

|항목|환경변수|기본값|설명|
|---|---|---:|---|
|문서 청크 크기|`SIM_CHUNK_SIZE`|`1800`|문자 기준 청크 크기|
|청크 overlap|`SIM_CHUNK_OVERLAP`|`250`|인접 청크 중복 문자 수|
|최소 청크 문자 수|`SIM_MIN_CHUNK_CHARS`|`50`|이보다 짧은 청크 제외|
|문서 최대 청크 수|`SIM_MAX_DOCUMENT_CHUNKS`|`5000`|문서 1건당 최대 청크|
|로그 최대 청크 수|`SIM_MAX_LOG_CHUNKS`|`100`|로그 1건당 최대 청크|
|Milvus text 최대 bytes|코드 고정|`65000`|UTF-8 기준 초과분 절단|

## MongoDB 카탈로그와의 매핑

|Milvus 컬렉션|MongoDB 카탈로그|매핑 키|비고|
|---|---|---|---|
|`document_chunks`|`SIM_DOCUMENT_CATALOG`|`metadata.document_id` = `document_id`|문서 목록/통계 기준|
|`log_body_chunks`|`SIM_LOG_CATALOG`|`metadata.log_id` = `log_id`|로그 목록/통계 기준|

통계 API의 `document_chunks`, `log_chunks`는 MongoDB 카탈로그의 `chunk_count` 합계를 기준으로 계산한다. 따라서 Milvus에는 벡터가 있는데 MongoDB 카탈로그가 누락되면 통계에 반영되지 않을 수 있다.

## 생성 및 적재 흐름

1. API 또는 indexer가 원문 텍스트를 정규화한다.
2. 정규화된 텍스트를 청킹한다.
3. 청크별 임베딩 벡터를 생성한다.
4. Milvus 컬렉션이 없으면 생성하고 load한다.
5. 로그 청크는 `metadata.ctime` 기준 월별 파티션을 생성하고 load한다.
6. `entities/upsert`로 `id`, `vector`, `text`, `metadata`를 저장한다.

EMS indexer는 `EMS_INDEX_POST_BATCH_SIZE` 단위로 `/similarity/logs/batch`를 호출한다. 배치 전송이 성공한 뒤에만 월별 cursor state를 저장하므로, 전송 실패 또는 프로세스 중단 시 다음 주기에 같은 구간을 다시 upsert한다. Milvus primary key가 고정되어 있어 재처리는 중복 저장이 아니라 갱신으로 처리된다.
7. MongoDB 카탈로그에 문서/로그 단위 메타데이터와 `chunk_count`를 저장한다.

## 삭제 규칙

|대상|Milvus 처리|MongoDB 처리|
|---|---|---|
|문서 삭제|`document_chunks`에서 `metadata.document_id` 필터로 삭제|`SIM_DOCUMENT_CATALOG.status = "DELETED"`로 표시|
|로그 보관 삭제|`log_body_chunks`에서 `metadata.svc`와 `metadata.ctime < delete_before` 필터로 삭제|`SIM_LOG_CATALOG`에서 같은 `svc`, `metadata.ctime` 조건으로 삭제|

Milvus `delete_by_metadata`는 필터에 맞는 entity 삭제를 요청하고, 삭제 수를 정확히 반환하지 않으므로 애플리케이션에서는 `-1`을 반환할 수 있다.

로그 보관 삭제는 `POST /similarity/logs/delete-by-retention`으로 수행한다. 기본은 `dry_run=true`이며, `delete_before`를 생략하면 `SIM_LOG_DELETE_BEFORE_DAYS`가 1 이상일 때만 cutoff를 계산한다.

## 운영 점검 명령

### 컨테이너 상태

```bash
cd /data01/xcn-similarity
docker compose ps
curl -sS --max-time 15 http://127.0.0.1:8010/health
curl -sS --max-time 15 http://127.0.0.1:8010/similarity/stats
```

### Milvus 컬렉션 존재 여부

```bash
curl -sS -X POST http://127.0.0.1:19530/v2/vectordb/collections/has \
  -H 'Content-Type: application/json' \
  -d '{"collectionName":"document_chunks"}'

curl -sS -X POST http://127.0.0.1:19530/v2/vectordb/collections/has \
  -H 'Content-Type: application/json' \
  -d '{"collectionName":"log_body_chunks"}'
```

### row count 확인

```bash
curl -sS -X POST http://127.0.0.1:19530/v2/vectordb/collections/get_stats \
  -H 'Content-Type: application/json' \
  -d '{"collectionName":"log_body_chunks"}'
```

### 로그 파티션 목록

```bash
curl -sS -X POST http://127.0.0.1:19530/v2/vectordb/partitions/list \
  -H 'Content-Type: application/json' \
  -d '{"collectionName":"log_body_chunks"}'
```

### 특정 로그 청크 조회

```bash
curl -sS -X POST http://127.0.0.1:19530/v2/vectordb/entities/query \
  -H 'Content-Type: application/json' \
  -d '{
    "collectionName": "log_body_chunks",
    "filter": "metadata[\"log_id\"] == \"20260611171244.K5CQQXRNVEFVWFLZTFKCTWY3QYNSTWO6:body\"",
    "outputFields": ["id", "text", "metadata"],
    "limit": 10
  }'
```

## 운영 주의사항

- 임베딩 차원(`SIM_EMBEDDING_DIM` 또는 모델 실제 차원)이 기존 컬렉션 schema와 달라지면 같은 컬렉션에 upsert할 수 없다. 모델/차원 변경 시 새 컬렉션 또는 재색인 계획이 필요하다.
- Milvus, etcd, MinIO 볼륨은 한 세트로 백업/복구해야 한다.
- `log_body_chunks`의 월별 파티션은 `metadata.ctime`에 의존한다. `ctime`이 비어 있으면 기본 파티션에 저장되어 최근 매칭 파티션 검색에서 누락될 수 있으므로 `SIM_RECENT_MATCH_INCLUDE_DEFAULT_PARTITION` 값을 함께 확인한다.
- MongoDB 카탈로그만 복구하고 Milvus를 복구하지 않으면 목록에는 보이지만 검색 결과가 비어 있을 수 있다.
- Milvus만 복구하고 MongoDB 카탈로그를 복구하지 않으면 검색은 일부 가능해도 목록/통계/관리 화면이 불완전할 수 있다.
- Milvus 내부 MinIO bucket/object는 애플리케이션 스키마가 아니므로 직접 수정하지 않는다.
