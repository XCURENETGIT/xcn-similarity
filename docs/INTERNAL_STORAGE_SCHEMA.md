# 자체 MongoDB / MinIO 스키마 정의서

이 문서는 `xcn-similarity`가 자체적으로 소유하거나 운영하는 MongoDB 컬렉션과 MinIO 사용 범위를 정의한다. EMS 원천 MongoDB/MinIO의 접속 정보와 원천 데이터 조회 규칙은 `docs/EMS_DATA_SOURCE.md`를 기준으로 한다.

## 저장소 구분

|구분|용도|소유 주체|비고|
|---|---|---|---|
|MongoDB `xcn_similarity`|문서/로그 카탈로그, 리뷰, 캐시, 인덱서 상태|`xcn-similarity`|API와 indexer가 직접 읽고 쓴다.|
|Milvus|문서/로그 청크 벡터와 청크 원문|`xcn-similarity`|Milvus REST API를 통해 접근한다.|
|자체 MinIO|Milvus 내부 object storage|Milvus|애플리케이션이 직접 bucket/object 스키마를 관리하지 않는다.|
|EMS 원천 MinIO|EMS 첨부/추출 텍스트 조회|EMS 원천|`docs/EMS_DATA_SOURCE.md` 참조.|
|파일시스템 `/logs/uploads`|사용자 업로드 임시 저장|`xcn-similarity`|MinIO가 아니라 API 컨테이너 로컬 볼륨이다.|

## MongoDB 공통 기준

|항목|값|
|---|---|
|기본 URI 환경변수|`SIM_CATALOG_MONGO_URI`|
|기본 DB 환경변수|`SIM_CATALOG_DATABASE`|
|기본 DB명|`xcn_similarity`|
|시간 필드|MongoDB `Date` 타입 또는 API 응답 시 ISO-8601 문자열|
|문서 ID 정책|업무 키를 별도 unique index로 관리하고 MongoDB `_id`는 내부 식별자로 둔다.|

운영 접속 정보, 계정, 비밀번호는 코드나 이 문서에 중복 기재하지 않고 기존 환경 파일 또는 운영 접속 문서를 따른다.

## 컬렉션 목록

기본 단독/연동 배포에서는 문서/로그 카탈로그, 유사도 결과, indexer 상태/실패 컬렉션만 필수로 사용한다. 리뷰, 최근 매칭 캐시, 보안 인사이트 컬렉션은 `docs/PRODUCT_MODES.md`의 기능 플래그가 켜진 경우에만 사용한다.

|컬렉션|환경변수|용도|
|---|---|---|
|`SIM_LOG_CATALOG`|`SIM_LOG_CATALOG_COLLECTION`|인덱싱된 로그 단위 카탈로그|
|`SIM_DOCUMENT_CATALOG`|`SIM_DOCUMENT_CATALOG_COLLECTION`|등록 문서 단위 카탈로그|
|`SIM_MATCH_REVIEW`|`SIM_REVIEW_COLLECTION`|로그-문서 매칭 검토 결과|
|`SIM_MATCH_CACHE`|`SIM_MATCH_CACHE_COLLECTION`|최근 매칭 계산 캐시|
|`SIM_SIMILARITY_RESULT`|`SIM_SIMILARITY_RESULT_COLLECTION`|EMS `msgid` 단위 유사도 분석 결과|
|`SIM_INDEXER_STATE`|`SIM_INDEXER_STATE_COLLECTION`|EMS indexer 월별 진행 상태|
|`SIM_INDEXER_FAILED`|`SIM_INDEXER_FAILED_COLLECTION`|EMS indexer 실패 항목|
|`SIM_SECURITY_INSIGHT`|`SIM_INSIGHT_COLLECTION`|보안 인사이트 생성 결과|

## `SIM_LOG_CATALOG`

로그 본문 또는 첨부 1건을 `log_id` 단위로 관리한다. 실제 벡터와 청크 원문은 Milvus `log_body_chunks` 컬렉션에 저장되고, 이 컬렉션은 목록/통계/필터용 메타데이터를 보관한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`log_id`|string|Y|로그 식별자. 예: `<msg_id>:body`, `<msg_id>:attach:<index>`|
|`source_type`|string|Y|`body`, `attachment` 등 원천 구분|
|`svc`|string|N|EMS 서비스 코드|
|`user_id`|string|N|사용자 ID|
|`chunk_count`|int|Y|Milvus에 저장된 청크 수|
|`sample_text`|string|N|목록 표시용 원문 미리보기. 최대 1000자|
|`metadata`|object|Y|로그 상세 메타데이터|
|`created_at`|date|Y|최초 등록 시각|
|`updated_at`|date|Y|마지막 갱신 시각|

### 주요 `metadata` 필드

|필드|타입|설명|
|---|---|---|
|`source`|string|대개 `ems`|
|`source_type`|string|본문/첨부 구분|
|`msg_id`|string|EMS 메시지 `_id`|
|`fileName`, `file_name`|string|EMS 본문 파일명|
|`svc`|string|EMS 서비스 코드|
|`user_id`, `user_email`, `user_name`|string|사용자 정보|
|`src_ip`, `dst_ip`, `dst_port`, `host`|string/int|네트워크/HTTP 정보|
|`direction`, `directionSvc`|string|송수신 방향|
|`ctime`|string|원천 로그 생성 시각 ISO 문자열|
|`attachment_index`, `attach_index`|int|첨부 순번|
|`attach_name`, `attachment_name`, `file_name`|string|첨부 파일명|
|`attach_ext`, `attach_size`|string/int|첨부 확장자/크기|
|`attach_path`, `attach_textPath`|string|EMS 원천 MinIO object 경로|

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_log_id`|`log_id` ASC|unique|
|`idx_source_type_log_id`|`source_type` ASC, `log_id` ASC|-|
|`idx_svc_log_id`|`svc` ASC, `log_id` ASC|-|
|`idx_user_id_log_id`|`user_id` ASC, `log_id` ASC|-|
|`idx_metadata_ctime_log_id`|`metadata.ctime` DESC, `log_id` DESC|-|
|`idx_updated_at`|`updated_at` DESC|-|
|`idx_created_at`|`created_at` DESC|-|

`svc`와 `metadata.ctime`이 저장되어 있으므로 원천 데이터 삭제 정책에 맞춘 로그 보관 삭제가 가능하다. 애플리케이션은 `POST /similarity/logs/delete-by-retention`에서 `svc` 정확 일치와 `metadata.ctime < delete_before` 조건으로 `SIM_LOG_CATALOG`와 Milvus `log_body_chunks`를 함께 삭제한다.

## `SIM_DOCUMENT_CATALOG`

등록 문서 1건을 `document_id` 단위로 관리한다. 실제 벡터와 청크 원문은 Milvus `document_chunks` 컬렉션에 저장된다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`document_id`|string|Y|문서 식별자. `doc_<hash>` 형식|
|`title`|string|Y|문서명|
|`owner`|string/null|N|문서 소유자|
|`department`|string/null|N|부서|
|`security_level`|string/null|N|보안 등급|
|`status`|string|Y|`INDEXED`, `DELETED` 등|
|`chunk_count`|int|Y|Milvus에 저장된 청크 수|
|`created_at`|date|Y|최초 등록 시각|
|`updated_at`|date|Y|마지막 갱신 시각|
|`deleted_at`|date/null|N|삭제 처리 시각|
|`metadata`|object|Y|파일/업로드/운영 메타데이터|

### 주요 `metadata` 필드

|필드|타입|설명|
|---|---|---|
|`file_name`|string|원본 파일명|
|`file_ext`|string|파일 확장자|
|`file_size`|int|파일 크기|
|`file_checksum_sha256`, `checksum_sha256`|string|파일 체크섬|
|`description`|string|설명|
|`file_retained`|bool|본문 보관 여부. `false`이면 문서 청크 원문 노출을 제한한다.|

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_document_id`|`document_id` ASC|unique|
|`idx_status_title`|`status` ASC, `title` ASC|-|
|`idx_status_created_at`|`status` ASC, `created_at` DESC|-|
|`idx_document_file_name`|`metadata.file_name` ASC|-|
|`idx_document_file_size`|`metadata.file_size` ASC|-|
|`idx_document_checksum_sha256`|`metadata.file_checksum_sha256` ASC|-|

## `SIM_MATCH_REVIEW`

사용자가 로그-문서 매칭 결과를 검토한 이력을 저장한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`match_key`|string|Y|매칭 식별자. 일반적으로 `<log_id>:<document_id>`|
|`decision`|string|Y|`true_positive`, `false_positive`, `pending`|
|`reason_code`|string|Y|판정 사유 코드|
|`comment`|string/null|N|검토 의견|
|`reviewer`|string/null|N|검토자|
|`review_scope`|string|Y|`grey_zone`, `high_risk`, `low_risk`, `manual` 등|
|`match`|object|N|검토 당시 매칭 결과 스냅샷|
|`reviewed_at`|date/string|Y|검토 시각|
|`created_at`|date|Y|최초 등록 시각|
|`updated_at`|date|Y|마지막 갱신 시각|

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_match_key`|`match_key` ASC|unique|
|`idx_decision_reviewed_at`|`decision` ASC, `reviewed_at` DESC|-|
|`idx_scope_reviewed_at`|`review_scope` ASC, `reviewed_at` DESC|-|
|`idx_reviewed_at`|`reviewed_at` DESC|-|

## `SIM_MATCH_CACHE`

최근 매칭 API의 계산 결과를 TTL처럼 사용하기 위한 애플리케이션 캐시다. MongoDB TTL index를 사용하지 않고, API가 `generated_at`과 `SIM_RECENT_MATCH_CACHE_TTL_SEC`를 비교해 만료 여부를 판단한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`cache_key`|string|Y|요청 파라미터 JSON의 SHA-256 해시|
|`params`|object|Y|캐시 키 생성에 사용한 파라미터|
|`hits`|array<object>|Y|매칭 결과 목록|
|`hit_count`|int|Y|결과 개수|
|`generated_at`|date|Y|캐시 생성 시각|
|`created_at`|date|Y|최초 등록 시각|
|`updated_at`|date|Y|마지막 갱신 시각|

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_cache_key`|`cache_key` ASC|unique|
|`idx_generated_at`|`generated_at` DESC|-|

## `SIM_SIMILARITY_RESULT`

EMS 로그 본문/첨부가 색인된 뒤 등록문서와 비교한 유사도 분석 결과를 `msgid` 단위로 저장한다. Kafka 전송은 별도 producer 추가 대상이며, 이 컬렉션은 Kafka payload 생성의 기준 데이터로 사용한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`type`|string|Y|Kafka payload 최상위 `type`. 유사도 분석 결과는 `similarity`|
|`msgid`|string|Y|EMS 메시지 고유 식별자|
|`data.similarity`|object|Y|`docs/SIMILARITY_KAFKA_RESULT_SCHEMA.md` 기준 유사도 결과 payload|
|`results_by_key`|object|Y|본문/첨부별 최신 결과. `body`, `attach_<n>` 키 사용|
|`summary`|object|Y|메시지 단위 탐지 여부, 최고점, 위험도, 매칭 수|
|`detected`|bool|Y|임계값 이상 매칭 존재 여부|
|`max_score`|number|Y|메시지 단위 최고 유사도|
|`max_document_id`|string/null|N|메시지 단위 최고 유사도 match의 등록문서 ID|
|`max_document_title`|string/null|N|메시지 단위 최고 유사도 match의 등록문서 제목|
|`match_count`|int|Y|전달 대상 매칭 수|
|`risk_level`|string|Y|`none`, `low`, `grey`, `high`|
|`delivery_status`|string|Y|Kafka 전송 상태 예약 필드. 현재 기본 `pending`|
|`middleware_delivery_status`|string|N|middleware callback 상태. `sent`, `failed` 등|
|`middleware_delivery_url`|string|N|결과를 POST한 middleware callback URL|
|`middleware_delivery_error`|string/null|N|middleware callback 실패 시 오류 요약|
|`middleware_delivery_response`|object|N|middleware callback 응답 일부|
|`middleware_delivery_updated_at`|date|N|middleware callback 상태 갱신 시각|
|`generated_at`|date|Y|결과 생성 시각|
|`created_at`|date|Y|최초 등록 시각|
|`updated_at`|date|Y|마지막 갱신 시각|

### `matches[]` 주요 내부 필드

`data.similarity.results[].matches[]`와 `results_by_key.<key>.matches[]`에는 Kafka payload 기준 필드 외에 결과 샘플 표시를 위한 근거 필드를 함께 저장한다.

|필드|타입|설명|
|---|---|---|
|`matched_terms`|array<string>|기존 호환 필드. 의미는 `matched_keywords`와 동일|
|`matched_keywords`|array<string>|등록문서 매칭 청크와 EMS 본문/첨부 매칭 청크 양쪽에 공통으로 나타난 대표 핵심어. 최대 8개. 전체 공통 단어 목록이 아니라 판정 사유 설명용|
|`matched_terms_description`|string|`matched_terms`/`matched_keywords` 의미 설명|
|`score_breakdown`|array|AI 유사도, 핵심어 일치, 문장흐름 3개 항목의 `[라벨, 값]` 배열|
|`raw_score`|number|AI 유사도 원점수. Milvus 청크 검색 최고 점수|
|`weighted_coverage_score`|number|핵심어 일치 점수. 숫자/코드/긴 키워드 가중 공통어구 비율|
|`phrase_match_score`|number|문장흐름 점수. 2~4개 핵심어 연속 구문 일치 정도|
|`score_weight_policy`|object|대표 점수에 반영되는 항목별 비중. 원문 보관 시 AI 유사도 85%, 핵심어 일치 10%, 문장흐름 5%|

현재 저장 결과의 대표 점수는 AI 유사도, 핵심어 일치, 문장흐름 3개 항목만 사용한다. 원문이 있어 근거 항목을 계산할 수 있으면 `score = raw_score * 0.85 + weighted_coverage_score * 0.10 + phrase_match_score * 0.05`로 계산하고, 원문이 없어 근거 항목을 계산할 수 없으면 AI 유사도 100%로 계산한다.

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_msgid`|`msgid` ASC|unique|
|`idx_generated_at`|`generated_at` DESC|-|
|`idx_detected_generated_at`|`detected` ASC, `generated_at` DESC|-|
|`idx_delivery_status_updated_at`|`delivery_status` ASC, `updated_at` DESC|-|

## `SIM_INDEXER_STATE`

EMS indexer가 월별 마지막 처리 위치와 사이클 상태를 저장한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`job`|string|Y|작업명. 기본값 `ems`|
|`month`|string|Y|대상 월 `yyyymm` 또는 `_cycle`|
|`cursor_field`|string|N|증분 처리 기준 필드. 기본값 `ltime`|
|`last_ltime`|date|N|월별 마지막 처리 EMS 메시지 `ltime`|
|`last_ctime`|date|N|`EMS_INDEX_CURSOR_FIELD=ctime` 사용 시 마지막 처리 `ctime`|
|`last_id`|string|N|동일 커서 값 내 정렬 보조 기준으로 사용하는 마지막 EMS 메시지 `_id`|
|`state_type`|string|N|`month`, `cycle` 등|
|`stats`|object|N|최근 처리 통계|
|`months`|array<string>|N|사이클 대상 월 목록. `_cycle` 문서에서 사용|
|`elapsed_sec`|number|N|사이클 수행 시간|
|`created_at`|date|Y|최초 등록 시각|
|`updated_at`|date|Y|마지막 갱신 시각|

### `stats` 필드

|필드|타입|설명|
|---|---|---|
|`messages`|int|처리한 메시지 수|
|`body_ok`, `body_fail`|int|본문 성공/실패 수|
|`attach_ok`, `attach_fail`|int|첨부 성공/실패 수|
|`skipped_empty`|int|본문 또는 첨부 텍스트가 비어 건너뛴 수|
|`seeded_latest`|int|과거 월 state seed 여부|

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_job_month`|`job` ASC, `month` ASC|unique|

## `SIM_INDEXER_FAILED`

EMS 원천 조회, MinIO 첨부 읽기, API 전송 중 실패한 항목을 저장한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`job`|string|Y|작업명|
|`month`|string|Y|대상 월 `yyyymm`|
|`msg_id`|string|Y|EMS 메시지 `_id`|
|`source_type`|string|Y|`body` 또는 `attachment`|
|`attach_index`|int/null|Y|첨부 순번. 본문은 `null`|
|`error`|string|Y|오류 메시지|
|`error_type`|string|Y|예외 타입|
|`retry_count`|int|Y|실패 기록 누적 횟수|
|`created_at`|date|Y|최초 실패 시각|
|`updated_at`|date|Y|마지막 실패 시각|

### 인덱스

|이름|키|속성|
|---|---|---|
|`ux_failed_item`|`job` ASC, `month` ASC, `msg_id` ASC, `source_type` ASC, `attach_index` ASC|unique|
|`idx_failed_updated_at`|`updated_at` ASC|-|

## `SIM_SECURITY_INSIGHT`

최근 매칭 결과를 바탕으로 생성한 보안 인사이트를 저장한다.

### 필드

|필드|타입|필수|설명|
|---|---|---|---|
|`summary`|string|N|인사이트 요약|
|`severity`|string|N|위험도|
|`reasons`|array<string>|N|판단 근거|
|`recommended_actions`|array<string>|N|권고 조치|
|`facts`|object|Y|생성에 사용한 통계와 매칭 근거|
|`source`|string|Y|`vllm` 또는 `fallback`|
|`model`|string|Y|사용 모델명 또는 fallback 명|
|`llm_error`|string/null|N|LLM 호출 실패 사유|
|`generated_at`|date|Y|생성 시각|
|`created_hour`|date|Y|시간 단위 버킷|
|`reason`|string|Y|생성 트리거. 예: `scheduled`, `manual`|
|`history_days`|int|Y|보관 기준 일수|

### 인덱스

|이름|키|속성|
|---|---|---|
|`idx_generated_at`|`generated_at` DESC|-|
|`idx_created_hour`|`created_hour` DESC|-|

오래된 인사이트는 생성 시점에 `generated_at < now - SIM_INSIGHT_HISTORY_DAYS` 조건으로 삭제된다.

## 자체 MinIO 사용 범위

`docker-compose.offline.yml`의 `minio` 서비스는 Milvus standalone이 vector index/object storage 용도로 사용하는 내부 구성요소다. `xcn-similarity` API와 indexer는 자체 MinIO에 직접 업무 object를 쓰지 않는다.

### 자체 MinIO에 대한 애플리케이션 규칙

|항목|정의|
|---|---|
|직접 관리 bucket|없음|
|직접 관리 object key prefix|없음|
|직접 저장하는 업무 파일|없음|
|스키마 소유자|Milvus|
|백업/복구 단위|Milvus 데이터 볼륨과 MinIO 데이터 볼륨을 같은 시점으로 취급|

Milvus가 자체 MinIO에 생성하는 bucket/object 구조는 Milvus 내부 구현에 속한다. 운영자가 임의로 bucket/object를 삭제하거나 재배치하면 Milvus 컬렉션과 벡터 인덱스가 손상될 수 있다.

## 외부 EMS MinIO 참조 규칙

EMS 첨부는 자체 MinIO가 아니라 EMS 원천 MinIO에서 읽는다. indexer는 EMS 메시지의 `attach[n].textPath`를 우선 사용하고, 없으면 `attach[n].path`를 사용한다.

경로 해석 규칙은 다음과 같다.

|입력 경로 형태|해석|
|---|---|
|`emass/...`|bucket `emass`, 나머지를 object key로 사용|
|`msg/...`|bucket `emass`, 입력값 전체를 object key로 사용|
|그 외 상대 경로|bucket `emass`, `msg/<입력값>`으로 보정|
|URL 형태|URL path만 추출한 뒤 위 규칙 적용|

외부 EMS MinIO의 bucket, prefix, 접속 기준은 `docs/EMS_DATA_SOURCE.md`를 따른다.

## 파일시스템 업로드 저장소

업로드 파일은 MinIO가 아니라 `SIM_UPLOAD_DIR` 경로에 저장된다.

|경로|용도|
|---|---|
|`SIM_UPLOAD_DIR`|문서 등록 업로드 임시 파일|
|`SIM_UPLOAD_DIR/search`|검색용 업로드 임시 파일|
|`<SIM_UPLOAD_DIR parent>/reviews/similarity_reviews.json`|구버전 리뷰 JSON 마이그레이션 대상|

업로드 파일은 텍스트 추출과 인덱싱 후 가능한 범위에서 삭제된다. 운영 데이터 기준의 장기 보관 저장소로 사용하지 않는다.

문서 등록 업로드에서 지원하는 단일 문건 확장자는 `.pdf`, `.doc`, `.docx`, `.odt`, `.hwp`, `.hwpx`, `.rtf`, `.xls`, `.xlsx`, `.csv`, `.tsv`, `.ppt`, `.pptx`, `.txt`, `.text`, `.log`, `.md`, `.markdown`, `.rst`, `.json`, `.jsonl`, `.xml`, `.yaml`, `.yml`, `.toml`, `.ini`, `.conf`, `.cfg`, `.properties`, `.env`, `.sql`, `.graphql`, `.proto`, `.html`, `.htm`, `.css`, `.scss`, `.sass`, `.less`, `.py`, `.pyw`, `.ipynb`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`, `.java`, `.kt`, `.kts`, `.go`, `.rs`, `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.cs`, `.php`, `.rb`, `.pl`, `.pm`, `.r`, `.scala`, `.swift`, `.dart`, `.lua`, `.groovy`, `.gradle`, `.sh`, `.bash`, `.zsh`, `.fish`, `.ps1`, `.bat`, `.cmd`, `.vue`, `.svelte`이다.

압축파일은 `.zip`, `.tar`, `.tar.gz`, `.tgz`를 지원한다. 압축 내부 파일은 위 단일 문건 지원 확장자에 해당하는 파일만 추출 및 인덱싱 대상이 된다. 상세 제한값은 `SIM_MAX_UPLOAD_MB`, `SIM_MULTI_UPLOAD_MAX_FILES`, `SIM_ARCHIVE_MAX_FILES`, `SIM_ARCHIVE_MAX_TOTAL_MB`, `SIM_ARCHIVE_MAX_MEMBER_MB` 환경변수를 따른다.

## 운영 점검 쿼리 예시

아래 예시는 컨테이너 내부 MongoDB 기준이다. 운영 접속 정보는 환경 설정을 따른다.

```bash
docker exec -it xcn-similarity-mongodb mongosh xcn_similarity
```

```javascript
db.SIM_LOG_CATALOG.countDocuments()
db.SIM_LOG_CATALOG.find({}, { _id: 0, log_id: 1, source_type: 1, svc: 1, chunk_count: 1, "metadata.ctime": 1 })
  .sort({ "metadata.ctime": -1 })
  .limit(5)

db.SIM_DOCUMENT_CATALOG.find({ status: { $ne: "DELETED" } }, { _id: 0, document_id: 1, title: 1, chunk_count: 1 })
db.SIM_INDEXER_STATE.find({ job: "ems" }, { _id: 0 }).sort({ updated_at: -1 })
db.SIM_INDEXER_FAILED.find({}, { _id: 0 }).sort({ updated_at: -1 }).limit(20)
```

## 변경 시 주의사항

- 컬렉션명과 DB명은 환경변수로 바꿀 수 있으나, 운영 중 변경하면 기존 카탈로그를 새 컬렉션으로 마이그레이션해야 한다.
- MongoDB 카탈로그와 Milvus 벡터 컬렉션은 논리적으로 한 세트다. 한쪽만 삭제하면 목록/검색/통계가 불일치한다.
- 자체 MinIO는 Milvus 내부 저장소이므로 애플리케이션 업무 파일 저장 용도로 사용하지 않는다.
- EMS 원천 접속 정보와 운영 계정 정보는 이 문서에 중복 기재하지 않는다.
