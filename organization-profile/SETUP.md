# GitHub Organization 첫 화면 적용 안내

현재 `2026-admin-ai-challenge` Organization에는 **`.github` 저장소가 없습니다**. 이 폴더는 Organization 프로필 초안입니다. 기존 웹사이트 저장소의 README에 붙이는 것만으로는 Organization 첫 화면이 바뀌지 않습니다.

## 실제 적용

1. `2026-admin-ai-challenge` Organization에서 **Public** 저장소를 `.github`라는 이름으로 만듭니다.
2. 해당 저장소 기본 브랜치의 `profile/README.md`로 이 폴더의 `README.md`를 복사합니다.
3. `profile/assets/hero.svg`로 이 폴더의 `assets/hero.svg`를 복사합니다.
4. https://github.com/2026-admin-ai-challenge 에서 프로필이 표시되는지 확인합니다.
5. 게시 전에 **3위/4위 Private 점수 역전 문제**를 최종 운영 데이터로 검증합니다.

## 중요: 접근 권한 확인

GitHub 조회 결과 `admin-2026-protein-data` 저장소는 공개(public) 상태인데, 해당 저장소 문서에는 평가 정답과 배정표를 보관해 대회 중 비공개여야 한다고 적혀 있습니다. 현재 실제 노출된 파일을 별도로 점검하고, 비공개 자료가 있다면 Git 기록 포함 접근을 차단해야 합니다.

이 프로필의 리더보드 수치는 결과 화면을 옮긴 정적 기록이며 자동 갱신되지 않습니다.
