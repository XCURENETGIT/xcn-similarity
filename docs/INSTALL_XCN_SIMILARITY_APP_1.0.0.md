# xcn-similarity 1.0.0 설치 매뉴얼

이 문서는 `xcn-similarity-package-1.0.0-final.tar.gz` 기준의 오프라인 설치 절차다.

## 1. 패키지 정보

패키지 파일:

```text
xcn-similarity-package-1.0.0-final.tar.gz
xcn-similarity-package-1.0.0-final.tar.gz.sha256
```

SHA256:

```text
2a9eaab77b8ab03719f0de2d9433e5fda815007dcc89896cb0ec1d6afafe5f1a
```

포함 이미지:

```text
xcn-similarity/api:1.0.0
```

포함하지 않는 항목:

- app 소스 디렉터리
- tools 디렉터리
- vendor 디렉터리
- infra 이미지
- 모델 파일
- Milvus/MongoDB/MinIO/etcd 데이터
- 운영 로그

이 패키지는 API 전용 패키지다. `indexer` 모드는 포함하지 않는다.

## 2. 사전 조건

먼저 infra 패키지가 설치되어 있어야 한다.

```text
xcn-similarity-infra
```

infra Docker network 기본 이름:

```text
xcn-similarity-infra_default
```

설치 서버에 아래 항목이 준비되어 있어야 한다.

```bash
docker version
docker compose version
```

모델 파일은 호스트의 아래 경로에 준비한다.

```text
/data/models/upskyy_bge_m3_korean
```

필요 포트:

```text
8010   API
18080  API alias
```

## 3. 설치

패키지를 설치 위치로 복사한 뒤 압축을 해제한다.

```bash
cd /users/xcn_docker
tar -xzf xcn-similarity-package-1.0.0-final.tar.gz
cd xcn-similarity
```

무결성을 확인한다.

```bash
sha256sum -c xcn-similarity-package-1.0.0-final.tar.gz.sha256
```

패키지 파일과 `.sha256` 파일이 다른 디렉터리에 있으면 아래처럼 직접 비교한다.

```bash
sha256sum xcn-similarity-package-1.0.0-final.tar.gz
cat xcn-similarity-package-1.0.0-final.tar.gz.sha256
```

이미지를 로드하고 `.env`를 준비한다.

```bash
./install.sh --no-start
```

서비스를 기동한다.

```bash
docker compose up -d
```

## 4. 기본 설정

패키지의 `.env.package`는 아래 기본값을 사용한다.

```env
SIM_IMAGE_REPO=xcn-similarity
SIM_IMAGE_TAG=1.0.0
COMPOSE_PROFILES=
SIM_PACKAGE_MODE=api
SIM_DOCKER_NETWORK=xcn-similarity-infra_default
SIM_MILVUS_URL=http://milvus:19530
SIM_CATALOG_MONGO_URI=mongodb://mongodb:27017/xcn_similarity?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000
SIM_MODELS_VOLUME=/data/models
SIM_MILVUS_MINIO_VOLUME=/data/infra/minio
SIM_EMBEDDING_MODEL_PATH=/models/upskyy_bge_m3_korean
```

infra network 이름이 다르면 `.env`에서 `SIM_DOCKER_NETWORK`를 수정한다.

모델 경로가 다르면 `.env`에서 `SIM_MODELS_VOLUME`을 수정한다.

## 5. 설치 확인

컨테이너 상태:

```bash
docker compose ps
```

정상 예:

```text
xcn-similarity-api   xcn-similarity/api:1.0.0   Up
```

API health:

```bash
curl -sS --max-time 15 http://127.0.0.1:8010/health
```

정상 응답 예:

```json
{
  "status": "ok",
  "version": "1.0.0",
  "vector_backend": "milvus",
  "embedder_backend": "hf_transformer",
  "embedding_model": "upskyy_bge_m3_korean",
  "embedding_dim": 1024,
  "catalog_backend": "mongodb",
  "catalog_database": "xcn_similarity"
}
```

infra 이름 해석 확인:

```bash
docker exec xcn-similarity-api getent hosts milvus mongodb minio etcd
```

모델 마운트 확인:

```bash
docker exec xcn-similarity-api test -d /models/upskyy_bge_m3_korean && echo model-mounted
```

통계 API 확인:

```bash
curl -sS --max-time 20 http://127.0.0.1:8010/similarity/stats
```

검색 smoke test:

```bash
curl -sS --max-time 120 \
  -X POST http://127.0.0.1:8010/similarity/search/logs/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"test similarity smoke","top_k":1,"min_score":0.0,"metadata_filter":{}}'
```

## 6. 주요 운영 설정

등록 문서 기준 로그 검색 기본 범위:

```env
SIM_SEARCH_LOGS_DEFAULT_DAYS=30
SIM_SEARCH_LOGS_MAX_DOCUMENT_CHUNKS=8
SIM_SEARCH_LOGS_PARALLELISM=4
SIM_SEARCH_LOGS_CACHE_ENABLED=true
SIM_SEARCH_LOGS_CACHE_TTL_SEC=300
SIM_SEARCH_LOGS_INCLUDE_DEFAULT_PARTITION=true
```

로그 보관 정책:

```env
SIM_LOG_DELETE_BEFORE_DAYS=365
SIM_LOG_RETENTION_POLICY=*=365
SIM_LOG_RETENTION_DELETE_RESULTS=true
SIM_LOG_RETENTION_DELETE_REVIEWS=false
SIM_LOG_RETENTION_CLEAR_MATCH_CACHE=false
```

API 로그:

```env
SIM_FILE_LOG_ENABLED=true
SIM_LOG_DIR=/logs
SIM_LOG_LEVEL=INFO
SIM_LOG_ROTATE_WHEN=midnight
SIM_LOG_BACKUP_DAYS=30
```

설정 변경 후에는 컨테이너를 재생성한다.

```bash
docker compose up -d --force-recreate api
curl -sS --max-time 15 http://127.0.0.1:8010/health
```

## 7. 중지와 재시작

중지:

```bash
docker compose down
```

재시작:

```bash
docker compose up -d
```

로그 확인:

```bash
docker compose logs -f api
docker logs --tail 100 xcn-similarity-api
```

## 8. 재설치 절차

기존 앱 폴더를 백업하고 새 패키지를 설치한다.

```bash
cd /users/xcn_docker
docker rm -f xcn-similarity-api xcn-similarity-indexer 2>/dev/null || true
mkdir -p backups
mv xcn-similarity backups/xcn-similarity-before-$(date +%Y%m%d-%H%M%S)
tar -xzf xcn-similarity-package-1.0.0-final.tar.gz
cd xcn-similarity
./install.sh --no-start
docker compose up -d
```

확인:

```bash
curl -sS --max-time 15 http://127.0.0.1:8010/health
curl -sS --max-time 20 http://127.0.0.1:8010/similarity/stats
```

## 9. 주의사항

- 이 패키지는 API 전용이다.
- 설치 디렉터리에 `app/`, `tools/`, `vendor/` 소스 폴더가 풀리지 않는다.
- `indexer` 모드는 포함하지 않는다.
- API 실행 코드는 Docker 이미지 내부에 포함되어 있다.
- infra 데이터는 앱 패키지 삭제/재설치로 삭제되지 않는다.
- 모델 파일은 패키지에 포함되지 않으므로 `/data/models` 경로를 별도로 준비해야 한다.

