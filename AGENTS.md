# AGENTS.md

이 파일은 `C:\xcn_prj` 워크스페이스에서 Codex/에이전트가 모든 작업을 수행할 때 따르는 기본 지침이다.

## 기본 원칙

- `C:\xcn_prj`는 여러 독립 프로젝트를 담는 워크스페이스로 본다.
- 작업 전 먼저 대상 프로젝트를 식별하고, 해당 프로젝트의 `README.md`, `docs/`, `docker-compose*.yml`, `.env.example`을 확인한다.
- 사용자가 특정 프로젝트를 지정하지 않으면 파일 경로, 서비스명, 용어를 기준으로 대상 프로젝트를 판단한다.
- 기존 파일의 구조와 스타일을 우선 유지한다.
- 사용자가 명시하지 않은 기존 변경사항은 되돌리지 않는다.

## 접속 정보 및 원천 데이터

- 접속 정보는 별도 문서에 정리된 내용을 기준으로 한다.
- `xcn-similarity`의 EMS 원천 데이터, MongoDB, MinIO 접속 기준은 `xcn-similarity/docs/EMS_DATA_SOURCE.md`를 참조한다.
- 접속 정보, 계정, 비밀번호, 운영 데이터 기준은 코드나 README에 중복 기재하지 말고 기존 문서 참조를 우선한다.
- `.env`, `.secrets/`, 운영 데이터, 로그, 모델 파일, 빌드 산출물은 사용자가 명시하지 않는 한 커밋 대상에서 제외한다.

## 작업 방식

- 모든 변경은 먼저 로컬 워크스페이스에 반영한다.
- 변경 후 가능한 범위에서 로컬 검증을 수행한다.
- 검증은 프로젝트 성격에 맞게 선택한다. 예: 단위 테스트, 린트, 타입 검사, `docker compose config`, 컨테이너 빌드, 스모크 테스트.
- 검증이 불가능하면 불가능한 이유와 미검증 범위를 명확히 남긴다.
- 운영/리모트 반영이 필요한 작업은 로컬 변경과 검증 결과를 확인한 뒤 진행한다.

## 리모트 반영 및 적용

- 사용자가 작업 완료를 요청하면 기본 흐름은 로컬 반영, 리모트 반영, 적용, 확인 순서로 진행한다.
- 별도 지시가 없으면 `xcn-similarity` 변경사항은 52번 서버(`10.100.40.52`, `/data01/xcn-similarity`)에 반영하고 적용한다.
- 리모트 접속 및 배포 방법은 프로젝트 내 문서와 기존 스크립트를 우선 사용한다.
- 임의로 새로운 배포 절차를 만들기보다 기존 `remote_*.sh`, `scripts/`, `docker-compose*.yml` 흐름을 따른다.
- 리모트 적용 후에는 서비스 상태, 컨테이너 상태, 로그, API 헬스체크 등 최소 1개 이상의 확인 절차를 수행한다.
- 위험도가 높은 작업, 데이터 삭제, 스키마 변경, 운영 서비스 중단 가능성이 있는 작업은 실행 전 사용자 확인을 받는다.

## 52번 서버 접속 기준

- 52번 서버는 `10.100.40.52`이다.
- `xcn-similarity` 운영 경로는 `/data01/xcn-similarity`이다.
- Windows/PuTTY 기준 접속은 `aiuser@10.100.40.52`로 한다.
- PuTTY `plink`/`pscp` 사용 시 호스트키 미등록 오류가 날 수 있으므로 아래 호스트키를 명시한다.

```powershell
plink -batch -ssh -hostkey "ssh-ed25519 255 SHA256:LdtE/QqmxdhmcaZ3165VTYX5BAl0lBLYW8uS0WuXGz4" aiuser@10.100.40.52 "hostname"
pscp -batch -hostkey "ssh-ed25519 255 SHA256:LdtE/QqmxdhmcaZ3165VTYX5BAl0lBLYW8uS0WuXGz4" <local-file> aiuser@10.100.40.52:/data01/xcn-similarity/
```

- 비밀번호 방식 접속이 필요한 경우 기존 로컬 설정의 `aiuser` 접속 정보를 따른다.
- `root@10.100.40.52` 직접 SSH 접속은 실패할 수 있다. root 권한이 필요하면 먼저 `aiuser`로 접속한 뒤 서버 안에서 `su -`로 전환한다.
- `aiuser`는 `docker` 그룹에 포함되어 있으므로 일반적인 `docker compose` 빌드/재기동은 `su -` 없이 가능하다.
- 적용 후 기본 확인:

```bash
cd /data01/xcn-similarity
docker compose -f docker-compose.offline.yml --profile http ps
curl -sS --max-time 15 http://127.0.0.1:8010/health
```

## Git 기준

- 각 하위 프로젝트가 독립 Git 저장소일 수 있으므로 작업 전 `git status`로 저장소와 변경 상태를 확인한다.
- 사용자 또는 다른 작업자가 만든 변경사항을 덮어쓰거나 되돌리지 않는다.
- 커밋/푸시는 사용자가 요청했거나 작업 지침상 필요하다고 판단되는 경우에만 수행한다.
- 커밋 메시지는 변경 목적과 적용 범위를 간결하게 작성한다.

## 문서화

- 운영 기준, 접속 기준, 데이터 조회 규칙은 가능한 한 `docs/` 아래에 문서화한다.
- 프로젝트별 특수 규칙이 생기면 워크스페이스 루트가 아니라 해당 프로젝트 하위의 `AGENTS.md` 또는 `docs/`에 분리한다.
- 한국어 문서가 기존 스타일이면 한국어로 유지한다.
