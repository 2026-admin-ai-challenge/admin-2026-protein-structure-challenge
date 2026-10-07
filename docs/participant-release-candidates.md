# ADMIN 2026 참가자 배포 후보

> 운영진·데이터팀·평가팀 협의용 권장안입니다. 확정된 배포 목록이나 다운로드 구현 완료를 뜻하지 않습니다. 현재 계약은 [README](../README.md), [참가자 안내](competition.md), [API·추론 계약](api-contract.md), [평가 방식](evaluation.md)을 기준으로 하며, 차이는 아래 ‘확정 전 체크사항’에서 관리합니다.

참가자는 자기 컴퓨터에서 학습하고, 학습된 모델과 추론 코드를 제출합니다. 서버는 숨긴 평가 입력으로 `inference.py`만 실행합니다. 따라서 공개 배포본에는 학습 자료와 공개 샘플, 실행·제출 안내만 포함합니다. 데이터 생성과 배포 파일 제작은 별도 `admin-2026-protein-data` 저장소의 담당이며, 이 문서는 웹사이트에서 제공할 배포 경계를 정합니다. 실제 생성 데이터와 ZIP은 이 Git 저장소에 커밋하지 않습니다.

## 1. 권장 배포 구조

두 ZIP을 같은 위치에 풀었을 때의 논리적 구조입니다. `sample.csv`와 `sample_structures.zip`도 `sample_input/` 안에 둡니다.

```text
ADMIN_2026_RELEASE/
├── README.md
├── data/
│   ├── README.md
│   ├── train.csv
│   ├── train_features.csv
│   └── train_structures.zip
├── starter_kit/
│   ├── inference.py
│   ├── train.py
│   ├── requirements.txt
│   ├── sample_input/
│   │   ├── sample_features.csv
│   │   ├── sample.csv
│   │   └── sample_structures.zip
│   └── example_output.csv
└── environment/
    ├── supported_packages.txt
    └── README.md
```

실제 평가 행을 샘플로 복사하지 않습니다. 공개 학습 데이터에서 뽑은 소량 샘플 또는 형식을 검증한 합성 예제를 사용하고, 세 입력 파일과 예제 출력의 ID가 서로 대응해야 합니다.

## 2. 각 파일·폴더를 포함하는 이유

| 파일·폴더 | 포함 이유와 범위 |
| --- | --- |
| `README.md` | 두 다운로드의 구성, 버전, 압축 해제 위치, 학습→샘플 추론→제출 순서와 제출 ZIP 규격을 한 곳에서 안내합니다. |
| `data/` | 참가자에게 공개하는 학습 자료를 코드·환경 안내와 구분합니다. |
| `data/README.md` | 대회 전 발표자료의 내용만 포함합니다. 발표자료에 없는 설명은 추가하지 않습니다. |
| `data/train.csv` | 학습용 `id`, 관측 `sequence`, 정답 label 등 확정된 스키마를 제공합니다. **학습 정답은 공개 대상**입니다. |
| `data/train_features.csv` | `id`와 기본 특징 31개를 제공해 구조 전처리 없이도 베이스라인 학습이 가능하게 합니다. |
| `data/train_structures.zip` | 선택적으로 활용할 학습용 Cα 좌표·마스크·잔기 위치 등의 NPZ 구조를 제공합니다. 사전 계산한 그래프 edge는 권장안에 포함하지 않습니다. |
| `starter_kit/` | 공개 예제로 학습·추론·출력 형식을 연습하도록 최소 코드를 묶습니다. 참가자가 제출하는 ZIP 자체와는 구분합니다. |
| `starter_kit/inference.py` | 저장된 모델·전처리 객체를 로드하고 입력으로부터 `id,label` 예측을 생성하는 서버 인터페이스 예제입니다. 평가 중 재학습하지 않습니다. |
| `starter_kit/train.py` | 참가자 로컬에서 베이스라인을 학습·저장하고 재현하는 예제입니다. 현재 제출 규격에서도 필수지만 채점 때 실행하지 않습니다. |
| `starter_kit/requirements.txt` | 예제 코드의 사용 패키지 명세입니다. 참가자는 자신의 모델에 맞게 작성하되 공식 지원 환경과 일치시킵니다. 서버에서 이를 읽어 패키지를 설치하지 않습니다. |
| `starter_kit/sample_input/` | 실제 평가 입력과 같은 형식을 가진 **공개 실행 점검용 입력**만 모읍니다. |
| `sample_input/sample_features.csv` | 특징 CSV 경로를 받는 `--input` 인자와 31개 특징 처리 흐름을 점검합니다. |
| `sample_input/sample.csv` | 공개 샘플의 `id,sequence`를 제공해 서열을 사용하는 모델도 입력을 시험할 수 있게 합니다. 평가 입력처럼 정답 열은 넣지 않습니다. |
| `sample_input/sample_structures.zip` | 샘플 서열·특징에 대응하는 구조를 제공해 구조를 사용하는 추론을 점검합니다. |
| `starter_kit/example_output.csv` | UTF-8 CSV의 `id,label` 컬럼 순서와 label 문자열 형식을 보여 줍니다. 공개 샘플 ID만 사용하며 숨긴 평가 정답·예측은 포함하지 않습니다. 점수 보장 파일이 아닙니다. |
| `environment/` | 채점 환경과 참가자 코드의 패키지 명세를 구분해 안내합니다. |
| `environment/supported_packages.txt` | 운영진이 검증한 고정 evaluator 환경의 공식 지원 패키지와 정확한 버전을 공개합니다. |
| `environment/README.md` | 검증한 Python 버전, OS·CPU/GPU 조건, 이미지 식별자, 샘플 실행법, 네트워크·설치 제한을 설명합니다. |

학습 후 생성하는 `model/`은 참가자 제출에 필요합니다. Starter Kit의 초기 트리에는 학습된 모델을 필수 배포물로 넣지 않고, `train.py` 실행으로 생성하도록 안내합니다. 제출 ZIP에서는 `inference.py`, `train.py`, `requirements.txt`, `model/`이 **최상위**에 있어야 합니다. 다운로드 폴더를 그대로 제출하면 안 됩니다.

## 3. 참가자 배포본에 절대 포함하면 안 되는 파일·정보

아래 금지는 ZIP 내부, 공개 다운로드 경로, 프런트엔드 빌드 산출물, API 메타데이터, 코드·노트북 출력·로그 등 모든 공개 경로에 적용합니다. 파일명을 바꾸거나 다른 파일에 합쳐도 금지 대상입니다.

| 금지 대상 | 예시와 이유 |
| --- | --- |
| 실제 평가 입력 | `test.csv`, `test_features.csv`, `test_structures.zip`. 평가 서열·특징·구조는 운영 서버 안에서만 사용합니다. |
| 숨긴 평가 정답 / ground truth | `test_labels.csv`, `answer.csv`, `ground_truth.csv`, `private/labels.csv` 등. 학습용 `train.csv`의 label과 공개 샘플 예제 출력은 이 금지 대상이 아닙니다. |
| 평가 Public/Private 분할 | `public_private_split.*`, partition 컬럼, ID별 분할 매핑, 분할을 재구성할 수 있는 설정·seed. 공개된 평가 방식 설명과 구분합니다. |
| 평가 ID와 원본 식별자 매핑 | `evaluation_ids.*`, 실제 평가 ID 목록, 원본 CATH/PDB/domain ID 연결표. 공개 학습·샘플 ID는 사용할 수 있습니다. |
| scoring 내부 파일·결과 | `scoring.*`, worker용 채점 설정·스크립트·중간 결과, 숨긴 예측·Private 점수, 실제 평가 ID나 값이 포함된 검증기 상세 결과 및 추론 로그. 공개 지표(Macro F1)·출력 규격 안내는 제공합니다. |
| 운영 전용 자료·비밀정보 | `.env`, 계정 시트, 비밀번호·토큰, DB 백업, 관리자 로그, 다른 팀의 제출물·모델, 원본 데이터 캐시와 정제·분할 작업 디렉터리. |

파일명 차단만으로는 부족합니다. 명시적으로 허용한 파일만 깨끗한 배포 디렉터리에 복사하고, 중첩된 `train_structures.zip`·`sample_structures.zip`까지 검사합니다. CSV 컬럼·ID, NPZ 키, ZIP 내부 경로, README와 코드의 하드코딩 값, 노트북 출력에 숨긴 평가 자료나 원본 식별자 매핑이 없는지 확인합니다. 실제 평가 파일을 ‘예제’라고 이름만 바꿔 배포해서는 안 됩니다.

## 4. 서버의 test 명칭과 Starter Kit의 sample 명칭 분리

현재 [추론 계약](api-contract.md#추론-실행-계약-임시-데이터평가팀과-확정-필요)의 서버 내부 이름을 유지합니다.

```text
/input/
├── test_features.csv    # id + 학습 특징과 같은 31개 특징
├── test.csv             # id,sequence
└── test_structures.zip  # 학습 구조와 같은 NPZ 형식
```

```bash
python inference.py --input /input/test_features.csv --output /output/predictions.csv
```

이 세 파일만 읽기 전용으로 참가자 추론 컨테이너에 연결합니다. 정답과 Public/Private 분할은 컨테이너 밖 worker만 읽으며, 정답이 있는 `data/private` 디렉터리를 `/input`으로 연결하지 않습니다. ‘서버 내부’라는 말은 이 입력 파일명을 문서에서 설명할 수 없다는 뜻이 아니라, **실제 평가 파일과 내용은 내려주지 않는다**는 뜻입니다.

Starter Kit에서는 `sample_features.csv`, `sample.csv`, `sample_structures.zip`을 사용합니다. 실제 test를 받았다는 오해를 막고, 운영 배포 스크립트가 공개 예제와 비공개 평가 파일을 혼동할 가능성을 줄입니다. 이름만 다르고 입력 스키마는 같아야 합니다. 권장 로컬 실행 예시는 다음과 같습니다(`starter_kit/`에서 실행, 학습된 `model/` 필요).

```bash
python inference.py --input sample_input/sample_features.csv --output sample_predictions.csv
```

**확정 전 체크사항:** 현재 계약은 `Path(args.input).parent`에서 `test.csv`, `test_structures.zip`을 찾습니다. 특징만 사용하는 예제는 위 로컬 명령으로 점검할 수 있지만, 서열·구조를 쓰는 코드는 그대로 두면 sample 명칭을 찾지 못합니다. Starter Kit 구현 시 명시적인 입력 이름 매핑 등으로 두 입력 모드를 지원하고, 서버의 기존 명령을 유지한 상태에서 sample/test 양쪽을 검증해야 합니다. 이 문서는 새 인자나 자동 탐색 동작을 확정하지 않습니다.

## 5. supported_packages.txt 공개 원칙

`supported_packages.txt`는 참가자가 저장된 모델을 실제 채점 환경에서 불러와 추론할 수 있도록 제공하는 **공식 지원 명세**입니다. 참가자 로컬의 `pip freeze` 전체, 웹/API 서버의 의존성, 학습 전용 도구 목록을 그대로 옮기는 파일이 아닙니다. `requirements.txt`는 제출 코드의 사용 명세이고, `supported_packages.txt`는 운영진이 보장하는 채점 환경의 명세입니다.

**실제 대회에 사용할 evaluator Docker 이미지에서 검증 완료한 패키지와 버전만 공개합니다.** 필요한 패키지라는 의견이나 requirements에 적힌 버전만으로 공식 지원이라고 표시하지 않습니다. 공개 전 다음을 완료합니다.

1. 데이터·평가팀이 추론에 필요한 패키지 목록을 합의하고 실제 evaluator 이미지를 빌드합니다.
2. 그 이미지 안에서 Python의 정확한 버전과 설치된 패키지 버전을 확인하고, 지원 패키지 import 및 저장 모델 로드·예측을 검증합니다. 추가 ML/DL 라이브러리는 해당 라이브러리의 모델로 점검합니다.
3. 운영과 같은 네트워크 차단·읽기 전용·사용자·자원 제한으로 Starter Kit 추론을 실행하고 `id,label` 출력을 검증합니다. 실제 평가 입력을 사용하는 확인은 운영진 내부에서만 수행합니다.
4. 검증한 이미지 태그와 digest, 검증일·결과를 기록하고 그 환경과 일치하는 명세를 배포합니다. 이미지 변경 시 재검증하고 명세 버전도 갱신합니다.

하위 의존성은 이미지에 포함될 수 있으나 참가자에게 직접 사용을 보장할 패키지와 구분합니다. 재현용 전체 설치 목록은 별도로 기록하되, 공식 지원 표기는 검증 근거가 있는 항목만 합니다. 서버는 인터넷 접속·패키지 설치·학습을 허용하지 않으며, 지원 목록에 없는 패키지를 제출 `requirements.txt`에 추가해도 설치되지 않습니다.

**확정 전 체크사항:** [evaluator Dockerfile](../apps/evaluator/Dockerfile)과 [requirements](../apps/evaluator/requirements.txt)는 초안으로 표시되어 있습니다. `FROM python:3.12-slim`은 Python 패치 버전을 고정하지 않으므로 특정 패치 버전을 검증 없이 공지하면 안 됩니다. [검증 기록](validation.md)의 데모 격리 평가 성공은 현재 전체 패키지·실제 모델의 검증 완료 증거가 아닙니다. 이 문서는 패키지나 버전을 공식 지원값으로 새로 확정하지 않습니다.

## 6. 권장 다운로드: ZIP 두 개

| 다운로드 | ZIP 내부 경로 | 나누는 이유 |
| --- | --- | --- |
| `admin2026_data.zip` | `ADMIN_2026_RELEASE/data/README.md`, `data/train.csv`, `data/train_features.csv`, `data/train_structures.zip` (모두 같은 루트 아래) | 큰 학습 자료를 한 번에 받고, 안내·코드 수정 때 데이터를 다시 받지 않아도 됩니다. |
| `admin2026_starter_kit.zip` | `ADMIN_2026_RELEASE/README.md`, `starter_kit/` 전체, `environment/` 전체 (모두 같은 루트 아래) | 작은 코드·공개 샘플·환경 안내를 독립적으로 갱신하고, 참가자가 실행 계약을 쉽게 점검합니다. |

두 ZIP을 같은 디렉터리에 풀면 1절의 트리가 완성되도록 제작합니다. 루트 README에 호환되는 배포 버전·ZIP 이름·SHA-256 확인 방법을 안내합니다. `data/README.md`에는 대회 전 발표자료의 내용만 포함합니다. Starter Kit에는 전체 학습 데이터나 실제 평가 입력을 중복해서 넣지 않습니다.

이 두 ZIP은 **참가자가 받는 배포물**이며, 참가자가 서버에 올리는 모델 제출 ZIP과 다릅니다. 데이터가 든 두 배포물의 공개 시점과 권한은 현재 관리자 승인·대회 기간 조건을 존중해 확정합니다. ZIP 파일 제작, 다운로드 API·화면 교체, 공개 승인은 이 문서 추가만으로 수행되지 않습니다.

## 7. 확정 전 체크사항

| 항목 | 현재 문서·구현과의 차이 | 확정할 내용 |
| --- | --- | --- |
| 학습 내부 검증 분할 | [참가자 안내](competition.md)는 학습 내부 검증 분할 제공을 안내하고, [PUBLIC_FILES](../apps/api/app/dataset.py)와 [DataPanel](../apps/web/app/components/DataPanel.tsx)은 `validation_split.csv`를 제공합니다. 최소 트리의 학습 자료는 요청한 세 파일입니다. | `validation_split.csv`를 학습 전용 추가 파일로 유지할지, 동등한 분할 정보를 어떤 방식으로 제공할지 결정합니다. 기존 안내를 무시하고 삭제하지 않습니다. 학습 내부 분할과 **금지 대상인 평가 Public/Private 분할**은 다릅니다. |
| 예제 묶음 | [API 계약](api-contract.md)은 `example_io.zip`을 임시 이름으로 가정하고 현재 다운로드 목록에도 있습니다. | `admin2026_starter_kit.zip`의 `sample_input/`과 `example_output.csv`로 통합할지, 기존 경로 호환이 필요한지 결정합니다. |
| sample/test 입력 이름 | 현재 계약·[Docker 평가기](../apps/api/app/evaluators/docker.py)는 서버의 `test.*` 이름을 사용합니다. | 4절에 따라 서열·구조 입력 이름 매핑을 합의하고 동일 코드의 로컬 샘플 추론과 서버 추론을 확인합니다. |
| 두 ZIP 다운로드 | 현재 API·화면은 세 학습 파일, 검증 분할, 예제를 개별 다운로드합니다. 두 ZIP 경로는 아직 없습니다. | 데이터팀의 ZIP 생성과 웹팀의 허용 목록·메타데이터·버전/해시·승인/잠금·화면·API 계약을 함께 갱신합니다. |
| 코드 전용 사전 배포 | [public 라우터](../apps/api/app/routers/public.py)의 `/resources/baseline`은 `baseline_code.zip`을 별도로 제공하고, 시작 전 일반 참가자에게는 차단합니다. [DataPanel](../apps/web/app/components/DataPanel.tsx)의 ‘미리 받기’ 표현 및 [과거 검증 기록](validation.md)의 사전 공개 설명과 차이가 있습니다. | 코드 전용 묶음을 두 다운로드에 통합할지, 별도 예외로 유지할지와 공개 시점을 정하고 안내를 맞춥니다. sample이 든 Starter Kit을 자동으로 사전 공개하지 않습니다. |
| 패키지·Python 버전 | evaluator 명세는 초안이고 Python 패치 버전은 고정되지 않았습니다. | 실제 이미지 빌드·모델 추론 검증 근거를 확보한 후 `supported_packages.txt`를 확정합니다. API 컨테이너 테스트 통과를 evaluator 검증으로 대신하지 않습니다. |
| 구조·샘플·출력 스키마 | 계약은 구조 NPZ와 특징 31개를 사용하며 예측은 `id,label`, label은 문자열입니다. | 학습·샘플·서버 입력의 컬럼·NPZ 키·ID 대응을 데이터팀과 확인하고, 소량 공개 예제로 모델 로드부터 출력 검증까지 실행합니다. |

배포 확정은 위 차이를 해소하고, 허용 목록대로 만든 두 ZIP에 비공개 자료가 없는지 확인한 뒤 진행합니다. 공개 데이터 파일을 Git에 올리지 않는다는 README의 원칙도 유지합니다.
