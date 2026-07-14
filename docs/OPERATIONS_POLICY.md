# xcn-similarity 운영 정책

이 문서는 운영 환경에서 `xcn-similarity`의 로그, 업로드 파일, EMS 임베딩 데이터, 유사도 검색 범위, 저장소/성능 제한을 관리하기 위한 기준이다. 운영 설정은 기본적으로 프로젝트 루트의 `.env`와 `docker-compose.app.yml`을 통해 컨테이너 환경변수로 주입된다.

## 적용 원칙

- 정책값은 `.env`에서 관리한다.
- 운영 시간대는 `Asia/Seoul`로 통일한다. API 응답과 애플리케이션 로그는 `+09:00` KST를 사용하고, EMS `ctime`/`ltime` 및 Milvus metadata 시간은 기존 원천 형식과 호환되는 timezone 없는 KST 문자열로 저장한다.
- UTC 또는 timezone이 포함된 `ctime` 검색·보존기간 입력은 KST로 변환한 뒤 필터와 월별 Milvus partition에 동일하게 적용한다.
- `.env` 또는 compose 환경변수 변경 후에는 API 컨테이너 재생성이 필요하다.
- 단순 코드 재시작만 필요한 경우가 아니라면 아래 명령을 기준으로 적용한다.

```bash
cd /users/xcn_docker/xcn-similarity
docker compose -f docker-compose.infra.yml -f docker-compose.app.yml up -d --no-deps --force-recreate api
curl -sS --max-time 15 http://127.0.0.1:8010/health
```

`/health`는 API 프로세스 상태만 반환하지 않고 MongoDB ping과 Milvus REST 연결을 함께 확인한다. 둘 중 하나라도 실패하면 HTTP 503을 반환한다.

- `docker restart xcn-similarity-api`는 기존 컨테이너를 재시작할 뿐이므로 `extra_hosts`, volume, 일부 compose 변경은 반영되지 않는다.
- 현재 75번 서버는 호스트 `/etc/hosts`를 컨테이너에 read-only로 마운트하여 원천 DB/MinIO 호스트명을 해석한다.

## 1. 로그 유지 기간

대상:

- EMS/미들웨어에서 수집되어 `log_body_chunks`에 저장된 로그 임베딩 벡터
- MongoDB 카탈로그의 `SIM_LOG_CATALOG`

현재 구현:

- cleanup worker가 기본 활성화되어 서비스 타입과 관계없이 365일이 지난 로그를 자동 삭제한다.
- `SIM_LOG_DELETE_BEFORE_DAYS`는 기본 cutoff 계산용 옵션이다.
- cleanup worker는 시작 30초 후 첫 정리를 실행하고 이후 기본 86400초마다 반복한다.
- 삭제는 `metadata.ctime` 기준으로 동작한다.

관련 설정:

```env
SIM_CLEANUP_ENABLED=true
SIM_CLEANUP_INTERVAL_SEC=86400
SIM_CLEANUP_DRY_RUN=false
SIM_RETENTION_HOT_DAYS=90
SIM_RETENTION_WARM_DAYS=365
SIM_RETENTION_ARCHIVE_DAYS=1095
SIM_LOG_DELETE_BEFORE_DAYS=365
SIM_LOG_RETENTION_SVC=
SIM_LOG_RETENTION_POLICY=*=365
SIM_LOG_RETENTION_DELETE_RESULTS=true
SIM_LOG_RETENTION_DELETE_REVIEWS=false
SIM_LOG_RETENTION_CLEAR_MATCH_CACHE=false
```

현재 의미:

- `SIM_RETENTION_HOT_DAYS`, `SIM_RETENTION_WARM_DAYS`, `SIM_RETENTION_ARCHIVE_DAYS`는 UI/운영 정책 표시용이다.
- 실제 hot/warm/archive 이동은 아직 자동 수행하지 않는다.
- 기본 운영 정책은 서비스 타입과 관계없이 로그 임베딩/로그 카탈로그를 365일 보관한다.
- `SIM_LOG_DELETE_BEFORE_DAYS=0`이면 삭제 API 호출 시 `delete_before`를 명시해야 한다.
- `SIM_LOG_RETENTION_POLICY`가 설정되면 cleanup worker는 서비스별 보관 기간을 우선 적용한다.
- `SIM_LOG_RETENTION_POLICY`가 비어 있으면 기존 방식대로 `SIM_CLEANUP_ENABLED=true`, `SIM_CLEANUP_DRY_RUN=false`, `SIM_LOG_DELETE_BEFORE_DAYS>0`, `SIM_LOG_RETENTION_SVC`가 모두 설정된 경우에만 cleanup worker가 로그 retention 삭제를 자동 실행한다.

서비스별 retention 정책:

```env
# 단일 서비스별 지정
SIM_LOG_RETENTION_POLICY=ITAQ=90,IBDS=180

# 같은 기간을 여러 서비스에 적용
SIM_LOG_RETENTION_POLICY=ITAQ+IBDS=90,QSLC=180

# 서비스 타입과 관계없이 전체 로그 임베딩을 365일 보관
SIM_LOG_RETENTION_POLICY=*=365
```

- 형식은 `서비스명=보관일수` 또는 `서비스명:보관일수`이다.
- 여러 항목은 comma, semicolon, newline으로 구분할 수 있다.
- 동일 보관일수에 여러 서비스를 묶을 때는 `+` 또는 `|`를 사용한다.
- 서비스 타입과 관계없는 전체 로그 임베딩 정책은 `*=365`, `all=365`, `__all__=365` 중 하나로 지정한다.
- `SIM_CLEANUP_DRY_RUN=true`이면 실제 삭제하지 않고 대상 건수만 계산한다.

로그 삭제 연계 정리:

- `SIM_LOG_RETENTION_DELETE_RESULTS=true`: 삭제 대상 로그의 `msgid` 기준으로 `SIM_SIMILARITY_RESULT`를 같이 정리한다. 기본값은 `true`이다.
- `SIM_LOG_RETENTION_DELETE_REVIEWS=false`: 삭제 대상 `log_id`가 포함된 수동 리뷰를 같이 정리한다. 리뷰는 운영 감사 데이터일 수 있으므로 기본값은 `false`이다.
- `SIM_LOG_RETENTION_CLEAR_MATCH_CACHE=false`: 로그 삭제 시 `SIM_MATCH_CACHE` 전체를 비운다. 캐시는 검색 조건 기반이라 특정 msgid와 1:1 매핑되지 않으므로 기본값은 `false`이고, 일반적으로 `SIM_MATCH_CACHE_RETENTION_DAYS` TTL 정리를 사용한다.

수동 삭제 절차:

1. dry-run으로 삭제 대상 확인

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/logs/delete-by-retention \
  -H 'Content-Type: application/json' \
  -d '{"svc":["ITAQ","IBDS"],"delete_before":"2026-07-01T00:00:00+09:00","dry_run":true}'
```

2. 결과의 `matched_logs`, `matched_chunks` 확인

3. 실제 삭제

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/logs/delete-by-retention \
  -H 'Content-Type: application/json' \
  -d '{"svc":["ITAQ","IBDS"],"delete_before":"2026-07-01T00:00:00+09:00","dry_run":false}'
```

운영 권장:

- 기본 보관 기간은 서비스 타입과 관계없이 365일이다.
- 정책 변경 전 수동 cleanup API의 `dry_run=true` 결과로 삭제 대상을 확인한다.
- 서비스별 삭제가 필요하면 `SIM_LOG_RETENTION_POLICY`의 `svc` 목록을 명확히 관리한다.

추가 옵션화 필요:

- 삭제 전 백업/export 정책

구현 상태:

- 자동 cleanup worker와 수동 cleanup API가 제공된다.
- 기본 운영값은 `SIM_CLEANUP_ENABLED=true`, `SIM_CLEANUP_DRY_RUN=false`이며 365일 로그 보관 정책을 자동 실행한다. 삭제 전 검증 환경에서는 `.env`에서 `SIM_CLEANUP_DRY_RUN=true`로 재정의한다.
- 서비스별 retention 정책은 `SIM_LOG_RETENTION_POLICY`로 지정한다.
- 로그 retention 삭제 시 `SIM_LOG_RETENTION_DELETE_RESULTS=true`이면 유사도 결과가 msgid 기준으로 같이 정리된다.
- 수동 확인 API:

```bash
curl -sS -X POST 'http://127.0.0.1:8010/similarity/admin/cleanup?dry_run=true'
```

## 2. 문서 등록 업로드 파일 보관 정책

대상:

- UI/API로 문서 등록 시 업로드된 원본 파일
- 기본 저장 위치: `SIM_UPLOAD_DIR`

관련 설정:

```env
SIM_UPLOAD_DIR=/logs/uploads
SIM_MAX_UPLOAD_MB=300
SIM_MULTI_UPLOAD_MAX_FILES=50
SIM_ARCHIVE_MAX_FILES=500
SIM_ARCHIVE_MAX_TOTAL_MB=1024
SIM_ARCHIVE_MAX_MEMBER_MB=100
SIM_UPLOAD_RETAIN_ORIGINAL=true
SIM_UPLOAD_DELETED_RETENTION_DAYS=0
SIM_SEARCH_UPLOAD_RETENTION_DAYS=7
```

현재 구현:

- 등록 API는 업로드 파일을 `SIM_UPLOAD_DIR` 아래에 저장한다.
- 등록 문서 metadata에 `upload_path`, `file_name`, `file_size`, `file_checksum_sha256` 등을 남긴다.
- 문서 삭제 API는 벡터와 카탈로그 상태를 삭제/DELETED 처리하지만, 원본 업로드 파일 삭제는 별도 자동 수행하지 않는다.
- 검색 업로드 파일은 `SIM_UPLOAD_DIR/search` 아래에 저장된다.
- 등록된 문서와 등록 원본 파일은 보관 기간과 관계없이 자동 삭제하지 않는 것을 기본 정책으로 한다.

운영 권장:

- 상용 운영에서는 등록 원본 파일을 감사/재임베딩 목적으로 보관하는 것을 기본으로 한다.
- 단, 디스크 사용량이 커질 수 있으므로 보관 기간을 별도 정책으로 정해야 한다.
- 문서 재임베딩이 필요한 경우 원본 파일이 필요하므로 즉시 삭제 정책은 권장하지 않는다.

권장 정책 예:

```text
등록 원본 파일: 문서가 ACTIVE 상태인 동안 보관
DELETED 문서 원본: 별도 승인 전까지 무기한 보관
검색용 임시 업로드: 7일 후 삭제
```

구현 상태:

- `SIM_UPLOAD_RETAIN_ORIGINAL`은 업로드 API에서 `retain_file`이 명시되지 않은 경우 기본값으로 사용된다.
- `SIM_SEARCH_UPLOAD_RETENTION_DAYS`가 1 이상이면 cleanup worker/API가 `SIM_UPLOAD_DIR/search` 아래 오래된 파일을 정리한다.
- `SIM_UPLOAD_DELETED_RETENTION_DAYS=0`이면 DELETED 문서 원본 파일도 자동 삭제하지 않는다.
- 등록 문서 원본의 무기한 보관 정책을 유지하려면 `SIM_UPLOAD_RETAIN_ORIGINAL=true`, `SIM_UPLOAD_DELETED_RETENTION_DAYS=0`을 사용한다.

## 3. EMS에서 수집된 임베딩 데이터 저장 기간

대상:

- `/similarity/middleware/analyze`
- `/similarity/analyze/msgid`
- EMS indexer가 저장한 로그 벡터
- MongoDB 카탈로그의 로그 목록과 유사도 결과

현재 구현:

- EMS 원천 데이터 자체는 삭제하지 않는다.
- xcn-similarity가 생성한 로그 임베딩 벡터와 카탈로그만 관리 대상이다.
- 저장 기간은 1번 로그 유지 기간 정책과 동일하게 관리하며, 기본 운영 정책은 서비스 타입과 관계없이 365일이다.

관련 설정:

```env
SIM_LOG_DELETE_BEFORE_DAYS=365
SIM_LOG_RETENTION_POLICY=*=365
SIM_LOG_RETENTION_DELETE_RESULTS=true
SIM_LOG_RETENTION_DELETE_REVIEWS=false
SIM_LOG_RETENTION_CLEAR_MATCH_CACHE=false
SIM_RETENTION_HOT_DAYS=90
SIM_RETENTION_WARM_DAYS=365
SIM_RETENTION_ARCHIVE_DAYS=1095
SIM_SIMILARITY_RESULT_COLLECTION=SIM_SIMILARITY_RESULT
SIM_RESULT_RETENTION_DAYS=0
SIM_MATCH_CACHE_RETENTION_DAYS=7
SIM_REVIEW_RETENTION_DAYS=0
```

주의:

- 로그 벡터 삭제 시 유사도 결과(`SIM_SIMILARITY_RESULT`)와 리뷰/캐시 데이터가 남을 수 있다.
- `SIM_LOG_RETENTION_DELETE_RESULTS=true`이면 로그 삭제 시 같은 msgid의 유사도 결과도 같이 삭제한다.
- 리뷰는 수동 판단/감사 이력이므로 `SIM_LOG_RETENTION_DELETE_REVIEWS=false`가 기본값이다.
- `SIM_MATCH_CACHE`는 검색 조건 캐시이며 특정 msgid와 정확히 매핑되지 않으므로 로그 삭제와 직접 연계하지 않고 TTL 정리를 기본으로 한다.

구현 상태:

- `SIM_RESULT_RETENTION_DAYS`가 1 이상이면 `SIM_SIMILARITY_RESULT`의 오래된 결과를 cleanup 대상에 포함한다.
- `SIM_MATCH_CACHE_RETENTION_DAYS`가 1 이상이면 `SIM_MATCH_CACHE`의 오래된 캐시를 cleanup 대상에 포함한다.
- `SIM_REVIEW_RETENTION_DAYS`가 1 이상이면 `SIM_MATCH_REVIEW`의 오래된 리뷰를 cleanup 대상에 포함한다.
- 로그 retention 삭제 시 결과 연계 삭제는 기본 활성화되어 있고, 리뷰/캐시 연계 삭제는 운영 정책 확정 후 옵션으로 활성화한다.

### 로깅 데이터와 등록문서 비교 범위

- `/similarity/middleware/analyze`, `/similarity/analyze/msgid`는 로깅 데이터 본문/첨부 임베딩을 등록된 모든 문서 벡터와 비교한다.
- 코드 기준 검색 필터는 등록문서 전체 대상이며, 서비스 타입별 문서 제한을 적용하지 않는다.
- 결과에는 `SIM_SIMILARITY_RESULT_MIN_SCORE` 이상의 match만 포함한다.

## 4. 로깅 데이터 유사도 검색 대상 범위

검색 방향은 크게 두 가지다.

1. 로그/EMS 텍스트를 등록 문서와 비교
2. 등록 문서를 기존 로그와 비교

### 4.1 EMS/미들웨어 분석 시 등록 문서 검색 범위

대상 API:

- `POST /similarity/middleware/analyze`
- `POST /similarity/analyze/msgid`

관련 설정:

```env
SIM_SIMILARITY_RESULT_ENABLED=true
SIM_SIMILARITY_RESULT_MIN_SCORE=0.82
SIM_SIMILARITY_RESULT_TOP_K=5
SIM_SIMILARITY_RESULT_SEARCH_RETRIES=5
SIM_SIMILARITY_RESULT_SEARCH_RETRY_DELAY_SEC=0.5
SIM_SIMILARITY_RESULT_RECENT_DOCUMENT_WINDOW_SEC=30
```

현재 구현:

- 로그/첨부 청크를 등록 문서 벡터 전체 대상으로 검색한다.
- 점수가 `SIM_SIMILARITY_RESULT_MIN_SCORE` 이상인 결과만 저장/응답한다.
- part별 상위 `SIM_SIMILARITY_RESULT_TOP_K` 결과를 유지한다.
- 최근 등록 문서가 있는 경우 검색 retry를 수행할 수 있다.

운영 권장:

- 상용 기본 임계치: `0.82`
- 오탐이 많으면 `0.85~0.90`으로 상향
- 미탐이 많으면 `0.75~0.80`으로 하향 검토
- `TOP_K`는 결과량과 응답 크기를 고려해 5~20 사이로 운영한다.

### 4.2 등록 문서 기준 로그 검색 범위

대상 기능:

- 문서 기준 기존 로그 유사도 검색
- 최근 매칭 조회

관련 설정:

```env
SIM_SEARCH_LOGS_DEFAULT_DAYS=30
SIM_SEARCH_LOGS_MAX_DOCUMENT_CHUNKS=8
SIM_SEARCH_LOGS_PARALLELISM=4
SIM_SEARCH_LOGS_CACHE_ENABLED=true
SIM_SEARCH_LOGS_CACHE_TTL_SEC=300
SIM_SEARCH_LOGS_INCLUDE_DEFAULT_PARTITION=true
SIM_RECENT_MATCH_DAYS=30
SIM_RECENT_MATCH_LOG_LIMIT=50
SIM_RECENT_MATCH_LIMIT=20
SIM_RECENT_MATCH_CACHE_TTL_SEC=1800
SIM_RECENT_MATCH_INCLUDE_DEFAULT_PARTITION=true
SIM_RECENT_MATCH_DOCUMENT_LIMIT=0
SIM_RECENT_MATCH_DOCUMENT_RECENT_DAYS=365
```

현재 구현:

- 기본 검색 기간은 30일이다.
- 문서가 큰 경우 검색에 사용할 문서 청크 수는 `SIM_SEARCH_LOGS_MAX_DOCUMENT_CHUNKS`로 제한한다.
- 병렬도와 캐시 TTL을 설정할 수 있다.
- 최근 매칭은 `SIM_RECENT_MATCH_DAYS`, `SIM_RECENT_MATCH_LIMIT`, `SIM_RECENT_MATCH_LOG_LIMIT` 기준으로 제한된다.

운영 권장:

- 반복 조회가 많으면 캐시를 유지한다.
- 정확도가 중요하면 `SIM_SEARCH_LOGS_MAX_DOCUMENT_CHUNKS`를 늘리되, 응답 시간이 증가한다.
- 운영 화면 기본 조회는 30일, 분석 요청은 필요 시 API 파라미터로 범위를 좁히는 방식을 권장한다.

## 5. 대용량 EMS/첨부 처리 제한

대상:

- 대용량 본문/첨부가 실시간 분석 API로 들어오는 경우

관련 설정:

```env
SIM_MIDDLEWARE_TIMEOUT_SEC=60
SIM_MAX_MIDDLEWARE_CHUNKS=100
SIM_MAX_MIDDLEWARE_CHARS=2000000
SIM_MAX_MIDDLEWARE_ITEM_CHARS=800000
SIM_MAX_LOG_CHUNKS=100
```

현재 구현:

- API 전체 처리 시간은 60초 예산으로 처리한다.
- 초과 시 이미 처리/저장된 청크는 버리지 않고 `PARTIAL`로 응답한다.
- 항목 하나가 80만 자를 넘으면 앞 80만 자까지 처리하고 초과분은 버린다.
- 요청 전체 청크는 100개로 제한한다.
- 제한 또는 타임아웃 발생 시 응답의 `processing`에 사유를 남긴다.

운영 기준:

- 대용량 ZIP/textPath는 전체 분석보다 앞부분 우선 분석이 기본이다.
- 모든 첨부 전체 분석이 필요하면 비동기 배치 기능으로 분리하는 것이 맞다.
- 실시간 미들웨어 경로에서는 60초 이상 동기 처리하지 않는다.

## 6. 저장소/디스크 모니터링 정책

관련 설정:

```env
SIM_MONITOR_PATHS=/,/logs,/minio_data
SIM_DISK_WARN_PERCENT=80
SIM_DISK_CRITICAL_PERCENT=90
SIM_VECTOR_ROW_WARN_COUNT=50000000
SIM_STORAGE_STATS_TTL_SEC=300
SIM_MILVUS_OBJECT_ROOT=/minio_data/a-bucket/files
```

현재 구현:

- `/similarity/stats`에서 문서/로그 벡터 row 수, Milvus 객체 사용량, 디스크 사용률을 제공한다.
- UI의 "대용량 운영 상태"는 이 API 값을 표시한다.
- `SIM_MILVUS_OBJECT_ROOT` 아래 Milvus object 파일을 기준으로 문서/로그 인덱스 bytes를 계산한다.
- 디스크 경로가 같은 장치면 UI에서 하나로 묶어 표시한다.

운영 권장:

- warning 80%, critical 90% 기준을 유지한다.
- `/logs`와 `/minio_data`가 같은 디스크에 있는 서버는 합산 사용률로 판단한다.
- Milvus 객체 사용량은 전체 디스크 사용량과 다르다. "벡터 인덱스 사용량"으로 해석한다.

## 7. API/애플리케이션 로그 정책

관련 설정:

```env
SIM_FILE_LOG_ENABLED=true
SIM_LOG_DIR=/logs
SIM_LOG_LEVEL=INFO
SIM_LOG_ROTATE_WHEN=midnight
SIM_LOG_BACKUP_DAYS=30
SIM_LOG_BACKUP_COUNT=30
SIM_LOG_MAX_BYTES=0
```

현재 구현:

- API 로그는 `/logs` 아래 파일로 남는다.
- 요청별 처리 시간, EMS 조회 시간, 임베딩 시간, upsert 시간, similarity search 시간, 대용량 partial 사유가 기록된다.

운영 권장:

- 운영 기본은 `INFO`.
- 장애 분석 시 일시적으로 `DEBUG`를 검토하되 로그량 증가에 주의한다.
- 기본은 일 단위 rotation이다.
- `SIM_LOG_MAX_BYTES`를 1 이상으로 설정하면 크기 기반 rotation으로 전환한다.
- `SIM_LOG_BACKUP_COUNT` 또는 `SIM_LOG_BACKUP_DAYS`로 보관 파일 수를 제어한다.

추가 옵션화 필요:

- gzip 압축 여부

## 8. 문서/로그 청킹 및 임베딩 정책

관련 설정:

```env
SIM_CHUNK_SIZE=1800
SIM_CHUNK_OVERLAP=250
SIM_MIN_CHUNK_CHARS=50
SIM_MAX_DOCUMENT_CHUNKS=5000
SIM_MAX_LOG_CHUNKS=100
SIM_EMBEDDER_BACKEND=hf_transformer
SIM_EMBEDDING_DIM=1024
SIM_EMBEDDING_MODEL_PATH=/models/upskyy_bge_m3_korean
```

운영 기준:

- 문서 등록은 최대 5000 청크까지 허용한다.
- 로그/EMS는 기본 100 청크 제한으로 실시간 처리 지연을 방지한다.
- 모델/차원 변경은 기존 벡터와 호환되지 않으므로 전체 재임베딩이 필요하다.

모델 변경 절차:

1. 신규 모델 경로 준비
2. `.env`의 `SIM_EMBEDDING_MODEL_PATH`, `SIM_EMBEDDING_DIM` 변경
3. API 재생성
4. 기존 문서/로그 재임베딩 계획 수립

## 9. 원천 접속 정책

관련 문서:

- `docs/EMS_DATA_SOURCE.md`

관련 설정:

```env
EMS_MONGO_URI=mongodb://emassai1:27018,emassai2:27018,emassai3:27018/venus?replicaSet=shard1rs&readPreference=primary&serverSelectionTimeoutMS=5000&connectTimeoutMS=10000
MINIO_ENDPOINT=http://emassai1:19000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
```

현재 75번 기준:

- 컨테이너 `/etc/hosts`는 호스트 `/etc/hosts`를 read-only 마운트한다.
- `emassai1`, `emassai2`, `emassai3`, `es01`, `es02`, `es03` 해석은 호스트 기준을 따른다.
- MongoDB replica set은 `emassai2`, `emassai3`로 정상 접속된다.
- MinIO는 `emassai1:19000`으로 정상 접속된다.

주의:

- 호스트 `/etc/hosts` 변경은 bind mount 특성상 컨테이너에서 파일 내용이 보인다.
- 단, 일부 애플리케이션/라이브러리 DNS 캐시가 있으면 API 재시작이 필요할 수 있다.

## 10. 변경 적용 체크리스트

설정 변경:

```bash
cd /users/xcn_docker/xcn-similarity
vi .env
docker compose -f docker-compose.infra.yml -f docker-compose.app.yml config >/tmp/xcn-similarity-compose-check.yml
docker compose -f docker-compose.infra.yml -f docker-compose.app.yml up -d --no-deps --force-recreate api
curl -sS --max-time 15 http://127.0.0.1:8010/health
curl -sS --max-time 20 http://127.0.0.1:8010/similarity/stats
```

로그 삭제 전:

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/logs/delete-by-retention \
  -H 'Content-Type: application/json' \
  -d '{"svc":"ITAQ","delete_before":"2026-07-01T00:00:00+09:00","dry_run":true}'
```

대용량 처리 확인:

```bash
grep 'middleware analyze processed' logs/similarity-api.log | tail -n 20
grep 'partial=True\|timeout=True\|limit_reached=True' logs/similarity-api.log | tail -n 20
```

저장소 확인:

```bash
curl -sS http://127.0.0.1:8010/similarity/stats | python3 -m json.tool
df -h / /data /users/xcn_docker/xcn-similarity/logs /data/infra/minio
```

## 11. 현재 추가 구현 권장 항목

구현 완료:

- 서비스별 retention policy
- 로그 retention 삭제 시 msgid 기준 유사도 결과 연계 삭제

아래 항목은 아직 추가 구현이 필요한 영역이다.

- retention 삭제 전 export/backup
- 대용량 전체 분석용 비동기 배치 API
- 운영 UI에서 retention dry-run/삭제 실행 기능
