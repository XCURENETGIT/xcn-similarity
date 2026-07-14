# EMS 원천 데이터 조회 기준

이 문서는 `xcn-similarity`에서 EMS 로그 본문과 첨부파일을 임베딩할 때 사용하는 원천 데이터 조회 규칙이다. MongoDB/MinIO 접속 정보와 월별 컬렉션 규칙은 여기 내용을 기준으로 한다.

## MongoDB

접속 URI:

```text
mongodb://10.10.20.6:27018/venus?replicaSet=shard1rs&readPreference=primary&serverSelectionTimeoutMS=5000&connectTimeoutMS=10000&directConnection=true
```

DB:

```text
venus
```

월별 메시지 컬렉션:

```text
EMS_MESSAGE_yyyymm
```

예:

```text
EMS_MESSAGE_202605
```

월별 본문 컬렉션:

```text
EMS_BODY_yyyymm.files
EMS_BODY_yyyymm.chunks
```

예:

```text
EMS_BODY_202605.files
EMS_BODY_202605.chunks
```

## 본문 조회 규칙

본문은 `EMS_MESSAGE_yyyymm`의 메시지 문서에서 `fileName` 값을 확인한 뒤 `EMS_BODY_yyyymm`에서 조회한다.

기준 흐름:

1. `EMS_MESSAGE_yyyymm`에서 대상 메시지를 조회한다.
2. 메시지의 `fileName` 값을 확인한다.
3. 같은 월의 `EMS_BODY_yyyymm.files`에서 해당 `fileName`에 대응하는 본문 파일 메타를 찾는다.
4. `EMS_BODY_yyyymm.chunks`에서 본문 chunk를 읽어 텍스트를 복원한다.
5. 복원한 본문 텍스트를 청킹 후 임베딩하여 로그 벡터 컬렉션에 저장한다.

주의:

- 컬렉션 월(`yyyymm`)은 메시지 월과 본문 월이 동일하다는 전제로 조회한다.
- `fineName`이 아니라 `fileName` 필드를 기준으로 한다.
- 기존 백필 스크립트에서는 메시지 `_id + ".body"` 형태로 본문 파일명을 보조 조회할 수 있다. 운영 기준은 실제 메시지 문서의 `fileName`을 우선한다.

## 첨부 조회 규칙

첨부는 `EMS_MESSAGE_yyyymm` 문서의 `attach` 배열을 기준으로 조회한다.

기준 흐름:

1. `EMS_MESSAGE_yyyymm`의 `attach` 필드를 확인한다.
2. `attach`는 배열이며, 한 메시지에 첨부가 여러 개 있을 수 있다.
3. 각 `attach[n]`에서 MinIO object 경로를 확인한다.
4. MinIO의 `emass` bucket 아래 `msg` 경로에서 첨부 또는 첨부 추출 텍스트를 조회한다.
5. 첨부별 텍스트를 청킹 후 임베딩하여 로그 벡터 컬렉션에 저장한다.

첨부 경로 필드 우선순위:

```text
attach[n].textPath
attach[n].path
```

`textPath`가 있으면 추출 텍스트로 보고 우선 사용한다. `textPath`가 없으면 `path`를 사용한다.

## MinIO

Endpoint:

```text
http://10.10.20.6:19000/
```

Access key:

```text
minioadmin
```

Secret key:

```text
minioadmin
```

Bucket:

```text
emass
```

Prefix:

```text
msg
```

첨부 object는 MongoDB `attach[n]`에 기록된 경로를 기준으로 찾는다. 경로가 `/`로 시작하면 object key로 사용할 때 선행 `/`를 제거한다.

## 임베딩 대상 구분

본문:

```text
source=ems
source_type=body
msg_id=<EMS_MESSAGE._id>
log_id=<EMS_MESSAGE._id>:body
```

첨부:

```text
source=ems
source_type=attachment
msg_id=<EMS_MESSAGE._id>
log_id=<EMS_MESSAGE._id>:attach:<index>
attachment_index=<attach 배열 index>
```

본문과 첨부는 같은 메시지에 속하더라도 별도 `log_id`로 관리한다. 검색 결과에서는 `msg_id`로 원 메시지 단위 추적이 가능해야 한다.

## 필터 기준

기본 백필 대상은 `EMS_MESSAGE_yyyymm`에서 조회한다.

현재 내부 데이터 산정 시 적용한 기준:

```text
svc prefix가 X 또는 U인 데이터 제외
```

운영 백필에서도 동일 기준을 기본값으로 사용하되, 고객사 정책에 따라 제외 대상 서비스 코드는 설정값으로 분리한다.

## 월별 백필 예

2026년 5월 데이터:

```text
message collection: EMS_MESSAGE_202605
body files: EMS_BODY_202605.files
body chunks: EMS_BODY_202605.chunks
minio bucket/prefix: emass/msg
```

신규 운영 흐름에서는 `xcn-similarity`가 원천 MongoDB/MinIO를 직접 증분 스캔하지 않는다. middleware가 `POST /similarity/middleware/analyze`로 `svc`, `_id`를 전달하면, API가 이 문서의 원천 MongoDB/MinIO 조회 규칙으로 해당 단건의 본문/첨부 텍스트를 직접 읽어 처리한다. 이때 기존 `tools/index_ems.py`의 월별 직접 스캔, 재처리, 누락 reconcile, 원천 인덱스 생성은 `EMS_INDEX_DIRECT_ENABLED=false` 기준으로 수행하지 않는다.

레거시 백필/스케줄 작업을 명시적으로 다시 사용할 때만 MongoDB 메시지를 기준으로 본문과 첨부를 각각 읽는다. 운영 스케줄러는 지연 로깅 누락을 줄이기 위해 기본적으로 `ltime`을 증분 커서로 사용하고, 동일한 `ltime` 안에서는 `_id`를 보조 정렬 기준으로 저장한다.

자동 월 선택(`EMS_INDEX_MONTHS=auto`, `auto_recent`)은 `EMS_INDEX_TIMEZONE` 기준으로 계산한다. 운영 기본값은 `Asia/Seoul`이며, 월초 00:00 KST 직후 새 `EMS_MESSAGE_yyyymm` / `EMS_BODY_yyyymm` 컬렉션을 즉시 대상으로 포함하기 위한 설정이다.

## 원천 MongoDB 인덱스

운영 스케줄러가 `ltime` 커서를 사용하려면 대상 월별 메시지 컬렉션에 아래 인덱스가 필요하다.

```javascript
db.EMS_MESSAGE_yyyymm.createIndex({ ltime: 1, _id: 1 }, { name: "ltime_1__id_1", background: true })
```

`tools/index_ems.py`는 기본적으로 `EMS_INDEX_ENSURE_SOURCE_INDEXES=true` 설정에 따라 대상 월 컬렉션의 인덱스를 기동 시 보장한다. 대용량 과거월 컬렉션에서는 최초 인덱스 생성 시간이 길 수 있으므로, 운영 설치 시 사전에 생성해두는 것을 권장한다.
