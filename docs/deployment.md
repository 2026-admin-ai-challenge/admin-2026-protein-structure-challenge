# Deployment and operations

## Local

Docker Desktop 준비 후 데이터 저장소 `admin-2026-protein-data`에서 생성과 검증을 먼저 마칩니다. 두 저장소를 같은 상위 디렉터리에 두거나 `.env`의 `DATA_HOST_DIR`을 생성된 데이터 디렉터리로 지정하세요. 이후 `cp .env.example .env`, `docker compose up --build -d`를 실행합니다. 웹: http://localhost:3000. API·Postgres는 Docker 내부 네트워크 전용입니다. 웹사이트 시작 시 원본을 다운로드하거나 데이터셋을 생성하지 않습니다. `docker compose logs -f api`와 `/api/health`의 `dataset_ready`를 확인하세요.

`docker compose exec api python -m app.create_admin`으로 운영자 계정을 생성합니다. 기본 계정/비밀번호는 없습니다. 화면에서 관리자 로그인 → 설정 → Open competition.

데이터는 별도 저장소의 host 디렉터리에서 API에 읽기 전용 bind mount하고, DB는 postgres_data volume에 보관합니다. `docker compose down`은 DB를 삭제하지 않습니다. `down -v`는 DB를 삭제하므로 백업 없이 실행하지 마세요. 파일 재생성은 기존 대회와 제출을 무효화합니다.

## HTTPS deployment

- `.env`의 JWT secret과 DB password를 새 난수로 변경합니다. URL 비밀번호에는 영숫자/URL-safe 난수를 사용하거나 URL 인코딩합니다.
- TLS reverse proxy를 3000 앞에 놓고 정확한 APP_ORIGIN, COOKIE_SECURE=true를 설정합니다. web bind는 기본 loopback입니다.
- Reverse proxy body size를 2m~3m, 요청 timeout과 connection limits를 설정합니다. Forwarded IP를 사용할 경우 신뢰한 프록시만 허용해야 합니다. 기본 앱은 전달된 X-Forwarded-For를 신뢰하지 않습니다.
- 데이터 저장소에서 검증한 정확한 `data` 디렉터리만 `DATA_HOST_DIR`로 연결합니다. Compose 마운트는 이미 읽기 전용입니다.
- Linux에서 data 디렉터리를 컨테이너 UID 10001이 읽을 수 있게 준비합니다.
- private/labels.csv와 제출 predictions 컬럼이 있는 DB backup은 organizer 전용으로 암호화·접근 제한하세요. 데이터 integrity 검사와 checksum은 운영 전 실행합니다.
- 웹 이미지에는 data 디렉터리를 복사하지 않습니다. private 파일을 public volume/CDN에 업로드하지 마세요.

## Migration, backup, verification

`alembic upgrade head`는 API 시작 전에 자동 실행됩니다. 여러 replicas를 띄우기 전 migration을 한 번 별도 job으로 실행하는 방식으로 전환하세요. `docker compose exec -T postgres pg_dump -U admin challenge > backup.sql`로 백업하고 이 파일은 서버 전용 보관소에 저장합니다.

OpenAPI 확인: `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/openapi.json').status)"`.

테스트: `docker compose exec -w /srv api pytest -q -c /srv/apps/api/pytest.docker.ini` 또는 저장소 루트 Python 환경에서 `pytest -q`. 실제 데이터가 필요한 API 테스트에는 `DATA_DIR`로 검증된 데이터 디렉터리를 지정합니다. CATH 생성·좌표 검증 테스트는 데이터 저장소에서 실행합니다.

최종 공개 전에는 대회를 닫고 유효한 제출, 차단 계정, 공개 점수와 private 점수를 확인하세요. 최종 공개 후 재개는 지원하지 않습니다. 새 대회를 운영하려면 별도 DB/데이터 볼륨을 사용하세요.

구조 파일 다운로드는 대용량 응답이므로 업로드 제한과 혼동하지 마세요. 다운로드 Range 요청을 프록시가 전달하도록 하고, 예상 동시 참가자 수로 대역폭을 점검하세요. **현재 코드는 CSV 제출 프로토타입**입니다. 새 규칙의 모델 ZIP 제출·격리 추론을 구현한 뒤 업로드 크기와 시간 제한을 설정해야 합니다.
