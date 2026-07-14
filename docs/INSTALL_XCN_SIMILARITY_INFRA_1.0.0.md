# xcn-similarity-infra 1.0.0 설치 매뉴얼

이 문서는 `xcn-similarity-infra-package-1.0.0-final.tar.gz` 기준의 오프라인 설치 절차다.

## 1. 패키지 정보

패키지 파일:

```text
xcn-similarity-infra-package-1.0.0-final.tar.gz
xcn-similarity-infra-package-1.0.0-final.tar.gz.sha256
xcn-similarity-infra-package-1.0.0-final.images.txt
```

SHA256:

```text
6d8d23eeee0bef16075a1199201047f1dcf715f51023967d12fabe9ea6de9605
```

포함 이미지:

```text
xcn-similarity/mongo:8.3
xcn-similarity/etcd:v3.5.18
xcn-similarity/minio:latest
xcn-similarity/milvus:v2.6.18
```

포함하지 않는 항목:

- MongoDB 데이터
- etcd 데이터
- MinIO 데이터
- Milvus 데이터
- 운영 로그

## 2. 사전 조건

설치 서버에 아래 항목이 준비되어 있어야 한다.

```bash
docker version
docker compose version
```

`install.sh`는 `/data/infra` 아래 데이터 디렉터리를 생성하므로 root 권한으로 실행한다.

필요 포트:

```text
27017  MongoDB
19010  MinIO API
19011  MinIO Console
19530  Milvus
9091   Milvus metrics/health
```

기존 서비스가 같은 포트를 사용 중이면 먼저 중지하거나 compose 포트를 조정해야 한다.

## 3. 설치

패키지를 설치 위치로 복사한 뒤 압축을 해제한다.

```bash
cd /users/xcn_docker
tar -xzf xcn-similarity-infra-package-1.0.0-final.tar.gz
cd xcn-similarity-infra
```

무결성을 확인한다.

```bash
sha256sum -c xcn-similarity-infra-package-1.0.0-final.tar.gz.sha256
```

패키지 파일과 `.sha256` 파일이 다른 디렉터리에 있으면 아래처럼 직접 비교한다.

```bash
sha256sum xcn-similarity-infra-package-1.0.0-final.tar.gz
cat xcn-similarity-infra-package-1.0.0-final.tar.gz.sha256
```

이미지를 로드하고 `.env`를 준비한다.

```bash
./install.sh --no-start
```

서비스를 기동한다.

```bash
docker compose up -d
```

## 4. 기본 데이터 경로

기본 데이터 경로는 `/data/infra`이다.

```text
/data/infra/mongodb
/data/infra/mongodb_config
/data/infra/xcn-similarity-etcd
/data/infra/minio
/data/infra/minio_config
/data/infra/milvus
```

데이터 경로를 바꾸려면 `docker-compose.yml`의 volume 경로를 설치 전에 수정한다.

## 5. 설정 파일

설치 후 `.env`에는 아래 값이 준비된다.

```env
MONGO_IMAGE=xcn-similarity/mongo:8.3
ETCD_IMAGE=xcn-similarity/etcd:v3.5.18
MINIO_IMAGE=xcn-similarity/minio:latest
MILVUS_IMAGE=xcn-similarity/milvus:v2.6.18
MILVUS_MINIO_ACCESS_KEY=minioadmin
MILVUS_MINIO_SECRET_KEY=minioadmin
```

MinIO access key/secret key를 변경할 경우 Milvus 설정과 같이 맞춰야 한다.

## 6. 설치 확인

컨테이너 상태를 확인한다.

```bash
docker compose ps
```

정상 예:

```text
xcn-similarity-mongodb   Up
xcn-similarity-etcd      Up
xcn-similarity-minio     Up
xcn-similarity-milvus    Up
```

etcd health:

```bash
docker exec xcn-similarity-etcd \
  etcdctl --endpoints=http://127.0.0.1:2379 endpoint health
```

Milvus health:

```bash
curl -sS --max-time 10 http://127.0.0.1:9091/healthz
```

정상 응답:

```text
OK
```

MongoDB 확인:

```bash
docker exec xcn-similarity-mongodb \
  mongosh --quiet --eval 'db.adminCommand({ ping: 1 })'
```

MinIO 포트 확인:

```bash
curl -sS --max-time 10 http://127.0.0.1:19010/minio/health/live
```

## 7. 앱 패키지와의 연결

앱 패키지 `xcn-similarity`는 기본적으로 infra Docker network에 붙는다.

기본 네트워크 이름:

```text
xcn-similarity-infra_default
```

infra가 정상 설치되면 앱 컨테이너에서 아래 이름을 사용할 수 있어야 한다.

```text
mongodb
etcd
minio
milvus
```

## 8. 중지와 재시작

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
docker compose logs -f
docker compose logs -f milvus
```

## 9. 재설치 주의사항

`docker compose down`은 컨테이너만 내리고 `/data/infra` 데이터는 삭제하지 않는다.

데이터까지 초기화하려면 아래 경로를 삭제해야 하지만, 운영 데이터가 모두 사라지므로 반드시 백업 후 수행한다.

```bash
rm -rf /data/infra/mongodb
rm -rf /data/infra/mongodb_config
rm -rf /data/infra/xcn-similarity-etcd
rm -rf /data/infra/minio
rm -rf /data/infra/minio_config
rm -rf /data/infra/milvus
```

운영 환경에서는 위 삭제 명령을 바로 실행하지 않는다.

