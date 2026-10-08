# prediction_validator (데이터팀 코드 복사본)

채점 worker가 예측 파일을 점수 계산 전에 검사할 때 쓰는 데이터팀 검증기입니다. 여기서 고치지 않습니다.

- 원본: `admin-2026-protein-data`의 `scripts/prediction_validator/`, 계약은 `contract/prediction_contract.json` → `apps/api/contract/`
- 기준 커밋: 데이터 저장소 PR #15 (계약 `0.3.0-draft`)
- 갱신: 데이터 저장소에서 수정·병합한 뒤 두 경로를 그대로 다시 복사하고 기준 커밋을 고칩니다.

갱신을 빠뜨리면 계약의 `expected_rows` 가 실제 데이터와 어긋납니다. 2026-10-08
점검에서 실제로 어긋난 상태(사본 5,387 / 실제 5,330)가 발견됐고, 그래서
`verify_contract_against_dataset()` 가 추가됐습니다. worker 시작 시 한 번
호출하면 어긋난 계약으로 채점하는 것을 막습니다 (`E903`).

worker는 `app/scoring/predictions.py`를 거쳐 호출하고 계약 경로를 직접 넘깁니다. 명령줄로 쓸 때도 `--contract`가 필요합니다.

```bash
cd apps/api
python -m prediction_validator predictions.csv --contract contract/prediction_contract.json \
    --eval-ids <data>/private/test.csv --classes-metadata <data>/public/metadata.json
```
