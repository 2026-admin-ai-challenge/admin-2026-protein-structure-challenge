# Competition guide

단백질 관측 서열과 제공된 3D 구조로 CATH Architecture를 분류합니다. Data에서 Starter Kit을 받아 CPU Logistic Regression으로 첫 제출을 만들어 보세요. 필요에 따라 학습·시험 구조 ZIP을 받을 수 있습니다. 모델과 특징 구성은 자유롭게 선택합니다. 입력 구조를 다시 예측하거나 PDB를 직접 파싱할 필요가 없습니다. `id,label` CSV를 Submit에 올리면 validation과 Public Macro F1 채점이 진행됩니다.

허용: 공개 pretrained model, Protein Language Model, 출처를 밝힌 외부 공개 데이터. 금지: 서열·구조 검색을 통한 CATH/PDB 시험 정답 lookup, domain ID 복원 후 조회, 직접 수작업 label, 계정·예측 공유, 다중 계정 제출 우회. 대회 종료 시 전체 재현 코드를 요구할 수 있습니다.

기본 UTC 하루 5회, 실패 제출 포함, 2 MB 이하, UTF-8 CSV. 관리자 설정과 대회 화면의 실제 일정이 우선합니다. 시작 전/종료 후/닫힌 상태에서는 제출되지 않습니다. 대회 종료 후 관리자만 Final 순위를 공개할 수 있습니다.

대회 전 공개: `/api/resources/baseline`의 baseline_code.zip은 코드·노트북·설명서만 포함합니다. 데이터·특징 표·좌표·시험 정답은 없으며 전체 Starter Kit은 대회 시간 제한을 유지합니다.
> **기존 CSV 제출 프로토타입 문서입니다.** 새 대회의 모델 제출·제공 데이터만 사용 규정으로 전면 갱신해야 합니다. 이 문구를 참가자 규정으로 게시하지 마세요.
