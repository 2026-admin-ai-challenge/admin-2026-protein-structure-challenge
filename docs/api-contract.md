# API·상태 계약

웹사이트팀 네 사람과 데이터/평가 담당자가 **같은 버전**을 쓰기 위한 단일 문서입니다. 계약을 바꿀 때는 이 문서, `apps/api/app/routers/common.py`, `apps/web/app/types.ts`를 함께 고칩니다. 변경은 승현이 반영합니다.

`(임시)` 표시는 운영진·데이터팀 확정 전의 개발용 값입니다. 코드에 박지 않고 환경변수나 관리자 설정으로 뒀습니다.

## 공통

- 모든 경로는 `/api`로 시작합니다. 로그인 세션은 `admin_session` 쿠키(HttpOnly, 12시간)입니다.
- `POST`, `PATCH`에는 헤더 `X-Requested-With: ADMIN-Challenge`가 필요합니다.
- 오류 응답은 `{"detail": "한국어 안내", "code": "기계용 코드"}`입니다. 제출 접수 거절에는 401(로그인 필요)을 빼고 항상 `code`가 있습니다. 차단 계정(`banned`), 요청 속도 제한(`rate_limited`), 잘못된 Content-Length(`bad_request`)도 경로와 관계없이 `code`를 붙입니다. 그 밖의 오류는 `detail`만 있을 수 있습니다.
- 시각은 모두 UTC ISO 8601입니다.

## 제출 상태

```text
            접수(202)                 worker가 가져감              채점 끝
(업로드) ───────────▶ queued ───────────────────▶ running ───────────▶ succeeded
                        ▲                            │
                        │  worker가 죽으면 되돌림      └────────────▶ failed
                        └────────────────────────────┘
                        ▲
                        └── 관리자가 failed 제출을 "다시 채점"
```

| 상태 | 뜻 | 참가자 화면 |
| --- | --- | --- |
| `queued` | 접수됨, 대기열에서 차례를 기다림 | 대기 중, 대기 순서 |
| `running` | worker가 추론·채점 중 | 채점 중 |
| `succeeded` | Public/Private 점수 저장 완료 | Public 점수 |
| `failed` | 실패. `failure_code`와 `error_message`가 있음 | 실패 사유와 안내 |

### 실패 코드 (`failure_code`)

제출 조회의 `file_deleted`는 최고 점수 보관 정책 또는 운영진 수동 정리로 ZIP이 삭제됐는지 표시합니다. `/submissions/me`의 각 항목은 `is_best_public`으로 팀 최고 Public 점수 제출 여부를 표시합니다. 최고 점수 선택 기준은 리더보드와 동일합니다. 삭제 여부와 관계없이 제출 점수·로그·접수 기록은 남습니다. 대회 정보의 `zip_retention`은 `best_public`(기본) 또는 `keep_all`입니다. 보관 예외와 재시도 조건은 운영진 가이드의 제출 파일 관리 절을 참고하세요.

| 코드 | 원인 | 횟수 차감 |
| --- | --- | --- |
| `zip_invalid` | 압축 내용이 규격 위반(심층 검사) | **항상 차감 없음** |
| `install_failed` | `requirements.txt`의 패키지를 설치하지 못함. `error_message`에 pip의 `ERROR:` 줄 | 설정 `count_failed`에 따름 |
| `runtime_error` | 추론 코드가 0이 아닌 코드로 종료 | 〃 |
| `timeout` | 추론이 제한 시간을 넘김 | 〃 |
| `out_of_memory` | 메모리 한도 초과로 종료 | 〃 |
| `output_missing` | 예측 파일이 없음 | 〃 |
| `output_invalid` | 예측 파일 형식·ID·라벨 오류, 출력 크기 초과. `error_message`에 검증기 오류 코드(`[E401]` 등)·메시지·건수·고정 해결 안내 | 〃 |
| `system_error` | 채점 서버 쪽 장애 | **항상 차감 없음** |

`error_message`는 참가자에게 보여도 되는 문장만 담습니다. 컨테이너 출력(`log_tail`)은 **관리자 API에서만** 나갑니다. 추론 코드가 숨긴 평가 입력을 오류 메시지로 빼내는 것을 막기 위해서입니다.

`failure_detail`은 실패 제출의 원인·발생 위치·해결 방법을 담은 문자열이며, 분석할 수 없거나 실패가 아니면 `null`입니다. 실행 로그에서 허용된 예외 종류, 알려진 라이브러리 이름, `inference.py`의 줄 번호만 사용합니다. 임의의 오류 값·모듈명·파일 경로·소스 코드·평가 데이터는 포함하지 않습니다. 기존 실패 제출에도 조회 시 적용됩니다. 웹은 제출 아래 전체 너비로 상세를 표시하며, 관리자에게만 관리자 상세 API를 통한 실행 로그 펼치기를 제공합니다.

### 접수 단계 거절 (HTTP 오류, 기록·차감 없음)

| HTTP | `code` | 상황 |
| --- | --- | --- |
| 400 | `bad_request` | Content-Length가 숫자가 아님 |
| 401 | — | 로그인 필요, 또는 비밀번호 재설정·팀 삭제로 세션 만료 |
| 403 | `banned` | 차단된 계정 |
| 403 | `closed` | 제출 기간이 아님 |
| 413 | `zip_too_large` | 압축 ZIP이 상한 초과 |
| 415 | `not_zip` | 파일 이름이 `.zip`이 아님 |
| 422 | `zip_invalid` | ZIP이 아님, 손상, 필수 항목 누락, 경로 순회, 심볼릭 링크, 중복 경로, 항목 수·해제 크기 초과 |
| 429 | `limit_reached` | 팀 제출 횟수 소진 |
| 429 | `rate_limited` | 계정당 1분에 10회를 넘는 업로드 시도(1분 뒤 다시 가능) |

## 인증

회원가입 API는 없습니다. 계정은 운영진만 만듭니다.

| 메서드·경로 | 요청 | 응답 |
| --- | --- | --- |
| `POST /auth/login` | `{"username","password"}`: `username`에 **팀 이름**(운영진은 관리자 아이디도 가능) | 사용자 |
| `POST /auth/logout` | — | `{"ok":true}` |
| `GET /auth/me` | — | 사용자 |

```json
{"id": 12, "username": null, "display_name": "Team 03", "team_id": 5, "team_name": "Team 03", "role": "USER"}
```

모든 계정은 팀 이름과 배부된 비밀번호로 로그인합니다. 운영진도 운영진 팀 이름으로 로그인할 수 있습니다. 팀 이름은 대소문자와 띄어쓰기(빼고 쳐도 됨)를 구분하지 않습니다. 참가 팀은 계정이 하나뿐이고 따로 아이디가 없어 응답의 `username`은 `null`입니다. 운영진 계정만 `username`에 관리자 아이디가 들어갑니다. 차단된 계정으로는 로그인할 수 없습니다. 운영진은 관리자 아이디로도 로그인할 수 있고, 관리자 아이디와 같은 이름을 입력하면 관리자 로그인으로 처리합니다. 로그인 시도 제한(팀 이름별 분당 10회)은 관리자 아이디에는 걸리지 않습니다. 비밀번호를 재설정하면 그 계정의 기존 로그인은 모두 풀립니다.

## 공개 조회

`GET /competition`

```json
{
  "settings": {"is_open": true, "start_time": "2026-10-24T00:00:00Z", "end_time": "2026-10-24T09:00:00Z",
               "team_submission_limit": 20, "frozen": false, "finalized": false},
  "submission_open": true,
  "dataset_available": true,
  "dataset": {"version": "…", "labels": ["1.10", "…"], "stats": {"…": 0}, "files": {"train.csv": {"rows": 21339, "bytes": 0}}},
  "limits": {"zip_bytes": 524288000, "inference_seconds": 600, "team_submissions": 20,
             "required_entries": ["inference.py", "train.py", "requirements.txt", "model/"]},
  "evaluator": "mock",
  "zip_retention": "best_public",
  "teams": 10,
  "submissions": 37
}
```

- `submission_open`: 지금 제출을 받는지. `dataset_available`: 지금 학습 데이터를 받을 수 있는지(기간 + 관리자 승인).
- `dataset`은 `metadata.json` 중 `version`, `labels`, `stats`, `files`만 담습니다(허용 목록). seed·분할 설정 등 다른 키는 공개하지 않습니다. `stats`도 `classes`, `train`, `test`만 남깁니다. 클래스별 전체 개수(`samples_per_class`)는 학습과 평가를 합친 값이라, 공개된 학습 데이터를 빼면 숨긴 평가 데이터의 클래스 분포가 드러나므로 공개하지 않습니다. `files`도 내려받을 수 있는 파일만 남깁니다.
- 화면의 용량·시간·횟수 문구는 **반드시 `limits`에서** 읽습니다. 숫자를 화면에 직접 쓰지 않습니다.
- `evaluator`가 `mock`이면 점수가 가짜임을 화면에 표시합니다.
- 운영 설정(`count_failed`, `final_selection`)은 이 응답에 넣지 않습니다. 확정된 제출 차감 기준을 적용하려면 관리자 설정 `count_failed`를 켜 둡니다.
- 대회 이름(`title`)도 넣지 않습니다. 이름에 대회 주제가 드러나는데, 이 응답은 대회 시작 전에도 누구나 받기 때문입니다.

`GET /leaderboard?board=public|final`

```json
{"board": "public", "frozen": false, "evaluator": "mock",
 "entries": [{"rank": 1, "team": "Team 03", "score": 0.71234, "grading_seconds": 12.345, "submissions": 4, "last_submission": "2026-10-24T03:10:00Z"},
             {"rank": null, "team": "Team 07", "score": null, "grading_seconds": null, "submissions": 0, "last_submission": null}]}
```

관리자(ADMIN) 계정의 제출은 순위에 들어가지 않습니다. 이 보드에 점수가 없는 참가 팀(차단·관리자 팀 제외)도 순위 뒤에 팀 이름 순으로 `rank`·`score`가 `null`인 항목으로 나옵니다. 웹은 순위를 "—", 점수를 0으로 표시합니다. 웹 리더보드는 화면이 보이는 동안 이 응답을 10초마다 다시 받아 순위 변화를 애니메이션으로 보여 주고, 순위가 동결되면 다시 받지 않습니다.

`final`은 최종 공개 전까지 403입니다. `GET /datasets/{kind}`의 `kind`는 `train`, `train-features`, `train-structures`, `validation-split`과 공개 예제 `example-input`(`example_input.csv`), `example-features`(`example_features.csv`), `example-structures`(`example_structures.zip`), `example-output`(`example_output.csv`)입니다. 평가 입력에 해당하는 경로는 없습니다(404). 데이터팀 분석 차트(`class_distribution.png`, `sequence_length_distribution.png`)는 발표용이라 참가자에게 제공하지 않습니다(404).

`GET /resources/baseline`은 데이터 없이 코드만 담은 베이스라인 ZIP입니다. 대회 기간과 상관없이 받을 수 있지만, 코드에 대회 주제가 드러나므로 `LAUNCH_AT` 전에는 관리자만 받고 나머지는 403입니다.

## 제출 (참가자)

`POST /submissions`: 본문은 **ZIP 원본 바이트**, 헤더 `X-Filename: <URL 인코딩한 파일 이름>`, `Content-Type: application/zip`. 서버는 저장·기본 검사만 하고 즉시 `202`를 돌려줍니다. 여기서는 모델을 실행하지 않습니다.

```json
{"id": 41, "filename": "code.zip", "status": "queued", "failure_code": null, "error_message": null,
 "failure_detail": null, "public_score": null, "grading_seconds": null, "counted": true, "size_bytes": 18342211, "sha256": "…", "file_deleted": false, "evaluator": null,
 "queue_position": 3, "created_at": "…", "started_at": null, "finished_at": null,
 "used": 4, "limit": 20, "remaining": 16}
```

`queue_position`은 대기 중(`queued`)인 제출에만 있습니다. 1이면 다음에 채점이 시작됩니다. 여러 제출을 동시에 채점할 수 있어(`WORKER_SLOTS`) 채점 중인 제출은 순서 없이 `null`입니다.

`GET /submissions/me`: 로그인한 계정의 **팀 전체** 제출과 남은 횟수.

```json
{"entries": [{"id": 41, "…": "위와 같음", "submitted_by": "Team 03"}], "used": 4, "limit": 20, "remaining": 16}
```

`GET /submissions/{id}`: 자기 팀 제출 하나(상태 확인용). 관리자는 모든 팀의 제출을 볼 수 있습니다. Private 점수는 참가자 응답 어디에도 없습니다.

### 횟수 규칙

- 팀 단위, 대회 전체. 날짜가 바뀌어도 복구되지 않습니다.
- **접수된 시점에 1회 사용**합니다(`counted: true`). 접수 단계에서 거절된 업로드는 사용하지 않습니다.
- 채점 실패 시: ZIP 규격 위반(`zip_invalid`)과 서버 오류(`system_error`)는 항상 `counted: false`입니다. 나머지 실패는 1회 차감합니다(관리자 설정 `count_failed`, 기본 켜짐. 끄면 모든 실패가 미차감).
- 같은 팀이 여러 기기에서 동시에 올려도 팀 행을 잠그고 세므로 상한을 넘지 않습니다.
- 다시 채점: 자동으로 미차감된 제출(`zip_invalid`·`system_error`, 또는 `count_failed`가 꺼져 있을 때의 실패)은 `counted: true`로 돌아가 결과에 따라 다시 판정합니다. 관리자가 횟수 복구로 `counted: false`로 만든 제출은 그대로입니다. 팀 한도는 확인하지 않습니다.

## 관리자

모두 `ADMIN` 권한이 필요합니다. 조작은 `audit` 기록에 담당자·시각·대상·결과로 남습니다.

| 메서드·경로 | 용도 |
| --- | --- |
| `GET /admin/overview` | 설정 전체, 대기열 건수, 실패 코드별 건수, worker 상태 |
| `PATCH /admin/competition` | `is_open`, `start_time`, `end_time`, `team_submission_limit`, `count_failed`, `final_selection`, `frozen` |
| `POST /admin/competition/reset` `{"confirm": "초기화"}` | 대회 초기화. 제출·파일 기록·순위·특별상 기록·조작 기록·worker 상태와 디스크의 제출 ZIP을 영구 삭제(따로 보관하지 않음), ID 번호를 1부터 다시 시작, 일정·동결·최종 공개 해제. 대회가 닫혀 있고 살아 있는 채점이 없어야 함. 응답: 지운 건수(`special_awards`, `audit_entries` 포함), 이전 상태(`previous`), 지우지 못한 ZIP(`not_deleted`), 새 설정 |
| `GET /admin/teams` | 팀, 소속 계정(`username`은 운영진만), 사용 횟수, 최고 Public |
| `POST /admin/teams` `{"name"}` · `PATCH /admin/teams/{id}` `{"name"}` | 팀 생성·이름 변경. 팀 이름은 로그인 아이디이므로 다른 팀과 대소문자·띄어쓰기만 다르거나 관리자 아이디와 같으면 409 |
| `POST /admin/teams/{id}/delete` `{"confirm": "<팀 이름>"}` | 팀 영구 삭제. 소속 계정, 제출, 파일 기록과 디스크의 ZIP, 순위 항목을 함께 지움(조작 기록은 남음). 확인 문구가 팀 이름과 같아야 함(대소문자·띄어쓰기 무시, 다르면 422). 최종 공개 후, 관리자 계정이 있는 팀, 채점 중인 제출이 있는 팀은 409(대기 중인 제출은 함께 삭제). 응답: `name`, 지운 계정 수 `accounts`, `submissions`, `files`, 지우지 못한 ZIP `not_deleted` |
| `POST /admin/users` `{"team_id","display_name"?}` | 팀 계정 발급. 팀당 하나이며 이미 계정이 있는 팀은 409(비밀번호를 잊었으면 재설정). `display_name`을 빼면 팀 이름. 응답의 `temporary_password`는 **이때만** 나옴. 로그인은 응답의 `team_name`으로 함 |
| `POST /admin/users/{id}/reset-password` | 새 임시 비밀번호 발급. 응답에 `team_id`, `team_name` 포함 |
| `PATCH /admin/users/{id}` `{"banned"}` | 차단·해제 |
| `GET /admin/submissions?status=&failure_code=&team_id=&q=&limit=` | 제출 목록. Private 점수 포함. `user`는 운영진이 낸 제출의 관리자 아이디, 참가 팀이면 `null` |
| `GET /admin/submissions/{id}` | 상세 + `log_tail` + ZIP 보관 여부, 파일 삭제 기록 |
| `GET /admin/files?team_id=` | 저장된 ZIP 목록과 팀별 보관 개수·용량 |
| `GET /admin/files/{id}/download` | ZIP 내려받기(재현 심사용). 조작 기록에 남음 |
| `POST /admin/files/{id}/delete` `{"reason"}` | ZIP 삭제. 기록은 남고 파일만 지움 |
| `POST /admin/files/verify` | DB 기록과 디스크 비교. 아무것도 바꾸지 않음 |
| `POST /admin/submissions/{id}/requeue` | 실패한 제출을 다시 채점(저장된 ZIP이 있어야 함). `counted` 처리는 위 횟수 규칙 |
| `PATCH /admin/submissions/{id}` `{"counted"}` | 제출 횟수 복구·차감 |
| `POST /admin/leaderboard/recalculate` | 저장된 점수로 Public 순위 다시 만들기 |
| `POST /admin/leaderboard/finalize` | 최종 순위 공개. 대회가 닫혀 있고 대기열이 비어야 함 |
| `GET /admin/awards?board=public\|final` | 특별상 계산표 `efficiency`(성능 대비 ZIP 용량: 점수·용량을 min-max로 0.01~1에 맞춘 `score_scaled ÷ size_scaled`)와 `climb`(첫 점수가 나온 순간 그 순위표에서의 순위 `rank_then` − 지금 순위 `rank`), 기록된 수상팀 `recorded`. `final`은 최종 공개 뒤에만(그 전엔 409) |
| `POST /admin/awards/{efficiency\|climb}` `{"team_id","board"}` | 그 팀을 수상팀으로 기록. 서버가 표를 다시 계산해 그 팀의 줄을 `detail`로 저장하고, 다시 기록하면 바꿈. 표에 없는 팀, 순위가 오르지 않은 팀(`climb`)은 409 |
| `POST /admin/awards/{kind}/delete` | 수상 기록 삭제 |
| `GET /admin/dataset` · `POST /admin/dataset/approve` · `/verify` · `/lock` `{"locked"}` | 데이터 버전 확인·승인·변경 검사·잠금 |
| `GET /admin/audit?limit=` | 조작 기록 |

## 제출 파일 관리

ZIP 내용은 디스크(`submissions` 볼륨)에, 파일 정보는 `submission_files` 테이블에 있습니다. 이 테이블은 **공유 컬럼** `team_id`로 `teams`와, `submission_id`로 `submissions`와 연결됩니다(제출 하나에 파일 하나).

| 컬럼 | 뜻 |
| --- | --- |
| `team_id`, `submission_id`, `uploaded_by` | 소속 팀, 해당 제출, 올린 계정 |
| `original_filename`, `storage_key` | 참가자가 붙인 이름, 디스크의 무작위 저장 이름 |
| `sha256`, `size_bytes`, `created_at` | 해시, 크기, 업로드 시각 |
| `deleted_at`, `deleted_by`, `delete_reason` | 삭제 기록. 비어 있으면 보관 중 |

- 접수할 때 제출 행과 파일 행을 한 트랜잭션으로 씁니다.
- 제출 응답의 `size_bytes`, `sha256`, `file_deleted`는 이 테이블에서 읽습니다. 관리자 응답에는 `file_id`, `on_leaderboard`가 더 있습니다.
- 삭제는 관리자만, 사유와 함께 합니다. **순위에 반영된 제출**과 **채점이 끝나지 않은 제출**의 파일은 삭제할 수 없습니다. 삭제해도 점수·기록·제출 횟수는 그대로이고, 그 제출은 다시 채점할 수 없습니다.
- `ZIP_RETENTION=best_public`(기본)이면 채점이 끝날 때 팀 최고 Public 제출 등 보존 대상만 남기고 나머지 ZIP을 자동 정리합니다. 보존 조건은 운영진 가이드의 제출 파일 관리 절을 보세요. `keep_all`이면 자동 삭제가 없습니다.

## 순위 규칙

- Public 순위: 팀별 최고 Public 점수. 채점 성공 직후 갱신(동결 중이면 해제 때 갱신).
- 동점 `(확정)`: 제출 ZIP(압축 파일) 크기가 작은 쪽, 그다음 먼저 접수한 쪽(접수 시각, 같으면 접수 ID). 팀 안에서 대표 제출(Public·최종 순위, ZIP 보관)을 고를 때와 팀끼리 순위를 정할 때 같은 기준을 씁니다(`app/leaderboard.py`의 `_rank_key`).
- 채점 시간(`grading_seconds`)은 참고용 표시값이며 순위와 대표 제출 선택에 쓰지 않습니다. `running`이 된 시각부터 `succeeded`로 끝난 시각까지의 초로, 대기 시간은 빠지고 패키지 설치·컨테이너 준비 시간은 들어갑니다. 성공하지 않았거나 시작 시각이 없으면 `null`입니다.
- 최종 순위 `(확정, Q7)`: Public 최고 제출물의 Private 점수. 설정 `final_selection=best_public`(기본값)입니다. `best_private`(Private 최고 제출물)는 쓰지 않습니다.
- 다른 평가기로 채점된 제출은 순위에 넣지 않습니다. mock 점수가 실제 순위에 섞이지 않습니다.

## 제출 ZIP 규격 `(임시, Q2·Q3)`

```text
code.zip
├── inference.py        필수
├── train.py            필수. 채점 때 실행하지 않음
├── requirements.txt    필수. 추론 전에 설치할 패키지
└── model/              필수. 학습된 가중치와 전처리 객체
```

- 필수 항목은 **ZIP 최상위**에 있어야 합니다. 목록은 환경변수 `ZIP_REQUIRED`.
- 압축 ZIP은 공지상 최대 500 MB이며 현재 `MAX_ZIP_BYTES` 기본값은 524,288,000 bytes(500 MiB)입니다. 정확한 접수 한도는 API의 `limits.zip_bytes`를 따릅니다. 해제 후 합계 2 GiB, 항목 2,000개(`MAX_UNZIPPED_BYTES`, `MAX_ZIP_ENTRIES`, 임시).
- 거절: 절대 경로, `..`, 심볼릭 링크·특수 파일, 같은 경로 중복, 암호화.
- `requirements.txt` 검사(`app/packages.py`): 패키지 종류와 버전은 제한하지 않습니다. pip이 인덱스 밖에서 무언가를 가져오게 하는 줄(`-r`·`-c`·`-e`, 경로·URL)과 알 수 없는 옵션만 `422 zip_invalid`로 거절합니다. 인덱스 옵션과 `--hash`는 무시하고, Linux 컨테이너에 해당하지 않는 환경 표시(`; sys_platform == "win32"`) 줄은 건너뜁니다. 같은 패키지 줄은 버전 조건을 합치고, `+cu128` 같은 로컬 버전 표시는 지웁니다. 최대 64 KB·300개, UTF-8 또는 UTF-16(BOM). pip에는 원문이 아니라 `packaging`이 다시 쓴 요구사항만 넘깁니다.

## 추론 실행 계약 `(임시, 데이터/평가팀과 확정 필요)`

채점 컨테이너 안에서 다음과 같이 실행합니다.

```text
작업 디렉터리  /submission        (ZIP을 푼 내용, 읽기 전용)
명령          python inference.py --input /input/test_features.csv --output /output/predictions.csv
입력          /input              (숨긴 평가 입력, 읽기 전용)
                test_features.csv     id + 특징 31개 (train_features.csv와 같은 열)
                test.csv              id,sequence
                test_structures.zip   샘플별 NPZ 구조 (train_structures.zip과 같은 형식)
출력          /output/predictions.csv   UTF-8, 헤더 id,label, 평가 ID마다 정확히 한 줄
```

`--input`은 데이터팀 베이스라인과 같이 **특징 CSV 파일 경로**입니다. 서열이나 구조를 쓰는 모델은 같은 폴더(`Path(args.input).parent`)의 `test.csv`, `test_structures.zip`을 읽습니다. 서버의 `EVAL_INPUT_HOST_DIR`에는 이 세 파일만 둔 별도 폴더를 지정하고, 정답이 들어 있는 `data/private`를 그대로 연결하지 않습니다.

- 네트워크 없음, 읽기 전용 루트, 일반 사용자(65534), CPU·메모리·프로세스 수 제한, `/tmp`만 쓰기 가능.
- 이미지에는 기본 패키지(`apps/evaluator/requirements.txt`)만 설치되어 있고, 데이터팀 89개 목록의 wheel은 `/opt/wheels`에 받아만 둡니다. `requirements.txt`가 패키지를 요구하면 설치 컨테이너가 제출 전용 Docker 볼륨에 가상환경을 만듭니다. ① 먼저 **네트워크 없이** `/opt/wheels`만으로 설치하고, ② 거기에 없는 패키지·버전이 있을 때만 **네트워크를 연** 컨테이너에서 PyPI(와 PyTorch CPU 인덱스)로 받습니다. 두 단계 모두 추론과 같은 제한(읽기 전용, 사용자 65534 등)을 걸고, 제출 내용과 평가 입력은 붙이지 않으며, wheel만 받으므로 네트워크가 열린 동안 참가자가 고른 코드는 실행되지 않습니다. 추론 컨테이너는 볼륨을 `/deps`에 읽기 전용으로 받고 `/deps/venv/bin`이 PATH 맨 앞이라 `python`이 그 환경을 씁니다. 추론에는 계속 네트워크가 없습니다.
- 설치 시간(`EVAL_INSTALL_TIMEOUT_SECONDS`, 두 단계 합계 기본 600초)은 추론 제한과 따로 셉니다. 없는 패키지·버전 충돌·wheel 없음은 `install_failed`(팀 책임), PyPI 연결 실패·설치 시간 초과·docker 오류는 `system_error`(차감 없음)입니다. 온라인 단계의 내려받은 파일은 공유 볼륨 `admin-eval-pip-cache`(`EVAL_PIP_CACHE_VOLUME`, 비우면 끔)에 캐시합니다. 패키지 볼륨은 채점이 끝나면 지웁니다.
- 정답, Public/Private 분할표, DB 정보, Docker 소켓은 컨테이너에 주지 않습니다. 정답 비교는 컨테이너 밖 worker가 합니다.
- 명령은 환경변수 `EVAL_COMMAND`, 이미지는 `EVAL_IMAGE`, 자원은 `EVAL_CPUS`·`EVAL_MEMORY`·`EVAL_PIDS`로 바꿉니다.

### 데이터/평가팀에 확인할 것

1. `/input` 아래 파일 이름과 스키마(서열 CSV, 특징 CSV, 구조 NPZ의 배치).
2. 진입점 형태: 위의 `--input/--output` 인자 방식으로 고정해도 되는가.
3. 채점 이미지의 기본 패키지(`apps/evaluator/requirements.txt`)와 미리 받아 둘 89개 목록(`runtime/requirements-competition.lock.txt`). 목록을 바꾸면 사본을 갱신하고 이미지를 다시 빌드합니다. 목록 밖 패키지도 설치는 되지만 PyPI에서 받으므로 느립니다.
4. `metadata.json`에 `version`과 `validation`(검증 통과 여부)을 넣어 줄 수 있는가. 관리자 데이터 화면이 이 값을 읽습니다.
5. ~~작은 공개 예제 입출력 파일의 이름.~~ → 데이터팀이 만든 `example_input.csv`, `example_features.csv`, `example_structures.zip`, `example_output.csv`를 그대로 내려줍니다.
