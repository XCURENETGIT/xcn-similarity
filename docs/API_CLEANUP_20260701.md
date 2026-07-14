# xcn-similarity API 정리 기준

## 정리 목적

삭제되었거나 현재 사용하지 않는 입력 파라미터와 실제 동작 중인 API를 구분해, 연동 시 혼동을 줄이기 위한 기준이다.

## 공개 연동 기본 API

|구분|Method|Path|상태|비고|
|---|---|---|---|---|
|헬스체크|GET|`/health`|유지|서비스 상태 확인|
|문서 직접 등록|POST|`/similarity/documents`|유지|`title`, `text`, `security_level`, `metadata`만 입력|
|문서 파일 등록|POST|`/similarity/documents/upload`|유지|다중 파일/압축 내부 문건은 각각 별도 문서로 등록|
|문서 목록/검색|GET|`/similarity/documents/search`|유지|최신 등록 문서 우선|
|문서 수정|PATCH|`/similarity/documents/{document_id}`|유지|제목, 보안등급, 메타데이터 수정|
|문서 삭제|DELETE|`/similarity/documents/{document_id}`|유지|문서와 문서 청크 삭제|
|로그 단건 등록|POST|`/similarity/logs`|유지|외부 직접 연동 가능|
|로그 배치 등록|POST|`/similarity/logs/batch`|유지|EMS indexer 기본 연동|
|로그 목록|GET|`/similarity/logs`|유지|`source_type`, `svc`, `user_id` 필터|
|로그 기준 문서 검색|POST|`/similarity/search/documents`|유지|텍스트 기준 등록문서 검색|
|문서 기준 로그 검색|POST|`/similarity/search/logs`|유지|기본 최근 30일, 전체 검색은 `metadata_filter.ctime` 명시|
|텍스트 기준 로그 검색|POST|`/similarity/search/logs/text`|유지|텍스트 기준 로그 검색|
|통계|GET|`/similarity/stats`|유지|벡터/문서/로그/스토리지 상태|
|설정 조회|GET|`/similarity/settings`|유지|운영 임계값과 검색 기본값 확인|

## 운영/화면용 API

|구분|Method|Path|상태|비고|
|---|---|---|---|---|
|저장된 유사도 결과 목록|GET|`/similarity/results`|운영용|SIM_SIMILARITY_RESULT 조회|
|저장된 최근 매칭|GET|`/similarity/results/recent-matches`|운영용|UI 고위험 목록|
|msgid 결과 조회|GET|`/similarity/results/{msgid}`|운영용|msgid 단위 결과|
|최근 매칭 재계산|GET|`/similarity/matches/recent`|운영용|캐시/재계산 옵션 포함|
|수동 리뷰 목록|GET|`/similarity/reviews`|옵션|`SIM_MANUAL_REVIEW_ENABLED` 필요|
|수동 리뷰 저장|POST|`/similarity/reviews`|옵션|`SIM_MANUAL_REVIEW_ENABLED` 필요|
|보안 인사이트|GET|`/similarity/insights/security`|옵션|`SIM_SECURITY_INSIGHT_ENABLED` 필요|
|보안 인사이트 이력|GET|`/similarity/insights/security/history`|옵션|`SIM_SECURITY_INSIGHT_ENABLED` 필요|
|관리 UI|GET|`/admin`, `/admin/*`|옵션|`SIM_ADMIN_UI_ENABLED` 필요|

## 정리한 입력 파라미터

|대상|파라미터|처리|이유|
|---|---|---|---|
|`POST /similarity/documents`|`owner`|공개 요청 스키마에서 제외|현재 등록 로직에서 사용하지 않음|
|`POST /similarity/documents`|`department`|공개 요청 스키마에서 제외|현재 등록 로직에서 사용하지 않음|
|`PATCH /similarity/documents/{document_id}`|`owner`|공개 요청 스키마에서 제외|현재 수정 로직에서 사용하지 않음|
|`PATCH /similarity/documents/{document_id}`|`department`|공개 요청 스키마에서 제외|현재 수정 로직에서 사용하지 않음|
|`POST /similarity/documents/upload`|`owner`|Form 파라미터에서 제외|현재 등록 로직에서 사용하지 않음|
|`POST /similarity/documents/upload`|`department`|Form 파라미터에서 제외|현재 등록 로직에서 사용하지 않음|

응답 모델 `DocumentInfo.owner`, `DocumentInfo.department`는 과거 데이터 호환을 위해 남겨둔다. 신규 등록에서는 기본적으로 `null`이다.

## 등록문서 기준 로그 검색 기간 기준

`POST /similarity/search/logs`는 `metadata_filter.ctime`이 없으면 기본적으로 최근 `SIM_SEARCH_LOGS_DEFAULT_DAYS`일만 검색한다. 운영 기본값은 30일이다.

전체 기간 검색이 필요하면 API 요청에 아래 값을 넣는다.

```json
{
  "metadata_filter": {
    "ctime": {
      "$gte": "2000-01-01T00:00:00+00:00",
      "$lte": "2099-12-31T23:59:59+00:00"
    }
  }
}
```

서비스 전체 기본을 전체 검색으로 바꾸려면 `.env`에서 `SIM_SEARCH_LOGS_DEFAULT_DAYS=0`으로 설정한다. 단, 운영 성능 기준으로는 화면/버튼에서 필요할 때만 전체 기간을 명시하는 방식을 권장한다.

