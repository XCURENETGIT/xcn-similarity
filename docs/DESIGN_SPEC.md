# XCN Similarity 설계서

## 설계 목표

XCN Similarity는 사내 문서와 복호화 로깅 데이터를 벡터 검색으로 비교하여 내부정보 유출 가능성을 분석하는 서비스다. 1차 목표는 고객사 기준 10만 로그/day, 1년 보관, 최대 1억 벡터 규모를 감당할 수 있는 구조를 제공하는 것이다.

## 아키텍처

```text
MongoDB
- 기존 로그 메타데이터
- 등록 문서 메타데이터
- 벡터 처리 상태
- 검색/감사 이력

MinIO
- 기존 첨부 원본
- 등록 문서 원본
- 추출 텍스트 및 청킹 결과

Embedding Worker
- 문서/로그/첨부 텍스트 청킹
- 로컬 임베딩 모델 호출
- 벡터 DB 저장

Vector DB
- Milvus 기본 권장
- 개발/검증용 memory backend 제공

API/UI
- 문서 등록/삭제/조회
- 로그 기준 유사 문서 검색
- 문서 기준 유사 로그 검색
- 결과 근거/하이라이트 제공
```

## 벡터 DB 선택

상용 대용량 기준 기본 후보는 Milvus다.

선정 이유:

```text
1. 1억 벡터급 저장/검색 확장에 적합
2. 문서/로그/첨부 collection 분리 운영 가능
3. MongoDB + MinIO 기존 구조와 느슨하게 결합 가능
4. GPU 없이 CPU 검색 노드로 운영 가능
```

## Collection 설계

```text
document_chunks
- id
- document_id
- chunk_id
- vector
- text
- metadata: title, owner, department, security_level, page, section, version

log_body_chunks
- id
- log_id
- chunk_id
- vector
- text
- metadata: svc, user_id, src_ip, dst_ip, host, ctime, direction, channel

log_attach_chunks
- id
- log_id
- attach_id
- chunk_id
- vector
- text
- metadata: file_name, ext, size, text_path, ctime, user_id, svc
```

## 임베딩 모델

1차 권장:

```text
BGE-M3 계열 또는 한국어 튜닝 BGE-M3 계열
```

운영 조건:

```text
외부망 차단 환경이므로 모델은 사전 다운로드 후 로컬 경로에 마운트한다.
모델 교체 시 전체 재임베딩 배치 기능이 필요하다.
```

## 청킹 정책

기본값:

```text
chunk_size: 1000 tokens 또는 문자 기반 1800자
chunk_overlap: 150 tokens 또는 문자 기반 250자
최소 청크 길이: 50자
문서당 최대 청크 수: 5000
로그 1건당 최대 청크 수: 100
```

주의사항:

```text
너무 작은 청크는 문맥 유실과 오탐을 늘린다.
너무 큰 청크는 검색 정확도와 임베딩 처리량을 떨어뜨린다.
검색은 청크 단위로 수행하고 UI는 문서/로그 단위로 집계한다.
```

## 용량 제한

초기 권장값:

```text
등록 문서 1개 최대: 100MB
첨부 처리 최대: 100MB
추출 텍스트 최대: 20MB
문서당 최대 청크 수: 5000
로그당 최대 청크 수: 100
```

초과 시:

```text
처리 보류
관리자 승인
샘플링 처리
```

## 처리 방식

실시간 동기 임베딩은 피하고 준실시간 비동기 처리를 기본으로 한다.

```text
로그 저장 -> 작업 큐 적재 -> 임베딩 worker -> Vector DB 저장
```

API에서 지원할 상태:

```text
PENDING
PROCESSING
INDEXED
FAILED
DELETED
SKIPPED
```

## 검색 기능

로그 기준 검색:

```text
입력: log_id 또는 임의 텍스트
대상: document_chunks
출력: 유사 문서, 유사 청크, 점수, 근거 텍스트
```

문서 기준 검색:

```text
입력: document_id
대상: log_body_chunks, log_attach_chunks
출력: 유사 로그, 사용자, 목적지, 시간, 첨부 정보, 점수
```

## 보안/감사

필수 감사 이벤트:

```text
문서 등록
문서 삭제
문서 조회
유사도 검색
검색 결과 상세 조회
재처리 요청
```

원문/첨부 접근은 역할 기반 권한으로 제한한다.

## 1차 구현 범위

현재 프로젝트의 1차 구현은 다음을 제공한다.

```text
1. xcn-pii 스타일 FastAPI 프로젝트 구조
2. 문서 등록/삭제/조회 API
3. 텍스트 기반 로그 인덱싱 API
4. 로그 텍스트 -> 유사 문서 검색 API
5. 문서 -> 유사 로그 검색 API
6. memory vector backend
7. Milvus adapter 인터페이스
8. 로컬 임베딩 모델 또는 deterministic hash embedder
```
