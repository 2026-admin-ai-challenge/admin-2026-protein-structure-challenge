# Evaluation contract

`sklearn.metrics.f1_score(y_true, y_pred, labels=all_architectures, average="macro", zero_division=0)`를 사용합니다. 항상 전체 허용 label 목록을 명시하므로 특정 클래스가 예측되지 않아도 그 클래스가 평균에서 누락되지 않습니다.

UTF-8(BOM 허용) CSV의 column 순서는 정확히 `id,label`. 2 MB 이하. Null, 추가 열, 중복 ID, unknown/missing ID, 허용하지 않은 label을 거부합니다. label은 문자열이며 `1.10`을 `1.1`로 바꾸지 마세요. 제출 행 순서는 자유이며 private answer의 ID 기준으로 안전하게 정렬합니다.

한 참가자의 UTC 하루 제한은 invalid와 success 기록을 모두 셉니다. 인증 실패, 업로드 전체 크기 초과(HTTP 413), 닫힌 대회, 제한 초과는 채점 시도 전에 거절되어 기록되지 않습니다. 에러 메시지를 반환하는 검증 실패는 기록됩니다.

Public와 Private는 분리 채점하고 일반 응답은 Public만 반환합니다. Public 순위는 팀별 최고 Public, Final 순위는 팀별 최고 Private. 자동으로 가장 높은 점수를 사용하며 최종 제출 선택 UI는 없습니다. 동점은 최고 점수 달성 시각이 빠른 순, 그 뒤 제출 ID 순입니다. 표시는 5자리, 내부 순위는 전체 float 정밀도입니다.

Freeze는 순위 snapshot만 동결하며 제출·개인 Public score는 계속 이용 가능합니다. Unfreeze에서 최신 순위를 재구성합니다. 차단된 계정은 동결 중에도 순위 조회에서 제외됩니다. Finalize는 닫힌 상태에서만 허용되며 최종 snapshot 이후 제출, 계정 상태 변경, 재계산, 대회 재개를 거부합니다.
> **기존 CSV 제출 프로토타입 문서입니다.** 새 대회의 팀당 10회·모델 추론 채점 정책으로 갱신해야 합니다.
