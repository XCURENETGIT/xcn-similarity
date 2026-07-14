# 제품 모드 및 선택 기능

`xcn-similarity`는 배포 형태에 따라 UI, LLM, Kafka, 운영성 DB 사용 범위를 환경변수로 분리한다. 기본값은 단독 제품 기준이며, 로그/문서 색인과 유사도 결과 저장 기능만 동작한다.

## 제품 모드

|모드|환경변수|기본 목적|기본 선택 기능|
|---|---|---|---|
|단독 제품|`SIM_PRODUCT_MODE=standalone`|Kafka 없이 자체 MongoDB에 분석 결과 저장|UI off, LLM off, Kafka off, 리뷰 off, 최근매칭 캐시 off|
|연동 제품|`SIM_PRODUCT_MODE=integrated`|외부 시스템 연동용 API/Kafka 배포|UI off, LLM off, Kafka는 명시적으로만 on|
|운영/개발|`SIM_PRODUCT_MODE=ops`|대시보드 확인, 수동 검토, 인사이트 확인|UI/리뷰/인사이트/최근매칭 캐시 기본 on, LLM은 명시적으로만 on|

`SIM_PRODUCT_MODE`는 기본값 정책만 정한다. 특정 기능을 강제로 켜거나 끄려면 아래 개별 플래그를 명시한다.

## 기능 플래그

|환경변수|기본값|설명|
|---|---:|---|
|`SIM_ADMIN_UI_ENABLED`|`auto`|`/admin` 대시보드와 정적 파일 제공 여부|
|`SIM_SECURITY_INSIGHT_ENABLED`|`auto`|보안 인사이트 API와 주기 생성 worker 사용 여부|
|`SIM_LLM_ENABLED`|`false`|보안 인사이트 생성 시 LLM 호출 여부|
|`SIM_LLM_URL`|빈 값|LLM endpoint. `SIM_LLM_ENABLED=true`일 때만 사용|
|`SIM_MANUAL_REVIEW_ENABLED`|`auto`|`/similarity/reviews` 수동 검토 API 사용 여부|
|`SIM_RECENT_MATCH_CACHE_ENABLED`|`auto`|`SIM_MATCH_CACHE`에 최근 매칭 API 계산 결과 저장 여부|
|`SIM_KAFKA_ENABLED`|`false`|임계치 이상 유사도 결과 Kafka 전송 여부|

`auto`는 `ops` 모드에서 true, `standalone`/`integrated` 모드에서 false로 해석된다. LLM과 Kafka는 운영 영향이 크므로 `auto`가 아니라 명시적으로 true를 설정해야 켜진다.

## MongoDB 사용 범위

기본 배포에서 필요한 컬렉션은 아래와 같다.

|컬렉션|용도|
|---|---|
|`SIM_DOCUMENT_CATALOG`|등록 문서 메타데이터|
|`SIM_LOG_CATALOG`|색인된 로그/첨부 메타데이터|
|`SIM_SIMILARITY_RESULT`|EMS `msgid` 단위 유사도 분석 결과|
|`SIM_INDEXER_STATE`|EMS indexer 진행 상태|
|`SIM_INDEXER_FAILED`|EMS indexer 실패 항목|

운영 UI 또는 부가 기능을 켠 경우에만 아래 컬렉션을 사용한다.

|컬렉션|사용 조건|
|---|---|
|`SIM_MATCH_REVIEW`|`SIM_MANUAL_REVIEW_ENABLED=true`|
|`SIM_MATCH_CACHE`|`SIM_RECENT_MATCH_CACHE_ENABLED=true`|
|`SIM_SECURITY_INSIGHT`|`SIM_SECURITY_INSIGHT_ENABLED=true`|

## Kafka 사용

단독 제품은 Kafka를 사용하지 않는다.

연동 제품에서 Kafka 전송이 필요하면 `SIM_KAFKA_ENABLED=true`를 설정한다. 내장 Kafka를 함께 띄우는 경우에는 compose profile도 같이 사용한다.

```bash
SIM_PRODUCT_MODE=integrated SIM_KAFKA_ENABLED=true docker compose -f docker-compose.offline.yml --profile kafka up -d
```

외부 Kafka를 사용하는 경우에는 `SIM_KAFKA_BOOTSTRAP_SERVERS`를 외부 broker 주소로 지정하고 `--profile kafka` 없이 API만 기동한다.

## 이미지 기준

|이미지/Compose|용도|문서 추출 런타임|
|---|---|---|
|`Dockerfile.offline`, `docker-compose.offline.yml`|운영/오프라인 배포 기준 이미지|PDF, Office, HWP/HWPX, RTF, 텍스트, 압축파일 처리를 위한 Python 패키지와 `antiword`, `catppt`, `soffice`를 포함|

설치와 운영은 `docker-compose.offline.yml` 단일 구성을 기준으로 한다. 별도 경량 HTTP/CPU 전용 이미지는 운영 기준에서 제외한다.
