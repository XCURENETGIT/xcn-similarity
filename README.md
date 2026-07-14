# xcn-similarity

문서와 EMS 로그의 본문·첨부를 벡터로 색인하고, 양방향 유사도 검색과 분석 결과 저장을 제공하는 FastAPI 서비스다.

현재 버전은 `1.0.0`이며 운영 배포는 Docker Compose와 오프라인 이미지를 기준으로 한다. MongoDB와 Milvus 등 상태 저장 인프라는 별도 프로젝트인 [`xcn-similarity-infra`](https://github.com/XCURENETGIT/xcn-similarity-infra)에서 운영한다.

## 주요 기능

- 텍스트 또는 파일 기반 문서 등록·수정·삭제
- PDF, Office, HWP/HWPX, RTF, 텍스트 및 압축파일 문서 추출
- EMS 로그 본문과 MinIO 첨부파일 조회·색인
- 로그 기준 유사 문서 검색과 문서 기준 유사 로그 검색
- `msgid` 단위 실시간 유사도 분석 및 결과 저장
- MongoDB 카탈로그와 Milvus 벡터 저장소 사용
- 선택적 Kafka 결과 전달
- 선택적 운영 UI, 수동 리뷰, 보안 인사이트 기능
- 로그·결과·캐시 데이터 자동 정리와 저장소 사용량 모니터링

## 구성

```text
EMS MongoDB / MinIO
        │
        ▼
xcn-similarity API ── 임베딩 모델
        │
        ├── MongoDB: 카탈로그, 분석 결과, 작업 상태
        ├── Milvus: 문서·로그 청크 벡터
        └── Kafka: 선택적 외부 결과 전달
```

기본 서비스는 다음과 같이 분리된다.

|구성|역할|기본 포트|
|---|---|---:|
|`api`|FastAPI 유사도 분석 서비스|8010, 18080|
|`indexer`|EMS 월별 컬렉션 직접 색인용 선택 프로필|내부|
|`kafka`|내장 Kafka 선택 프로필|19092|
|MongoDB|카탈로그 및 분석 결과 저장|27017|
|Milvus|벡터 저장 및 검색|19530|

MongoDB, Milvus, etcd, Milvus 내부 MinIO는 `xcn-similarity-infra`에서 관리한다. EMS 원천 MongoDB와 MinIO는 이 프로젝트가 소유하거나 초기화하는 대상이 아니다.

## 제품 모드

`SIM_PRODUCT_MODE`로 기본 기능 범위를 선택하고, 개별 기능 플래그로 최종 동작을 조정한다.

|모드|용도|기본 선택 기능|
|---|---|---|
|`standalone`|자체 MongoDB에 결과를 저장하는 단독 제품|UI off, LLM off, Kafka off|
|`integrated`|외부 시스템 API/Kafka 연동|UI off, Kafka는 명시적으로 활성화|
|`ops`|운영·개발 대시보드 사용|UI, 리뷰, 인사이트, 최근 매칭 캐시 on|

기본 `.env.example`은 `standalone`이며 `SIM_ADMIN_UI_ENABLED=false`다. UI가 꺼져 있어도 문서·로그·유사도 결과 등 핵심 데이터 저장 기능은 동작한다. UI 관련 부가 컬렉션은 해당 기능을 켰을 때만 사용한다.

자세한 내용은 [제품 모드 및 선택 기능](docs/PRODUCT_MODES.md)을 참고한다.

## 요구사항

- Docker Engine 및 Docker Compose
- NVIDIA GPU와 Container Toolkit
- 한국어 임베딩 모델 `upskyy_bge_m3_korean`
- 기동된 `xcn-similarity-infra` 또는 외부 MongoDB/Milvus
- EMS 연동 시 원천 MongoDB/MinIO 네트워크 접근

기본 임베딩 설정은 1024차원 Hugging Face transformer 모델이다. 모델 또는 차원을 변경하면 기존 벡터와 호환되지 않으므로 전체 재임베딩이 필요하다.

## 빠른 시작

환경 파일을 준비한다.

```bash
cp .env.example .env
```

`.env`에서 최소한 다음 항목을 실제 환경에 맞춘다.

```env
SIM_CATALOG_MONGO_URI=mongodb://<infra-host>:27017/xcn_similarity
SIM_MILVUS_URL=http://<infra-host>:19530
SIM_MODELS_VOLUME=/data/models
SIM_EMBEDDING_MODEL_PATH=/models/upskyy_bge_m3_korean
```

앱과 infra가 동일한 Docker network에 연결된 구성에서는 `<infra-host>` 대신 각각 `mongodb`, `milvus` 서비스명을 사용할 수 있다.

서비스를 기동한다.

```bash
docker compose -f docker-compose.offline.yml up -d
docker compose -f docker-compose.offline.yml ps
```

기본 상태를 확인한다.

```bash
curl -sS --max-time 15 http://127.0.0.1:8010/health
curl -sS --max-time 20 http://127.0.0.1:8010/similarity/stats
```

기본 `docker-compose.yml`도 `docker-compose.offline.yml`을 include하므로 아래 명령과 동일하게 사용할 수 있다.

```bash
docker compose up -d
```

개발 환경에서 앱과 로컬 인프라를 함께 기동할 때만 다음 구성을 사용한다.

```bash
docker compose -f docker-compose.local.yml up -d
```

## 선택 서비스

레거시 EMS 직접 indexer를 사용할 때만 프로필을 활성화한다.

```bash
docker compose -f docker-compose.app.yml --profile indexer up -d
```

기본 운영 흐름은 `EMS_INDEX_DIRECT_ENABLED=false`이며, 미들웨어가 `svc`와 `_id`를 전달하면 API가 EMS 원천에서 단건 데이터를 조회한다.

내장 Kafka가 필요한 경우 다음과 같이 실행한다.

```bash
SIM_PRODUCT_MODE=integrated SIM_KAFKA_ENABLED=true \
  docker compose -f docker-compose.offline.yml --profile kafka up -d
```

외부 Kafka를 사용하면 `SIM_KAFKA_BOOTSTRAP_SERVERS`만 외부 broker로 지정하고 내장 Kafka 프로필은 실행하지 않는다.

## 주요 API

|메서드|경로|설명|
|---|---|---|
|`GET`|`/health`|서비스와 벡터·카탈로그 설정 확인|
|`POST`|`/similarity/documents`|텍스트 문서 등록|
|`POST`|`/similarity/documents/upload`|파일 문서 등록|
|`GET`|`/similarity/documents`|문서 목록 조회|
|`DELETE`|`/similarity/documents/{document_id}`|문서 삭제|
|`POST`|`/similarity/logs`|로그 본문 색인|
|`POST`|`/similarity/middleware/analyze`|미들웨어 단건 분석|
|`POST`|`/similarity/analyze/msgid`|EMS `msgid` 기준 분석|
|`POST`|`/similarity/search/documents`|로그 텍스트 기준 유사 문서 검색|
|`POST`|`/similarity/search/logs`|문서 기준 유사 로그 검색|
|`GET`|`/similarity/results/{msgid}`|저장된 분석 결과 조회|
|`GET`|`/similarity/stats`|카탈로그·벡터·디스크 통계 조회|

전체 요청·응답 형식은 [API Reference](docs/API_REFERENCE.md), 외부 공개 범위는 [외부 API](docs/EXTERNAL_API.md)를 참고한다.

현재 API 자체 인증은 제공하지 않는다. 운영 환경에서는 네트워크, 방화벽 또는 리버스 프록시에서 접근을 제한해야 한다.

## 데이터 저장 및 정리

핵심 저장 대상은 다음과 같다.

- MongoDB: 문서·로그 카탈로그, 유사도 결과, indexer 상태
- Milvus: 문서 청크와 로그 본문·첨부 청크 벡터
- 로컬 파일: 업로드 원본과 애플리케이션 로그

기본 자동 정리 설정은 다음과 같다.

```env
SIM_CLEANUP_ENABLED=true
SIM_CLEANUP_INTERVAL_SEC=86400
SIM_CLEANUP_DRY_RUN=false
SIM_LOG_RETENTION_POLICY=*=365
SIM_LOG_RETENTION_DELETE_RESULTS=true
SIM_MATCH_CACHE_RETENTION_DAYS=7
```

로그 벡터와 카탈로그는 기본 365일 보관 후 정리하며 연결된 `msgid` 결과도 함께 삭제한다. 결과·리뷰의 독립 보관 기간이 `0`이면 해당 기준의 자동 삭제를 비활성화한다.

운영 데이터 삭제 전에는 반드시 dry-run으로 대상을 확인한다.

```bash
curl -sS -X POST http://127.0.0.1:8010/similarity/logs/delete-by-retention \
  -H 'Content-Type: application/json' \
  -d '{"dry_run":true}'
```

전체 정책은 [운영 정책](docs/OPERATIONS_POLICY.md)을 따른다.

## 테스트

외부 MongoDB와 Milvus 없이 실행 가능한 기본 테스트:

```bash
python -m unittest discover -s tests -v
```

Compose 설정 확인:

```bash
docker compose -f docker-compose.offline.yml --env-file .env.example config
```

검색 스모크 테스트:

```bash
curl -sS --max-time 120 \
  -X POST http://127.0.0.1:8010/similarity/search/logs/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"test similarity smoke","top_k":1,"min_score":0.0,"metadata_filter":{}}'
```

## 프로젝트 구조

```text
app/                      FastAPI와 유사도 엔진
app/admin/                선택적 운영 UI
bin/                      문서 추출 실행 파일
docs/                     API·설계·설치·운영 문서
scripts/                  패키징과 데이터 초기화 스크립트
tests/                    기본 검증 테스트
tools/                    EMS 색인·마이그레이션·성능 도구
vendor/                   오프라인 배포용 Python 의존성
docker-compose.app.yml    API, indexer, Kafka 구성
docker-compose.local.yml  앱과 로컬 인프라 통합 구성
docker-compose.offline.yml 운영 기본 구성
Dockerfile.offline        오프라인 운영 이미지
```

## 문서

- [API Reference](docs/API_REFERENCE.md)
- [외부 API](docs/EXTERNAL_API.md)
- [제품 모드](docs/PRODUCT_MODES.md)
- [운영 정책](docs/OPERATIONS_POLICY.md)
- [EMS 원천 데이터 기준](docs/EMS_DATA_SOURCE.md)
- [Milvus 스키마](docs/MILVUS_SCHEMA.md)
- [내부 저장 스키마](docs/INTERNAL_STORAGE_SCHEMA.md)
- [설치 매뉴얼](docs/INSTALL_XCN_SIMILARITY_APP_1.0.0.md)
- [운영 명령](docs/COMMANDS.md)

## 주의사항

- `.env`, 운영 로그, 데이터 디렉터리, 모델 파일과 배포 산출물은 Git에 커밋하지 않는다.
- 기능 데이터 초기화 시 EMS 원천 DB와 MinIO를 삭제하지 않는다.
- Milvus 데이터는 Milvus, etcd, 내부 MinIO를 동일 시점의 한 세트로 백업·복구한다.
- `18080`은 기존 연동 호환을 위한 API alias이므로 운영 연동 확인 없이 제거하지 않는다.
