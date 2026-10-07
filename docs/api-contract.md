# API·상태 계약

웹사이트팀 네 사람과 데이터/평가 담당자가 **같은 버전**을 쓰기 위한 단일 문서입니다. 계약을 바꿀 때는 이 문서, `apps/api/app/routers/common.py`, `apps/web/app/types.ts`를 함께 고칩니다. 변경은 승현이 반영합니다.

`(임시)` 표시는 운영진·데이터팀 확정 전의 개발용 값입니다. 코드에 박지 않고 환경변수나 관리자 설정으로 뒀습니다.

## 공통

- 모든 경로는 `/api`로 시작합니다. 로그인 세션은 `admin_session` 쿠키(HttpOnly, 12시간)입니다.
- `POST`, `PATCH`에는 헤더 `X-Requested-With: ADMIN-Challenge`가 필요합니다.
- 오류 응답은 `{"detail": "한국어 안내", "code": "기계용 코드"}`입니다. `code`는 제출 접수 오류에만 항상 있습니다.
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

| 코드 | 원인 | 횟수 차감 |
| --- | --- | --- |
| `zip_invalid` | 압축 내용이 규격 위반(심층 검사) | **항상 차감 없음** |
| `runtime_error` | 추론 코드가 0이 아닌 코드로 종료 | 〃 |
| `timeout` | 추론이 제한 시간을 넘김 | 〃 |
| `out_of_memory` | 메모리 한도 초과로 종료 | 〃 |
| `output_missing` | 예측 파일이 없음 | 〃 |
| `output_invalid` | 예측 파일 형식·ID·라벨 오류, 출력 크기 초과. `error_message`에 검증기 오류 코드(`[E401]` 등)와 건수 | 〃 |
| `system_error` | 채점 서버 쪽 장애 | **항상 차감 없음** |

`error_message`는 참가자에게 보여도 되는 문장만 담습니다. 컨테이너 출력(`log_tail`)은 **관리자 API에서만** 나갑니다. 추론 코드가 숨긴 평가 입력을 오류 메시지로 빼내는 것을 막기 위해서입니다.

### 접수 단계 거절 (HTTP 오류, 기록·차감 없음)

| HTTP | `code` | 상황 |
| --- | --- | --- |
| 401 | — | 로그인 필요, 또는 비밀번호 재설정으로 세션 만료 |
| 403 | `closed` | 제출 기간이 아님 |
| 413 | `zip_too_large` | 압축 ZIP이 상한 초과 |
| 415 | `not_zip` | 파일 이름이 `.zip`이 아님 |
| 422 | `zip_invalid` | ZIP이 아님, 손상, 필수 항목 누락, 경로 순회, 심볼릭 링크, 중복 경로, 항목 수·해제 크기 초과 |
| 429 | `limit_reached` | 팀 제출 횟수 소진 |

## 인증

회원가입 API는 없습니다. 계정은 운영진만 만듭니다.

| 메서드·경로 | 요청 | 응답 |
| --- | --- | --- |
| `POST /auth/login` | `{"username","password"}` | 사용자 |
| `POST /auth/logout` | — | `{"ok":true}` |
| `GET /auth/me` | — | 사용자 |

```json
{"id": 12, "username": "k7m2xq9rtd", "display_name": "Team 03", "team_id": 5, "team_name": "Team 03", "role": "USER"}
```

아이디는 대소문자를 구분하지 않습니다. 비밀번호를 재설정하면 그 계정의 기존 로그인은 모두 풀립니다.

## 공개 조회

`GET /competition`

```json
{
  "settings": {"is_open": true, "start_time": "2026-10-24T00:00:00Z", "end_time": "2026-10-24T09:00:00Z",
               "team_submission_limit": 20, "frozen": false, "finalized": false},
  "submission_open": true,
  "dataset_available": true,
  "dataset": {"version": "…", "labels": ["1.10", "…"], "stats": {"…": 0}, "files": {"train.csv": {"rows": 21545, "bytes": 0}}},
  "limits": {"zip_bytes": 524288000, "inference_seconds": 600, "team_submissions": 10,
             "required_entries": ["inference.py", "train.py", "requirements.txt", "model/"]},
  "evaluator": "mock",
  "teams": 10,
  "submissions": 37
}
```

- `submission_open`: 지금 제출을 받는지. `dataset_available`: 지금 학습 데이터를 받을 수 있는지(기간 + 관리자 승인).
- 화면의 용량·시간·횟수 문구는 **반드시 `limits`에서** 읽습니다. 숫자를 화면에 직접 쓰지 않습니다.
- `evaluator`가 `mock`이면 점수가 가짜임을 화면에 표시합니다.
- 미확정 정책(`count_failed`, `final_selection`)은 이 응답에 넣지 않습니다.
- 대회 이름(`title`)도 넣지 않습니다. 이름에 대회 주제가 드러나는데, 이 응답은 대회 시작 전에도 누구나 받기 때문입니다.

`GET /leaderboard?board=public|final`

```json
{"board": "public", "frozen": false, "evaluator": "mock",
 "entries": [{"rank": 1, "team": "Team 03", "score": 0.71234, "submissions": 4, "last_submission": "2026-10-24T03:10:00Z"}]}
```

`final`은 최종 공개 전까지 403입니다. `GET /datasets/{kind}`의 `kind`는 `train`, `train-features`, `train-structures`, `validation-split`, `example`(임시 이름)입니다. 평가 입력에 해당하는 경로는 없습니다(404). 데이터팀 분석 차트(`class_distribution.png`, `sequence_length_distribution.png`)는 발표용이라 참가자에게 제공하지 않습니다(404).

`GET /resources/baseline`은 데이터 없이 코드만 담은 베이스라인 ZIP입니다. 대회 기간과 상관없이 받을 수 있지만, 코드에 대회 주제가 드러나므로 `LAUNCH_AT` 전에는 관리자만 받고 나머지는 403입니다.

## 제출 (참가자)

`POST /submissions`: 본문은 **ZIP 원본 바이트**, 헤더 `X-Filename: <URL 인코딩한 파일 이름>`, `Content-Type: application/zip`. 서버는 저장·기본 검사만 하고 즉시 `202`를 돌려줍니다. 여기서는 모델을 실행하지 않습니다.

```json
{"id": 41, "filename": "code.zip", "status": "queued", "failure_code": null, "error_message": null,
 "public_score": null, "counted": true, "size_bytes": 18342211, "sha256": "…", "file_deleted": false, "evaluator": null,
 "queue_position": 3, "created_at": "…", "started_at": null, "finished_at": null,
 "used": 4, "limit": 10, "remaining": 6}
```

`GET /submissions/me`: 로그인한 계정의 **팀 전체** 제출과 남은 횟수.

```json
{"entries": [{"id": 41, "…": "위와 같음", "submitted_by": "Team 03"}], "used": 4, "limit": 10, "remaining": 6}
```

`GET /submissions/{id}`: 자기 팀 제출 하나(상태 확인용). Private 점수는 참가자 응답 어디에도 없습니다.

### 횟수 규칙

- 팀 단위, 대회 전체. 날짜가 바뀌어도 복구되지 않습니다.
- **접수된 시점에 1회 사용**합니다(`counted: true`). 접수 단계에서 거절된 업로드는 사용하지 않습니다.
- 채점 실패 시: ZIP 규격 위반(`zip_invalid`)과 서버 오류(`system_error`)는 항상 `counted: false`입니다. 나머지 실패는 1회 차감합니다(관리자 설정 `count_failed`, 기본 켜짐. 끄면 모든 실패가 미차감).
- 같은 팀의 여러 계정이 동시에 올려도 팀 행을 잠그고 세므로 상한을 넘지 않습니다.

## 관리자

모두 `ADMIN` 권한이 필요합니다. 조작은 `audit` 기록에 담당자·시각·대상·결과로 남습니다.

| 메서드·경로 | 용도 |
| --- | --- |
| `GET /admin/overview` | 설정 전체, 대기열 건수, 실패 코드별 건수, worker 상태 |
| `PATCH /admin/competition` | `is_open`, `start_time`, `end_time`, `team_submission_limit`, `count_failed`, `final_selection`, `frozen` |
| `POST /admin/competition/reset` `{"confirm": "초기화"}` | 대회 초기화. 제출·파일 기록·순위·조작 기록·worker 상태와 디스크의 제출 ZIP을 영구 삭제(따로 보관하지 않음), ID 번호를 1부터 다시 시작, 일정·동결·최종 공개 해제. 대회가 닫혀 있고 살아 있는 채점이 없어야 함. 응답: 지운 건수(`audit_entries` 포함), 이전 상태(`previous`), 지우지 못한 ZIP(`not_deleted`), 새 설정 |
| `GET /admin/teams` | 팀, 소속 계정, 사용 횟수, 최고 Public |
| `POST /admin/teams` `{"name"}` · `PATCH /admin/teams/{id}` `{"name"}` | 팀 생성·이름 변경 |
| `POST /admin/users` `{"team_id","username"?}` | 계정 발급. `username`을 빼면 랜덤 10자리. 응답의 `temporary_password`는 **이때만** 나옴 |
| `POST /admin/users/{id}/reset-password` | 새 임시 비밀번호 발급 |
| `PATCH /admin/users/{id}` `{"banned"}` | 차단·해제 |
| `GET /admin/submissions?status=&failure_code=&team_id=&q=&limit=` | 제출 목록. Private 점수 포함 |
| `GET /admin/submissions/{id}` | 상세 + `log_tail` + ZIP 보관 여부, 파일 삭제 기록 |
| `GET /admin/files?team_id=` | 저장된 ZIP 목록과 팀별 보관 개수·용량 |
| `GET /admin/files/{id}/download` | ZIP 내려받기(재현 심사용). 조작 기록에 남음 |
| `POST /admin/files/{id}/delete` `{"reason"}` | ZIP 삭제. 기록은 남고 파일만 지움 |
| `POST /admin/files/verify` | DB 기록과 디스크 비교. 아무것도 바꾸지 않음 |
| `POST /admin/submissions/{id}/requeue` | 실패한 제출을 다시 채점 |
| `PATCH /admin/submissions/{id}` `{"counted"}` | 제출 횟수 복구·차감 |
| `POST /admin/leaderboard/recalculate` | 저장된 점수로 Public 순위 다시 만들기 |
| `POST /admin/leaderboard/finalize` | 최종 순위 공개. 대회가 닫혀 있고 대기열이 비어야 함 |
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
- 자동 삭제는 없습니다. 보관 기간은 운영진 미결정 사항입니다.

## 순위 규칙

- Public 순위: 팀별 최고 Public 점수. 채점 성공 직후 갱신(동결 중이면 해제 때 갱신).
- 동점: 점수가 기록된 시각이 빠른 쪽, 그다음 접수 ID가 작은 쪽.
- 최종 순위 `(임시, Q7)`: 설정 `final_selection`. `best_public`(기본)은 Public 최고 제출물의 Private 점수, `best_private`는 Private 최고 제출물.
- 다른 평가기로 채점된 제출은 순위에 넣지 않습니다. mock 점수가 실제 순위에 섞이지 않습니다.

## 제출 ZIP 규격 `(임시, Q2·Q3)`

```text
code.zip
├── inference.py        필수
├── train.py            필수. 채점 때 실행하지 않음
├── requirements.txt    필수. 추론 전에 설치할 패키지 (대회 패키지 목록 안에서만)
└── model/              필수. 학습된 가중치와 전처리 객체
```

- 필수 항목은 **ZIP 최상위**에 있어야 합니다. 목록은 환경변수 `ZIP_REQUIRED`.
- 압축 ZIP 최대 500 MB(`MAX_ZIP_BYTES`, 확정). 해제 후 합계 2 GiB, 항목 2,000개(`MAX_UNZIPPED_BYTES`, `MAX_ZIP_ENTRIES`, 임시).
- 거절: 절대 경로, `..`, 심볼릭 링크·특수 파일, 같은 경로 중복, 암호화.
- `requirements.txt` 검사(`app/packages.py`): 모든 패키지가 `PACKAGE_LOCK`(`apps/evaluator/requirements-competition.lock.txt`, 데이터팀 `runtime/`의 89개 고정 목록 사본)에 있어야 합니다. 아니면 `422 zip_invalid`로 거절하며 메시지에 해당 패키지를 모두 적습니다. 버전 지정은 보지 않고 항상 목록의 버전을 설치합니다(`filelock==4.0.10` → 4.0.9, `numpy<2` → 2.5.3). `-r`·`-c`·`-e`, 경로·URL, extras도 거절합니다. 인덱스 옵션과 `--hash`는 무시하고, Linux 컨테이너에 해당하지 않는 환경 표시(`; sys_platform == "win32"`) 줄은 건너뜁니다. 최대 64 KB, UTF-8 또는 UTF-16(BOM).

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
- 이미지에는 기본 패키지(`apps/evaluator/requirements.txt`)만 설치되어 있습니다. `requirements.txt`가 패키지를 요구하면, 같은 제한을 건 설치 컨테이너가 이미지 안의 wheel(`/opt/wheels`)로 제출 전용 Docker 볼륨에 가상환경을 만듭니다. 추론 컨테이너는 그 볼륨을 `/deps`에 읽기 전용으로 받고 `/deps/venv/bin`이 PATH 맨 앞이라 `python`이 그 환경을 씁니다. 설치 시간(`EVAL_INSTALL_TIMEOUT_SECONDS`, 기본 600초)은 추론 제한과 따로 셉니다. 설치 실패는 접수 때 검사를 통과한 목록에서 생긴 서버 문제이므로 `system_error`(차감 없음)입니다. 볼륨은 채점이 끝나면 지웁니다.
- 정답, Public/Private 분할표, DB 정보, Docker 소켓은 컨테이너에 주지 않습니다. 정답 비교는 컨테이너 밖 worker가 합니다.
- 명령은 환경변수 `EVAL_COMMAND`, 이미지는 `EVAL_IMAGE`, 자원은 `EVAL_CPUS`·`EVAL_MEMORY`·`EVAL_PIDS`로 바꿉니다.

### 데이터/평가팀에 확인할 것

1. `/input` 아래 파일 이름과 스키마(서열 CSV, 특징 CSV, 구조 NPZ의 배치).
2. 진입점 형태: 위의 `--input/--output` 인자 방식으로 고정해도 되는가.
3. 채점 이미지의 기본 패키지(`apps/evaluator/requirements.txt`)와 참가자가 고를 수 있는 89개 목록(`runtime/requirements-competition.lock.txt`). 목록을 바꾸면 사본과 이미지를 함께 갱신합니다.
4. `metadata.json`에 `version`과 `validation`(검증 통과 여부)을 넣어 줄 수 있는가. 관리자 데이터 화면이 이 값을 읽습니다.
5. 작은 공개 예제 입출력 파일의 이름. 지금은 `example_io.zip`으로 가정했습니다.
