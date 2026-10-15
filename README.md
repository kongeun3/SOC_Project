# 길바닥연구소 - 도로 포장 열응력 계산 프로그램

단일 Python 프로젝트에서 웹 화면, SAM2 균열 검출, FEM 열응력 계산, 로컬 AI 진단을 실행합니다.

## 설치 방법 (Windows · Anaconda)

### 1. 프로젝트 다운로드

Anaconda 또는 Miniconda와 Git을 설치하고 **Anaconda Prompt**에서 실행합니다.
GitHub에서 ZIP으로 다운로드했다면 압축을 풀고 해당 폴더로 이동해도 됩니다.

```bat
git clone https://github.com/kongeun3/SOC_Project.git
cd SOC_Project
```

이후 명령은 `environment.yml`과 `main2.py`가 있는 프로젝트 루트에서 실행합니다.

### 2. SOC 가상환경 생성

```bat
conda env create -f environment.yml
conda activate SOC
```

`environment.yml`은 Python 3.10, PyTorch 2.5.1, torchvision 0.20.1,
CUDA 12.4용 패키지와 `requirements.txt`의 실행 패키지를 함께 설치합니다.
이 환경 설정은 NVIDIA GPU 사용을 기준으로 합니다. GPU를 사용하려면 호환되는
NVIDIA 드라이버가 필요하며, CUDA Toolkit을 별도로 설치할 필요는 없습니다.

설치 후 GPU 인식 여부를 확인합니다.

```bat
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

`CUDA: False`이면 현재 코드는 CPU로 분석합니다. GPU보다 오래 걸릴 수 있습니다.
이미 `SOC` 환경이 설치된 PC에서는 환경 생성 대신 `conda activate SOC`만 실행하세요.

### 3. weights 다운로드

학습 가중치는 GitHub 저장소와 별도로 아래 링크에서 다운로드하세요.

**[Google Drive에서 weights 다운로드](https://drive.google.com/drive/folders/1slGvVoo3ThN5g39BHVoNQ1Hp5ctnylAZ?usp=sharing)**

압축 파일로 다운로드했다면 압축을 풀고, 다음 세 파일이 프로젝트 루트의
`weights/` 바로 아래에 오도록 배치합니다. `weights/weights/`처럼 중첩되지 않도록 확인하세요.

```text
SOC_Project/
├─ main2.py
└─ weights/
   ├─ checkpoint_8.pt
   ├─ prompt_tuned_ep20.pt
   └─ sam2.1_hiera_b+.yaml
```

위 파일 이름은 분석 코드에서 사용하므로 변경하지 마세요.

### 4. .env 설정

처음 설치하는 PC에서는 예제 설정을 복사합니다. 기존 `.env`가 있다면 유지하세요.

```bat
copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

출력된 무작위 문자열을 `.env`의 `FLET_SECRET_KEY` 값에 넣습니다.
기본 접속 주소는 `SERVER_URL=http://127.0.0.1:8000`이며, 상세 설정은 아래를 참고하세요.
`.env`에는 PC별 설정을 저장하며 GitHub에 업로드하지 않습니다.

### 5. AI 진단용 Ollama 준비

AI 진단 보고서와 추가 질문을 사용하려면 Ollama를 설치하고 다음 모델을 다운로드합니다.

```bat
ollama pull exaone3.5:7.8b
```

Ollama 설치 후 명령을 찾지 못하면 Anaconda Prompt를 새로 여세요.
기본 설정에서는 프로젝트 실행 시 로컬 Ollama 서버를 자동으로 시작합니다.
Ollama를 별도로 실행하려면 다른 프롬프트에서 `ollama serve`를 실행하세요.
AI 서비스를 준비하지 않아도 균열 검출과 FEM 분석은 사용할 수 있으며,
이 경우 화면의 **분석 후 AI 진단 자동 생성**을 해제하세요.

### 6. 웹 화면 실행

```bat
conda activate SOC
python main2.py
```

서버 준비가 끝나면 브라우저에서 **http://127.0.0.1:8000**으로 접속합니다.
파일을 선택하고 물성 입력을 확인한 뒤 **분석 시작**을 누릅니다.
분석 결과와 로그는 `result/` 아래에 저장되며, 서버는 **Ctrl+C**로 종료합니다.
기존 Flet 화면을 사용하려면 `python main2.py` 대신 `python main.py`를 실행하세요.
두 서버를 같은 주소와 포트로 동시에 실행할 수는 없습니다.

## 실행

Anaconda Prompt에서 프로젝트 폴더로 이동한 뒤 실행하세요.

```bat
conda activate SOC
cd /d C:\Users\rhd30\Desktop\Python\SOC_Project
python main.py
```

서버 시작 메시지가 나오면 브라우저에서 **http://127.0.0.1:8000**으로 접속합니다.
화면과 분석 API가 같은 서버·포트를 사용하며, **Ctrl+C**로 종료합니다.
첫 시작에는 모델을 불러오는 시간이 필요합니다.

### 개선 UI 실행

기존 화면은 `python main.py`, 별도 개선 화면은 다음 명령으로 실행합니다.

```bat
python main2.py
```

`main2.py`는 **`web/index.html`**을 제공합니다. Pinegrow 등 로컬 HTML 파일을 지원하는
웹디자이너에서 이 파일을 열어 배치·글자·색상·간격을 직접 수정할 수 있습니다.

| 파일 | 역할 |
| --- | --- |
| `web/index.html` | 화면 구성과 문구 · 웹디자이너에서 여는 파일 |
| `web/style.css` | 색상, 글꼴, 간격, 반응형 배치 |
| `web/app.js` | 업로드·분석·AI 진단·질의응답 API 연결 |

HTML·CSS를 저장하고 브라우저를 새로고침하면 변경 사항이 반영됩니다. 디자인 변경에는 서버 재시작이 필요하지 않습니다.
HTML 파일을 서버 없이 직접 열면 디자인 미리보기로 동작하며 실제 분석 버튼은 비활성화됩니다.
편집 시 유지할 요소 이름과 연결 규칙은 [웹 화면 편집 안내](web/README.md)를 참고하세요.
두 버전 모두 `.env`의 같은 서버 주소를 사용하므로 실행 중인 버전을 종료한 뒤 다른 버전을 시작하세요.
개선 버전의 로그는 `result/logs/server2.log`에 저장됩니다.
이전 Flet 개선 화면은 `past/ui2_flet`에 보관했습니다.

## .env 설정

프로젝트 루트의 `.env`를 수정한 후 서버를 재시작하세요.

```dotenv
SERVER_URL=http://127.0.0.1:8000
OLLAMA_BASE=http://127.0.0.1:11434
OLLAMA_MODEL=exaone3.5:7.8b
OLLAMA_AUTO_START=true
FLET_SECRET_KEY=프로젝트에_생성된_값_유지
JOB_QUEUE_CAPACITY=32
SESSION_TTL_SECONDS=86400
MAX_SESSIONS=256
MAX_PENDING_PER_SESSION=4
MAX_JOBS_PER_SESSION=128
MAX_UPLOADS_PER_SESSION=64
MAX_UPLOAD_MB=32
```

- **SERVER_URL**: 화면 접속 주소이자 서버 바인딩 주소. 예: `http://localhost:8080`.
- **OLLAMA_BASE / OLLAMA_MODEL**: 로컬 AI 서비스 주소와 모델 이름.
- **OLLAMA_AUTO_START**: 로컬 Ollama가 꺼져 있으면 자동으로 시작할지 여부.
- **FLET_SECRET_KEY**: 파일 업로드 URL 서명 키. 이 프로젝트의 `.env`에는 무작위 키를 생성해 두었습니다.
- **JOB_QUEUE_CAPACITY**: 서버 전체 작업 대기열 용량. 한도를 넘으면 요청을 거절하고 나중에 다시 시도하도록 안내합니다.
- **SESSION_TTL_SECONDS**: 활동이 없는 세션의 유효 시간(초). 기본값은 24시간이며, 실행 중이거나 대기 중인 작업이 있는 세션은 유지됩니다.
- **MAX_SESSIONS / MAX_PENDING_PER_SESSION**: 서버의 최대 세션 수 / 세션별 최대 대기·실행 작업 수.
- **MAX_JOBS_PER_SESSION / MAX_UPLOADS_PER_SESSION**: 세션별 최대 작업 수 / 업로드 수.
- **MAX_UPLOAD_MB**: 파일 하나의 최대 업로드 용량(MB).

`.env`는 Git에 포함되지 않습니다. 다른 PC에서는 `.env.example`을 `.env`로 복사하고 키를 새로 생성하세요.
이미 설정된 운영체제 환경 변수는 `.env`보다 우선합니다.

## 여러 사용자 동시 사용

웹 화면과 기존 Flet 화면 모두 사용자별 API 세션을 사용합니다. 업로드마다 파일 ID를,
분석마다 분석 ID를 발급하므로 파일 이름이 같아도 원본·그래프·AI 진단·추가 질문이 섞이지 않습니다.
분석 결과와 이미지 조회에도 해당 세션이 필요합니다.

여러 사용자가 동시에 접속하고 파일을 올리거나 결과를 조회할 수 있습니다.
SAM2·FEM·그래프 생성과 Ollama 진단·채팅은 **하나의 작업 대기열에서 순서대로 처리**합니다.
이 PC의 GPU 메모리와 공유 모델을 보호하기 위한 구성으로, 여러 분석을 GPU에서 동시에 계산하는 방식은 아닙니다.
먼저 제출한 작업을 처리하는 동안 다른 사용자는 화면에서 대기 순서를 확인할 수 있습니다.
한 사람의 분석이 끝나면 다음 작업이 실행되며, 자동 AI 진단은 해당 분석 결과를 기준으로 별도 작업으로 제출됩니다.

`python main2.py` 또는 `python main.py`로 **서버 프로세스 하나만** 실행하세요.
세션과 대기열을 프로세스 메모리에서 관리하므로 `uvicorn --workers`를 늘리거나
여러 서버 프로세스를 같은 결과 폴더에 연결하는 구성은 지원하지 않습니다.
기본 주소 `127.0.0.1`은 이 PC에서만 접속할 수 있습니다. 같은 네트워크의 다른 PC에서도
사용하려면 `.env`의 `SERVER_URL=http://0.0.0.0:8000`으로 실행하고 서버 PC의 IP 주소로 접속하세요.

서버를 재시작하거나 세션이 만료되면 파일을 다시 업로드해야 합니다.
이전에 저장한 결과 파일은 `result/jobs/`에 남지만, 이전 세션 ID로 웹에서 다시 조회할 수는 없습니다.
대기열이 가득 차면 자동 재제출하지 않으므로 잠시 후 버튼을 다시 눌러주세요.

## 폴더 구조

```text
SOC_Project/
├─ main.py           단일 웹 서버 실행 진입점
├─ main2.py          편집 가능한 HTML 웹 화면 실행
├─ api.py            업로드 · SAM2/FEM 분석 · AI 진단 API
├─ app.py            Flet 대시보드
├─ web/              웹디자이너에서 편집할 HTML · CSS · JavaScript
├─ config.py         .env 로드 · 주소 · 저장 경로 설정
├─ .env              이 PC의 실행 설정
├─ core/             온도 처리 · FEM · 균열 검출 · 마스크 후처리
├─ sam2/             통합된 SAM2 Python 패키지 (원본 라이선스 포함)
├─ weights/          모델 설정과 학습 가중치
├─ test/
│  ├─ test.jpg       uploaded_1778244646230.jpg의 복사본
│  ├─ check_runtime.py  모델·분석 API 점검
│  └─ check_web.py      실행 중인 웹 화면 점검
├─ result/
│  ├─ jobs/          세션별 업로드 · 작업별 결과/그래프/AI 진단
│  │  └─ <저장 ID>/
│  │     ├─ uploads/           업로드 ID별 원본
│  │     └─ <작업 ID>/         job.json · result.json · images/ 등
│  ├─ web_uploads/   Flet 브라우저 업로드 임시 전달 파일(고유 파일명)
│  ├─ reports/       점검 스크립트의 검증 기록
│  ├─ logs/          server.log 등 실행 로그
│  └─ fem/           명령행 FEM 분석 결과
└─ past/             기존 프로젝트·실행 파일·결과·참고 자료
```

`SOC_SAM2` 원본은 `past/SOC_SAM2`에 보관했습니다. 실행 코드는 `past`를 참조하지 않습니다.
그전에 보관했던 학습 자료는 `past/SOC_SAM2_training`에 있습니다.
BAT 파일과 이전 실행 도구는 `past/launchers_v2`에 보관했으며, PS1 파일은 삭제했습니다.

## 사용과 결과 확인

화면에서 `test/test.jpg` 또는 온도 CSV를 선택한 다음 **분석 시작**을 누릅니다.
분석 JSON과 그림은 `result/jobs/<저장 ID>/<작업 ID>/result.json`, `images/`에 저장됩니다.
AI 작업의 `diagnosis.txt`와 `chat.json`도 각 작업 폴더에 저장합니다. 다른 사용자의 결과를 덮어쓰지 않습니다.
API 상태는 설정한 주소의 `/api/`, API 문서는 `/api/docs`에서 확인할 수 있습니다.
실행 로그는 `result/logs/server.log`에 저장됩니다.

이 PC의 RTX 2050(4GB)에서 로컬 AI 모델은 CPU와 GPU를 함께 사용하며, 진단 생성에는 수 분이 걸릴 수 있습니다.

## 환경과 점검

Anaconda `SOC` 환경에 실행 패키지와 GPU용 PyTorch가 설치되어 있습니다.
환경 재생성은 `environment.yml`, Python 패키지 버전은 `requirements.txt`를 참고하세요.

```bat
python -m pip install -r requirements.txt
```

서버를 종료한 상태에서 이미지·CSV 분석을 점검하려면:

```bat
python test/check_runtime.py
```

동시 요청과 사용자별 결과 분리를 점검하려면:

```bat
python -X utf8 test/check_concurrency.py
```

이 검사는 모델 계산과 Ollama 응답을 모의 처리하고, 실제 API·작업 대기열을 사용해
두 사용자의 동시 요청, 파일·결과 접근 권한, 대기 순서, 실패 후 복구를 검증합니다.

`python main.py`로 서버를 실행한 상태에서 화면을 점검하려면:

```bat
python test/check_web.py
python test/check_web.py --ai
python test/check_upload.py
```

Flet 점검은 페이지별 파일 업로드부터 분석 작업과 보호된 결과 이미지까지 확인합니다.
`check_upload.py`는 두 사용자가 같은 파일 이름으로 동시에 업로드해도 충돌하지 않는지 검사합니다.
`check_web.py --ai`는 해당 페이지에 새 AI 진단문이 표시되었는지도 확인합니다.

HTML 버전은 `python main2.py`로 실행하고 `python test/check_html.py`로 점검합니다.
Edge 또는 Chrome을 화면 없는 모드로 열어 실제 파일 업로드·SAM2/FEM 분석·JSON 다운로드·모바일 배치를 확인합니다.
이 점검에서 AI 진단과 채팅 응답은 테스트 데이터로 대체하며, 실제 AI 모델을 다시 호출하지 않습니다.
화면 캡처는 `result/browser`, 검증 결과는 `result/reports/html_ui_check.json`에 저장됩니다.

점검은 실제 분석을 실행하며, 실행한 세션·작업에 대한 결과 파일이 새로 저장됩니다.
CSV 일괄 분석은 `python -m core.thermal_stress_fem_system past/csv --all`로 실행할 수 있습니다.
