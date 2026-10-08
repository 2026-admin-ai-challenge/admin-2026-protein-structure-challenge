# prediction_validator (데이터팀 코드 복사본)

채점 worker가 예측 파일을 점수 계산 전에 검사할 때 쓰는 데이터팀 검증기입니다. 여기서 고치지 않습니다.

- 원본: `admin-2026-protein-data`의 `scripts/prediction_validator/`, 계약은 `contract/prediction_contract.json` → `apps/api/contract/`
- 기준 커밋: 데이터 저장소 PR #15 (계약 `0.3.0-draft`)
- 갱신: 데이터 저장소에서 수정·병합한 뒤 두 경로를 다시 복사하고 기준 커밋을 고칩니다. 계약의 운영 정책은 아래 기준과 대조합니다.

## 제출 횟수 정책 (Q4)

ZIP 규격 위반(`zip_invalid`)과 서버 오류(`system_error`)만 미차감입니다.
예측 출력 형식 오류(`output_invalid`)를 포함한 나머지 채점 실패는 1회 차감합니다.
대회 운영 시 관리자 설정 `count_failed`를 켜 둡니다.

데이터 저장소 PR #15의 계약 원본에는 "형식 오류 미차감"이라는 설명이 남아 있습니다.
웹 계약 사본의 `decided.Q4`는 운영진 확정 기준과 웹 PR #6의 실제 동작에 맞춰 수정했습니다.
Q7은 웹 PR #18의 Public 최고 제출물 기준으로 확정하고, 문서의 낡은 ZIP 크기·구성 상충 설명도 제거했습니다. 최상위 필수 항목과 실행 경로의 최종 확정(Q2), 해제 후 안전 상한(Q3)은 계속 미정입니다.
원본 정책 문구가 수정되기 전에는 사본 갱신 시 이 설명을 다시 덮어쓰지 않습니다.
검증기 코드는 원본을 사용하고, 제출 횟수 차감은 웹 worker가 처리합니다.

갱신을 빠뜨리면 계약의 `expected_rows` 가 실제 데이터와 어긋납니다. 2026-10-08
점검에서 실제로 어긋난 상태(사본 5,387 / 실제 5,330)가 발견됐고, 그래서
`verify_contract_against_dataset()` 가 추가됐습니다. worker 시작 시 한 번
호출하면 어긋난 계약으로 채점하는 것을 막습니다 (`E903`). 현재 worker 시작 경로에는 이 호출이 연결돼 있지 않으므로 후속 구현이 필요합니다.

worker는 `app/scoring/predictions.py`를 거쳐 호출하고 계약 경로를 직접 넘깁니다. 명령줄로 쓸 때도 `--contract`가 필요합니다.

```bash
cd apps/api
python -m prediction_validator predictions.csv --contract contract/prediction_contract.json \
    --eval-ids <data>/private/test.csv --classes-metadata <data>/public/metadata.json
```
