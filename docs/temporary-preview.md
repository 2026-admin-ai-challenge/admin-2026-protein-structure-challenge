# 임시 HTTPS 공유

Cloudflare Quick Tunnel로 이 PC의 Docker 웹 서비스를 공유합니다. [Cloudflare 공식 안내](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). 클라우드로 DB/정답 파일을 옮기지 않고 HTTP 요청을 현재 웹 서비스에 연결합니다. PC 절전, Docker 종료, tunnel 중단 시 링크도 중단되며, 재시작하면 새 주소가 나올 수 있습니다. 운영용 호스팅/SLA는 아닙니다.

## 시작

1. `.env`에 새 임의 `SECRET_KEY`를 설정하고 `COOKIE_SECURE=true`로 설정합니다. 공개 기본 개발 secret을 사용하지 마세요.
2. `docker compose up --build -d`로 수정된 API를 실행합니다.
3. `/api/datasets/train`이 시작 전 403이며 `/api/competition`의 `dataset`이 null인지 확인합니다.
4. `docker compose -f docker-compose.yml -f docker-compose.preview.yml up -d tunnel`을 실행합니다.
5. `docker compose -f docker-compose.yml -f docker-compose.preview.yml logs tunnel`에 나온 HTTPS 주소를 `.env`의 `APP_ORIGIN`으로 설정합니다.
6. `docker compose -f docker-compose.yml -f docker-compose.preview.yml up -d api`로 정확한 Origin을 반영합니다.

임시 링크의 웹 기능은 동일하게 동작합니다. 인증 쿠키는 HTTPS 전용이고 다른 Origin의 쓰기 요청을 거절합니다. tunnel에는 웹 전용 네트워크만 연결되며 PostgreSQL/API 포트를 직접 공개하지 않습니다.

## 중지

```bash
docker compose -f docker-compose.yml -f docker-compose.preview.yml stop tunnel
```

데이터베이스와 로컬 웹 서비스는 유지됩니다. 다시 로컬 주소에서 로그인하려면 `.env`의 APP_ORIGIN을 http://localhost:3000으로 되돌리고 API를 재시작합니다.

## 데이터 공개 정책

운영자가 시작·종료 시각을 모두 설정하고 대회를 열어야 다운로드할 수 있습니다. 서버 시각 기준 `[start_time, end_time)`에만 train/test/sample/분포 그림 및 메타데이터를 반환합니다. 수동으로 닫거나 최종 순위를 공개하면 즉시 차단합니다. 날짜를 아직 모르면 닫힌 상태로 유지하세요. 같은 날만 공개하려면 시작과 종료를 대회 당일의 원하는 시각으로 지정합니다.

현재 GitHub 저장소는 비공개입니다. 생성된 공개용 CSV/통계/그림도 새 커밋부터 추적하지 않습니다. 이전 커밋의 생성본은 과거 이력에 남아 있으므로 이 저장소의 접근 권한은 운영자에게만 제공하세요. 이미 내려받은 파일을 회수하는 기능은 없습니다.
