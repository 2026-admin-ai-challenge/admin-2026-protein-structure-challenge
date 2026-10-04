# prediction_validator (데이터팀 코드 복사본)

채점 worker가 예측 파일을 점수 계산 전에 검사할 때 쓰는 데이터팀 검증기입니다. 여기서 고치지 않습니다.

- 원본: `admin-2026-protein-data`의 `scripts/prediction_validator/`, 계약은 `contract/prediction_contract.json` → `apps/api/contract/`
- 기준 커밋: `main` `44e28e4` (이 파일들의 마지막 변경 `4e9df45`)
- 갱신: 데이터 저장소에서 수정·병합한 뒤 두 경로를 그대로 다시 복사하고 기준 커밋을 고칩니다.

worker는 `app/scoring/predictions.py`를 거쳐 호출하고 계약 경로를 직접 넘깁니다. 명령줄로 쓸 때도 `--contract`가 필요합니다.

```bash
cd apps/api
python -m prediction_validator predictions.csv --contract contract/prediction_contract.json \
    --eval-ids <data>/private/test.csv --classes-metadata <data>/public/metadata.json
```
