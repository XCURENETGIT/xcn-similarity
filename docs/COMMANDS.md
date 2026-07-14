# XCN Similarity 명령어

## 로컬 실행

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

## 로컬 테스트

외부 MongoDB/Milvus 없이 실행 가능한 기본 검증 테스트:

```bash
python -m unittest discover -s tests -v
```

Windows에서 `python` 명령이 Microsoft Store stub으로 잡히면 Python Launcher를 사용한다.

```powershell
py -m unittest discover -s tests -v
```

## Docker 실행

```bash
cp .env.example .env
docker compose up -d
```

기본 `docker-compose.yml`은 호환용으로 `docker-compose.offline.yml`을 include하고, 현재 기본 실행은 애플리케이션 서비스만 기동한다. MongoDB/Milvus는 `xcn-similarity-infra` 프로젝트에서 별도로 운영한다.

```text
docker-compose.app.yml    # API, indexer, Kafka optional
```

개발/테스트 목적으로 앱과 인프라를 한 프로젝트에서 함께 띄워야 할 때만 `docker-compose.local.yml`을 사용한다.

```text
docker-compose.infra.yml  # MongoDB, Milvus, etcd, Milvus 내부 MinIO
docker-compose.app.yml    # API, indexer, Kafka optional
```

로컬 통합 기동:

```bash
docker compose -f docker-compose.local.yml up -d
```

## xcn-similarity 기능 데이터 초기화

`scripts/reset_xcn_similarity.sh`는 EMS 원천 데이터와 인프라 전체 볼륨을 유지하면서
xcn-similarity가 소유한 기능 데이터만 초기화한다.

초기화 대상:

- MongoDB `xcn_similarity` 데이터베이스
- Milvus `document_chunks`, `log_body_chunks` 컬렉션
- `logs/uploads` 아래 업로드 파일

초기화하지 않는 대상:

- EMS 원천 MongoDB `venus` 및 `EMS_MESSAGE_*`
- EMS 원천 MinIO object
- MongoDB/Milvus/etcd/MinIO 인프라 볼륨 전체
- Docker image와 다른 XCN 서비스
- 애플리케이션 실행 로그(기본값, `--include-logs` 사용 시에만 삭제)

먼저 대상을 확인한다.

```bash
cd /users/xcn_docker/xcn-similarity
./scripts/reset_xcn_similarity.sh --dry-run
```

대화형 확인 후 초기화한다.

```bash
./scripts/reset_xcn_similarity.sh
```

자동화 환경에서 확인 입력을 생략하려면 명시적으로 `--yes`를 사용한다.

```bash
./scripts/reset_xcn_similarity.sh --yes
```

실행 중 API와 indexer 컨테이너만 잠시 중지하며, 실행 전에 동작 중이었던 컨테이너는
초기화 후 다시 시작한다. API 재기동 시 health check도 수행한다. 전체 옵션은
`./scripts/reset_xcn_similarity.sh --help`로 확인한다.

애플리케이션만 재기동할 때는 인프라를 건드리지 않고 app compose만 사용한다.

```bash
docker compose -f docker-compose.app.yml up -d --build
```

EMS indexer까지 함께 실행해야 하면 `.env`에 `COMPOSE_PROFILES=indexer`를 지정하거나 명령에 profile을 명시한다.

```bash
docker compose -f docker-compose.app.yml --profile indexer up -d
```

## 외부망 차단 서버 실행

서버에 런타임 이미지가 이미 있는 경우 기본 compose 명령으로 실행한다.

```bash
docker compose up -d
```

EMS indexer까지 함께 실행해야 하면 `.env`에 다음 값을 지정한 뒤 실행한다.

```bash
COMPOSE_PROFILES=indexer
docker compose up -d
```

EMS indexer는 기본적으로 원천 MongoDB 월별 메시지 컬렉션에 `ltime_1__id_1` 인덱스를 보장한다.

```text
EMS_INDEX_CURSOR_FIELD=ltime
EMS_INDEX_TIMEZONE=Asia/Seoul
EMS_INDEX_ENSURE_SOURCE_INDEXES=true
EMS_INDEX_POST_BATCH_SIZE=50
```

## MongoDB / Milvus 외부화 순서

1차 분리는 compose 파일만 분리하고 같은 Docker network, 같은 `/data01/xcn-similarity/data/*` bind mount를 사용한다.

2차 외부화는 `C:\xcn_prj\xcn-similarity-infra` / `/data01/xcn-similarity-infra` 프로젝트에서 진행한다. MongoDB와 Milvus 묶음 데이터는 `/data01/xcn-similarity-infra/data`로 이동한다.

운영 서버 기준:

```bash
cd /data01/xcn-similarity-infra
cp .env.example .env
docker compose config
docker compose up -d
docker compose ps
```

그 다음 `xcn-similarity` 앱의 `.env`에서 카탈로그 MongoDB와 Milvus를 infra host endpoint로 바꾼 뒤 app compose만 재기동한다.

```text
SIM_CATALOG_MONGO_URI=mongodb://10.100.40.52:27017/xcn_similarity?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000
SIM_MILVUS_URL=http://10.100.40.52:19530
SIM_MILVUS_MINIO_VOLUME=/data01/xcn-similarity-infra/data/minio
EMS_MONGO_URI=mongodb://<ems-host>:27018/venus?replicaSet=shard1rs&readPreference=primary&serverSelectionTimeoutMS=5000&connectTimeoutMS=10000&directConnection=true
```

MongoDB 외부화 확인:

```bash
docker compose -f docker-compose.app.yml up -d
curl -sS --max-time 15 http://127.0.0.1:8010/health
curl -sS --max-time 15 http://127.0.0.1:8010/similarity/stats
```

향후 데이터 물리 경로까지 `/data01/xcn-similarity-infra/data`로 옮길 경우, Milvus는 `milvus`, `etcd`, Milvus 내부 `minio` 데이터를 한 세트로 이전하고, 앱의 read-only MinIO volume도 같이 변경한다.

```text
SIM_MILVUS_MINIO_VOLUME=/data01/xcn-similarity-infra/data/minio
```

주의: 현재 API는 `SIM_MILVUS_OBJECT_ROOT=/minio_data/a-bucket/files`를 읽어 Milvus 내부 MinIO object 용량을 계산한다. Milvus/MinIO가 다른 서버로 이동하면 API 호스트에서 같은 경로를 읽을 수 없으므로, `/similarity/stats`의 물리 저장 용량 통계는 별도 마운트 또는 코드 변경 없이는 정확하지 않을 수 있다.

Milvus 외부화 확인:

```bash
curl -sS --max-time 15 http://127.0.0.1:8010/health
curl -sS -X POST http://<milvus-host>:19530/v2/vectordb/collections/has \
  -H 'Content-Type: application/json' \
  -d '{"collectionName":"document_chunks"}'
curl -sS -X POST http://<milvus-host>:19530/v2/vectordb/collections/has \
  -H 'Content-Type: application/json' \
  -d '{"collectionName":"log_body_chunks"}'
```

`EMS_INDEX_MONTHS=auto_recent`의 월별 컬렉션 계산은 `EMS_INDEX_TIMEZONE` 기준이다. 운영 기본값은 한국시간(`Asia/Seoul`)이므로 월초 KST 기준으로 새 EMS 월 컬렉션이 포함된다.

수동으로 사전 생성하려면 원천 MongoDB `venus` DB에서 월별로 실행한다.

```javascript
db.EMS_MESSAGE_yyyymm.createIndex({ ltime: 1, _id: 1 }, { name: "ltime_1__id_1", background: true })
```

## 중지

```bash
docker compose down
```

## 기본 환경변수

```text
SIM_MILVUS_URL=http://milvus:19530
SIM_EMBEDDER_BACKEND=hf_transformer
SIM_EMBEDDING_MODEL_PATH=/models/upskyy_bge_m3_korean
SIM_EMBEDDING_DIM=1024
SIM_CHUNK_SIZE=1800
SIM_CHUNK_OVERLAP=250
SIM_MAX_UPLOAD_MB=300
SIM_MULTI_UPLOAD_MAX_FILES=50
SIM_ARCHIVE_MAX_FILES=500
SIM_ARCHIVE_MAX_TOTAL_MB=1024
SIM_ARCHIVE_MAX_MEMBER_MB=100
SIM_MAX_DOCUMENT_CHUNKS=5000
SIM_MAX_LOG_CHUNKS=100
```

## EMS 5월 데이터 백필

원천 데이터 조회 기준은 [EMS_DATA_SOURCE.md](EMS_DATA_SOURCE.md)를 따른다.

2026년 5월 기준:

```text
MongoDB: mongodb://10.10.20.6:27018/venus?replicaSet=shard1rs&readPreference=primary&serverSelectionTimeoutMS=5000&connectTimeoutMS=10000&directConnection=true
message collection: EMS_MESSAGE_202605
body collections: EMS_BODY_202605.files, EMS_BODY_202605.chunks
attachment storage: MinIO http://10.10.20.6:19000/ / bucket emass / prefix msg
```

본문은 `EMS_MESSAGE_202605.fileName`을 기준으로 `EMS_BODY_202605`에서 조회한다. 첨부는 `EMS_MESSAGE_202605.attach[n]`을 확인하고, `attach[n].textPath`를 우선 사용하며 없으면 `attach[n].path`를 MinIO에서 조회한다.

```bash
docker run -d --name xcn-similarity-backfill-202605 \
  --network xcn-similarity_default \
  -e PYTHONPATH=/work/vendor \
  -v /data01/xcn-similarity:/work \
  -w /work \
  xcn-similarity/api:0.1.0 \
  python tools/backfill_ems_may.py \
    --month 202605 \
    --api-url http://xcn-similarity-api:8000 \
    --batch-size 1000 \
    --progress-every 1000 \
    --state-file logs/backfill_ems_202605.state
```

상태 확인:

```bash
docker logs --tail 100 xcn-similarity-backfill-202605
cat /data01/xcn-similarity/logs/backfill_ems_202605.state
curl -s -X POST http://127.0.0.1:6333/collections/log_body_chunks/points/count \
  -H "Content-Type: application/json" \
  -d '{"exact":true}'
```
