# 유사도 분석 Kafka 결과 항목별 주석

이 문서는 샘플 Kafka 결과 payload의 각 항목이 무엇을 의미하는지 설명한다.
샘플 `generated_at` 값 `2026-06-23T07:19:25.433831+00:00`은 UTC 기준이며, KST로는 `2026-06-23 16:19:25`이다.

## 전체 구조

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `type` | `similarity` | Kafka 메시지 유형이다. 유사도 분석 결과 메시지는 `similarity`로 고정한다. |
| `msgid` | `20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A` | EMS 원천 메시지 식별자다. Kafka key 및 결과 조회의 대표 ID로 사용한다. |
| `data` | object | 실제 업무 데이터를 담는 컨테이너다. 현재는 `similarity` 결과만 포함한다. |
| `data.similarity` | object | 유사도 분석 처리 결과 본문이다. 성공 여부, 기준값, 요약, 본문/첨부별 상세 결과를 포함한다. |

## 처리 상태

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `data.similarity.success` | `true` | 유사도 분석 결과 payload 생성이 정상 처리됐는지 나타낸다. |
| `data.similarity.status` | `200` | API 스타일의 처리 상태 코드다. `200`은 정상 생성이다. |
| `data.similarity.message` | `OK` | 처리 결과 메시지다. 정상일 때 `OK`로 표시된다. |
| `data.similarity.version` | `similarity-result-v1` | 결과 payload 스키마/계산 로직 버전이다. 향후 필드나 판정 방식이 바뀌면 버전 구분에 사용한다. |
| `data.similarity.generated_at` | `2026-06-23T07:19:25.433831+00:00` | 결과 생성 시각이다. 저장/전송 기준은 UTC이며 화면에서는 KST로 변환해 보여준다. |

## 판정 기준값

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `data.similarity.thresholds.min_score` | `0.82` | 결과로 채택할 최소 유사도 기준이다. 이 값 미만은 Kafka 결과의 유의미한 탐지로 보지 않는다. |
| `data.similarity.thresholds.grey_zone_low_score` | `0.62` | 회색 구간 하한이다. 낮은 위험/검토 참고 영역을 나눌 때 쓰는 기준값이다. |
| `data.similarity.thresholds.grey_zone_high_score` | `0.82` | 고위험 판정 기준이다. 이 값 이상이면 `high` 위험도로 분류된다. |

## 요약 결과

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `data.similarity.summary.detected` | `true` | 기준 이상의 유사 매칭이 발견됐는지 나타낸다. 이 샘플은 탐지 결과가 있다. |
| `data.similarity.summary.max_score` | `0.997816` | 전체 본문/첨부 결과 중 가장 높은 대표 유사도다. 이 샘플에서는 첨부 매칭 점수가 최고다. |
| `data.similarity.summary.risk_level` | `high` | 전체 결과의 최종 위험도다. `max_score`가 `grey_zone_high_score` 이상이므로 `high`다. |
| `data.similarity.summary.match_count` | `2` | 기준 이상으로 매칭된 결과 수다. 본문 1건, 첨부 1건이 매칭됐다. |

## 결과 배열 공통 필드

`data.similarity.results[]`는 메시지 안에서 분석 대상별 결과를 나눈 배열이다.
이 샘플은 `body` 1개와 `attach` 1개가 있다.

| 경로 | 설명 |
|---|---|
| `target` | 분석 대상 유형이다. `body`는 메일/메시지 본문, `attach`는 첨부 파일을 뜻한다. |
| `attach_index` | 첨부 순번이다. 본문이면 `null`, 첨부면 0부터 시작하는 번호를 가진다. |
| `max_score` | 해당 대상 안에서 가장 높은 매칭 점수다. |
| `risk_level` | 해당 대상 단위의 위험도다. |
| `review_scope` | 검토 큐 분류다. `high_risk`는 고위험 검토 대상으로 올려야 함을 뜻한다. |
| `review_status` | 사람이 검토했는지 여부다. `unreviewed`는 아직 미검토 상태다. |
| `matches` | 실제로 어떤 등록문서와 어떤 청크가 유사했는지 담는 상세 매칭 목록이다. |

## 본문 결과 해석

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `results[0].target` | `body` | EMS 메시지 본문 텍스트를 등록문서와 비교한 결과다. |
| `results[0].attach_index` | `null` | 본문 대상이라 첨부 순번이 없다. |
| `results[0].max_score` | `0.9428` | 본문 기준 최고 유사도다. 94.28%로 고위험 기준 82%를 넘는다. |
| `results[0].risk_level` | `high` | 본문만 놓고 봐도 고위험이다. |
| `results[0].review_scope` | `high_risk` | 운영자가 우선 검토해야 하는 범위다. |
| `results[0].review_status` | `unreviewed` | 아직 검토/승인/오탐 처리되지 않았다. |

## 첨부 결과 해석

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `results[1].target` | `attach` | 첨부 파일 텍스트를 등록문서와 비교한 결과다. |
| `results[1].attach_index` | `0` | 첫 번째 첨부 파일이다. |
| `results[1].max_score` | `0.997816` | 첨부 기준 최고 유사도다. 99.78%로 사실상 거의 동일한 내용에 가깝다. |
| `results[1].risk_level` | `high` | 첨부 파일도 고위험이다. |
| `results[1].review_scope` | `high_risk` | 운영자 검토 대상이다. |
| `results[1].review_status` | `unreviewed` | 아직 사람이 검토하지 않았다. |

## 매칭 상세 공통 필드

`matches[]`는 특정 분석 대상이 등록문서의 어떤 청크와 유사했는지를 설명한다.

| 경로 | 설명 |
|---|---|
| `document_id` | 유사하다고 판정된 등록문서 ID다. |
| `document_title` | 등록문서 제목이다. UI에서 사람이 식별하기 쉽게 표시한다. |
| `document_chunk_id` | 등록문서 안에서 매칭된 청크 ID다. 긴 문서는 여러 청크로 나뉘며, 여기서는 첫 번째 청크가 매칭됐다. |
| `document_security_level` | 등록문서 보안등급이다. 이 샘플은 `대외비` 문서와 유사하다. |
| `log_chunk_id` | EMS 본문/첨부 쪽에서 매칭된 청크 ID다. |
| `_match_document_text_preview` | 등록문서 매칭 청크의 미리보기 텍스트다. 근거 확인용이며 Kafka 수신 시스템에서 필수 업무키로 쓰기보다는 설명/검토 용도다. |
| `_match_log_text_preview` | EMS 로그 또는 첨부에서 추출한 매칭 청크 미리보기 텍스트다. |
| `score` | 최종 운영 판정에 사용하는 대표 유사도다. 벡터 유사도와 핵심어/구문 보강 점수를 가중합한 값이다. |
| `score_percent` | `score`를 사람이 보기 쉬운 퍼센트로 변환한 값이다. |
| `raw_score` | 임베딩 벡터 검색에서 나온 원천 유사도다. 의미적으로 얼마나 가까운지를 나타낸다. |
| `weighted_coverage_score` | 핵심어가 얼마나 잘 겹치는지 계산한 가중 커버리지 점수다. |
| `phrase_match_score` | 문장 흐름/구문이 얼마나 유사한지 보강하는 점수다. |
| `matched_terms` | 기존 호환 필드다. 의미는 `matched_keywords`와 동일하다. |
| `matched_keywords` | 등록문서 매칭 청크와 EMS 본문/첨부 매칭 청크 양쪽에 공통으로 나타난 대표 핵심어다. 유사도 판정 사유 설명용이며 전체 공통 단어 목록은 아니다. |
| `matched_terms_description` | `matched_terms`/`matched_keywords`의 의미를 설명하는 문구다. |
| `score_breakdown` | 대표 점수 계산에 들어간 하위 점수 목록이다. |
| `score_weight_policy` | 대표 점수 계산 공식과 가중치 설명이다. |
| `reason` | 사람이 빠르게 이해할 수 있는 판정 사유 문구다. |

## 본문 매칭 상세

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `results[0].matches[0].document_id` | `doc_0d4fbf864b69000152e2b8bf` | 본문과 유사한 등록문서 ID다. |
| `results[0].matches[0].document_title` | `UEBA_이상행위_탐지_시스템_20260601` | 본문이 이 등록문서와 유사하다고 판단됐다. |
| `results[0].matches[0].document_security_level` | `대외비` | 유사 대상 문서가 대외비 등급이므로 유출/반출 의심 시 중요도가 높다. |
| `results[0].matches[0].score` | `0.9428` | 본문 최종 유사도다. |
| `results[0].matches[0].score_percent` | `94.28` | 본문 최종 유사도의 퍼센트 표시다. |
| `results[0].matches[0].raw_score` | `0.932706` | 본문과 등록문서 청크의 벡터 유사도다. |
| `results[0].matches[0].weighted_coverage_score` | `1` | 핵심어 커버리지가 매우 높다. |
| `results[0].matches[0].phrase_match_score` | `1` | 구문 일치 보강도 최고 수준이다. |
| `results[0].matches[0].matched_keywords` | `UEBA`, `시계열`, `이상행위`, `시스템`, `AutoEncoder`, `비지도`, `Improved`, `Transformer` | 본문과 등록문서 사이에 공통으로 잡힌 대표 핵심어다. |
| `results[0].matches[0].reason` | `등록문서와 94.28% 유사` | UI/운영자가 보는 간단한 설명이다. |

## 첨부 매칭 상세

| 경로 | 샘플 값 | 설명 |
|---|---:|---|
| `results[1].matches[0].document_id` | `doc_0d4fbf864b69000152e2b8bf` | 첨부와 유사한 등록문서 ID다. 본문과 같은 문서에 매칭됐다. |
| `results[1].matches[0].document_title` | `UEBA_이상행위_탐지_시스템_20260601` | 첨부 내용이 이 등록문서와 거의 동일하게 잡혔다. |
| `results[1].matches[0].document_security_level` | `대외비` | 첨부에 대외비 문서와 유사한 내용이 포함되어 있다. |
| `results[1].matches[0].score` | `0.997816` | 첨부 최종 유사도다. 1.0에 매우 가까워 동일/복제 가능성이 높다. |
| `results[1].matches[0].score_percent` | `99.78` | 첨부 최종 유사도의 퍼센트 표시다. |
| `results[1].matches[0].raw_score` | `0.999173` | 첨부와 등록문서 청크의 벡터 유사도다. 거의 동일한 의미 공간으로 판단됐다. |
| `results[1].matches[0].weighted_coverage_score` | `0.985185` | 핵심어 대부분이 겹친다. |
| `results[1].matches[0].phrase_match_score` | `1` | 문장/구문 흐름도 사실상 일치한다. |
| `results[1].matches[0].matched_keywords` | `UEBA`, `시계열`, `이상행위`, `시스템`, `AutoEncoder`, `비지도`, `Improved`, `Transformer` | 첨부와 등록문서 사이에 공통으로 확인된 대표 핵심어다. |
| `results[1].matches[0].reason` | `등록문서와 99.78% 유사` | 첨부가 등록문서와 매우 높은 유사도를 보인다는 요약 설명이다. |

## 점수 산식 주석

샘플의 `score_weight_policy`는 아래 의미를 가진다.

| 항목 | 샘플 값 | 설명 |
|---|---:|---|
| `decision_score_field` | `score` | 최종 운영 판정에 사용할 필드명이다. |
| `decision_score_formula` | `score = raw_score * vector_similarity_weight + weighted_coverage_score * keyword_match_weight + phrase_match_score * phrase_match_weight` | 대표 점수 계산 공식이다. |
| `vector_similarity_weight` | `0.85` | 벡터 유사도 비중이다. 의미적 유사도가 전체 점수의 85%를 차지한다. |
| `keyword_match_weight` | `0.1` | 핵심어 일치 점수 비중이다. |
| `weighted_term_coverage_weight` | `0.1` | 핵심어 커버리지 계산 내부에서 쓰는 가중치 설명 필드다. 현재 운영 공식의 핵심어 축과 연결된다. |
| `phrase_match_weight` | `0.05` | 문장 흐름/구문 일치 보강 비중이다. |
| `description` | 운영 판정 설명 | 운영 판정은 AI 유사도, 핵심어 일치, 문장흐름을 사용한다는 정책 설명이다. |

## 이번 샘플 결론

- EMS 메시지 `20260623155812.7PMRFYFQTVG2SZEHL3QDOPWBI35AJE2A`에서 등록문서 `UEBA_이상행위_탐지_시스템_20260601`과 유사한 내용이 탐지됐다.
- 본문 유사도는 `94.28%`, 첨부 유사도는 `99.78%`다.
- 전체 최고 점수는 첨부에서 나온 `0.997816`이며, 최종 위험도는 `high`다.
- 등록문서 보안등급이 `대외비`이고 첨부 유사도가 매우 높으므로 운영상 우선 검토 대상이다.
- 현재 검토 상태는 `unreviewed`이므로 사람이 확인 후 정상/오탐/위반 여부를 분류해야 한다.
