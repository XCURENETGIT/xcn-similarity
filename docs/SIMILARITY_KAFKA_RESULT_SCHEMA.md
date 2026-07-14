# 유사도 분석 결과 Kafka 전달 데이터 정의

이 문서는 `xcn-similarity`에서 생성한 유사도 분석 결과를 로깅 서버로 전달하기 위한 데이터 계약 초안이다. Kafka producer, topic, 인증, 재시도 처리는 추가 개발 대상이다. 현재 백엔드는 로그 배치 색인 후 이 문서의 payload 구조를 MongoDB `SIM_SIMILARITY_RESULT` 컬렉션에 `msgid` 단위로 저장한다.

## 기준 방향

로깅 서버가 이미 보유한 EMS/MongoDB 원천 메타데이터는 payload에 반복하지 않는다.

전달 대상은 유사도 분석 제품이 생성한 값으로 제한한다.

- 유사도 분석 처리 상태
- 적용 임계값
- 탐지 여부와 대표 점수
- 본문/첨부별 매칭 결과
- 등록문서 매칭 대상
- 점수, 위험도, 판정 사유
- 수동 검토 상태가 있으면 해당 결과

`msgid`는 Kafka key 또는 최상위 라우팅 식별자로만 사용한다. `data.similarity` 내부에는 EMS 원천 메타데이터(`svc`, `user_id`, `ctime`, `src_ip`, `dst_ip`, 첨부 파일명 등)를 넣지 않는다.

## 최상위 구조

기존 미들웨어 탐지 결과 형식과 결합하기 쉽도록 최상위는 `type`, `msgid`, `data` 3개 필드로 구성한다.

```json
{
  "type": "similarity",
  "msgid": "20260507143827.Z4MA6HMMJDSRHDU5NQX67Q4BMIZUEKGF",
  "data": {
    "similarity": {
      "success": true,
      "status": 200,
      "message": "OK",
      "version": "similarity-result-v1",
      "generated_at": "2026-06-19T15:30:00+09:00",
      "thresholds": {
        "min_score": 0.82,
        "grey_zone_low_score": 0.62,
        "grey_zone_high_score": 0.82
      },
      "summary": {
        "detected": true,
        "max_score": 0.9342,
        "max_document_id": "doc_0d4fbf864b69000152e2b8bf",
        "max_document_title": "UEBA_이상행위_탐지_시스템_20260601",
        "risk_level": "high",
        "match_count": 2
      },
      "results": [
        {
          "target": "body",
          "max_score": 0.8841,
          "risk_level": "high",
          "review_scope": "high_risk",
          "review_status": "unreviewed",
          "matches": []
        }
      ]
    }
  }
}
```

## 전달 단위

Kafka 메시지는 EMS `msgid` 1건을 기본 단위로 한다.

|구분|정의|
|---|---|
|메시지 단위|`msgid` 1건당 Kafka 메시지 1건|
|본문 결과|`results[].target = body`|
|첨부 결과|`results[].target = attach`, `attach_index`로 첨부 순번만 표시|
|원천 메타데이터|로깅 서버가 알고 있으므로 전달하지 않음|
|결과 없음|`summary.detected=false`, `summary.match_count=0`, `results=[]`|
|중복 제거|동일 본문/첨부와 동일 등록문서 조합은 최고 점수 1건만 전달|

## 필드 정의

### 최상위 및 공통

|필드명|경로|타입|필수|설명|예시값|
|---|---|---|---|---|---|
|`type`|`$.type`|string|Y|처리 유형. 유사도 분석 결과는 `similarity` 사용|`similarity`|
|`msgid`|`$.msgid`|string|Y|EMS 메시지 고유 식별자. Kafka key로도 사용 가능|`20260507143827.Z4MA6HMM...`|
|`data`|`$.data`|object|Y|탐지 결과 묶음|`{ "similarity": {...} }`|
|`similarity`|`$.data.similarity`|object|Y|유사도 분석 결과|`{ success, status, ... }`|
|`success`|`$.data.similarity.success`|boolean|Y|유사도 분석 처리 성공 여부|`true`|
|`status`|`$.data.similarity.status`|number|Y|처리 상태 코드|`200`|
|`message`|`$.data.similarity.message`|string|Y|처리 결과 메시지|`OK`|
|`version`|`$.data.similarity.version`|string|Y|payload schema version|`similarity-result-v1`|
|`generated_at`|`$.data.similarity.generated_at`|string|Y|유사도 결과 생성 시각. ISO-8601|`2026-06-19T15:30:00+09:00`|

### 임계값 및 요약

|필드명|경로|타입|필수|설명|예시값|
|---|---|---|---|---|---|
|`thresholds`|`...similarity.thresholds`|object|Y|유사도 판정에 적용한 임계값|`{...}`|
|`min_score`|`...thresholds.min_score`|number|Y|탐지 결과로 전달한 최소 유사도|`0.82`|
|`grey_zone_low_score`|`...thresholds.grey_zone_low_score`|number|Y|Grey Zone 하한|`0.62`|
|`grey_zone_high_score`|`...thresholds.grey_zone_high_score`|number|Y|고위험 구간 하한|`0.82`|
|`summary`|`...similarity.summary`|object|Y|메시지 단위 유사도 요약|`{...}`|
|`detected`|`...summary.detected`|boolean|Y|임계값 이상 매칭 존재 여부|`true`|
|`max_score`|`...summary.max_score`|number|Y|전체 최고 유사도|`0.9342`|
|`max_document_id`|`...summary.max_document_id`|string/null|N|전체 결과 중 최고 유사도 match의 등록문서 ID. 결과가 없으면 `null`|`doc_0d4fbf864b69000152e2b8bf`|
|`max_document_title`|`...summary.max_document_title`|string/null|N|전체 결과 중 최고 유사도 match의 등록문서 제목. 결과가 없으면 `null`|`UEBA_이상행위_탐지_시스템_20260601`|
|`risk_level`|`...summary.risk_level`|string|Y|대표 위험도. `none`, `low`, `grey`, `high` 중 하나|`high`|
|`match_count`|`...summary.match_count`|number|Y|전달된 매칭 결과 수|`2`|

### 결과 목록

`results[]`는 본문 또는 첨부 단위 결과다. 로깅 서버가 원천 데이터를 알고 있으므로 결과 대상은 `target`과 `attach_index` 정도만 전달한다.

|필드명|경로|타입|필수|설명|예시값|
|---|---|---|---|---|---|
|`results`|`...similarity.results`|array|Y|본문/첨부별 유사도 결과 배열|`[ {...} ]`|
|`target`|`...results[].target`|string|Y|결과 대상. `body` 또는 `attach`|`attach`|
|`attach_index`|`...results[].attach_index`|number/null|N|첨부 순번. 본문은 `null`|`0`|
|`max_score`|`...results[].max_score`|number|Y|해당 대상의 최고 유사도|`0.9342`|
|`risk_level`|`...results[].risk_level`|string|Y|`low`, `grey`, `high` 중 하나|`high`|
|`review_scope`|`...results[].review_scope`|string|Y|`low_risk`, `grey_zone`, `high_risk` 중 하나|`high_risk`|
|`review_status`|`...results[].review_status`|string|Y|수동 검토 상태. 미검토는 `unreviewed`|`unreviewed`|
|`matches`|`...results[].matches`|array|Y|등록문서 매칭 상세 배열|`[ {...} ]`|

### 매칭 상세

|필드명|경로|타입|필수|설명|예시값|
|---|---|---|---|---|---|
|`document_id`|`...matches[].document_id`|string|Y|유사도 분석 제품에 등록된 문서 ID|`doc_8f2a31c901ab`|
|`document_title`|`...matches[].document_title`|string|Y|등록문서 제목|`영업전략_기밀.pdf`|
|`document_chunk_id`|`...matches[].document_chunk_id`|string|N|매칭된 등록문서 청크 ID|`000003`|
|`document_security_level`|`...matches[].document_security_level`|string/null|N|등록문서 보안 등급|`CONFIDENTIAL`|
|`log_chunk_id`|`...matches[].log_chunk_id`|string|N|매칭된 로그 청크 ID. 로깅 서버 표시가 필요 없으면 생략 가능|`000001`|
|`score`|`...matches[].score`|number|Y|대표 유사도 점수|`0.9342`|
|`score_percent`|`...matches[].score_percent`|number|Y|백분율 점수|`93.42`|
|`raw_score`|`...matches[].raw_score`|number|N|AI 유사도 원점수. Milvus 청크 검색 최고 점수|`0.9342`|
|`weighted_coverage_score`|`...matches[].weighted_coverage_score`|number|N|핵심어 일치 점수. 숫자/코드/긴 키워드에 가중치를 둔 공통어구 비율|`0.81`|
|`phrase_match_score`|`...matches[].phrase_match_score`|number|N|문장흐름 점수. 2~4개 핵심어 연속 구문 일치 정도|`0.35`|
|`reason`|`...matches[].reason`|string|Y|통합 모니터링 표시용 판정 사유|`등록문서와 93.42% 유사`|
|`matched_terms`|`...matches[].matched_terms`|array|N|등록문서 청크와 로그 청크 사이의 공통 핵심어. 없으면 빈 배열 또는 생략|`["계약", "단가"]`|
|`score_breakdown`|`...matches[].score_breakdown`|array|N|결과 샘플 표시용 점수 분해 항목. `[라벨, 값]` 배열 목록|`[["최고 청크 벡터 유사도", 0.9342]]`|
|`score_weight_policy`|`...matches[].score_weight_policy`|object|N|대표 점수에 반영되는 항목별 비중과 참고 산식 설명|`{ "vector_similarity_weight": 1.0 }`|
|`review`|`...matches[].review`|object/null|N|수동 검토 결과가 있으면 포함|`{ "decision": "true_positive" }`|

### 점수 반영 정책

현재 운영 판정과 Kafka 대표 점수는 AI 유사도, 핵심어 일치, 문장흐름 3개 항목만 사용한다. 원문이 있어 근거 항목을 계산할 수 있으면 AI 유사도 85%, 핵심어 일치 10%, 문장흐름 5%를 반영한다. 원문이 없어 근거 항목을 계산할 수 없으면 AI 유사도 100%로 판정한다.

|항목|현재 대표 점수 반영 비중|설명|
|---|---:|---|
|AI 유사도 `raw_score`|85%|Milvus 청크 검색 최고 점수. 원문 미보관 시 100%|
|핵심어 일치 `weighted_coverage_score`|10%|숫자, 코드, 식별자, 긴 키워드 일치 정도|
|문장흐름 `phrase_match_score`|5%|핵심어가 같은 순서로 이어지는 정도|

대표 점수 산식은 아래와 같다.

```text
score = raw_score * 0.85 + weighted_coverage_score * 0.10 + phrase_match_score * 0.05
```

## 제외 필드

아래 값은 로깅 서버가 이미 보유하거나 MongoDB 원천에서 취득 가능한 값이므로 Kafka 결과 payload에서 제외한다.

|제외 필드|제외 사유|
|---|---|
|`svc`, `user_id`, `user_email`|로깅 서버 원천 메타데이터|
|`ctime`, `src_ip`, `dst_ip`, `direction`|로깅 서버 원천 메타데이터|
|첨부 파일명, 확장자, 크기, 해시|로깅 서버가 `msgid + attach_index` 기준으로 보유|
|`log_id`, `match_key`|유사도 제품 내부 식별자. 외부 표시/조인에 불필요하면 제외|
|원문 미리보기|중복 데이터 및 민감정보 전달 최소화 목적|

## xcn-similarity 내부 필드 매핑

|Kafka 필드|현재 내부 출처|
|---|---|
|`msgid`|`SIM_LOG_CATALOG.metadata.msg_id` 또는 `log_id`에서 `:body`, `:attach:<n>` 제거|
|`results[].target`|`log_id` suffix 기준. `:body`는 `body`, `:attach:<n>`은 `attach`|
|`results[].attach_index`|`SIM_LOG_CATALOG.metadata.attachment_index` 또는 `log_id` suffix|
|`matches[].document_id`|`SimilarityHit.target_id` 또는 `SimilarityHit.metadata.document_id`|
|`matches[].document_chunk_id`|`SimilarityHit.chunk_id`|
|`matches[].log_chunk_id`|`SimilarityHit.metadata._match_log_chunk_id`|
|`matches[].score`|`SimilarityHit.score`|
|`matches[].document_title`|`SimilarityHit.metadata.title` 또는 문서 카탈로그 title|
|`review_status`, `review`|`SIM_MATCH_REVIEW` 조회 결과. 없으면 `unreviewed`|
|`thresholds.*`|`/similarity/settings` 또는 환경변수 `SIM_RECENT_MATCH_*`, `SIM_GREY_ZONE_*`|

## Kafka 연동 개발 시 고려사항

1. Kafka message key는 `msgid`를 우선 사용한다.
2. Payload 내부에는 로깅 서버 원천 메타데이터를 반복하지 않는다.
3. Producer는 `SIM_SIMILARITY_RESULT`의 `data.similarity` 결과를 `msgid` 단위로 전송한다.
4. 동일 `msgid` 재전송을 고려해 `msgid + version + generated_at` 또는 결과 hash를 idempotency 기준으로 둔다.
5. 탐지 결과가 없는 메시지도 상태 동기화가 필요하면 `detected=false`, `results=[]` 이벤트를 전송한다.
