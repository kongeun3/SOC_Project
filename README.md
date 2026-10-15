# SOC · 도로 포장 열응력 진단

단일 Python 프로젝트에서 웹 화면, SAM2 균열 검출, FEM 열응력 계산, 로컬 AI 진단을 실행합니다.

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
```

- **SERVER_URL**: 화면 접속 주소이자 서버 바인딩 주소. 예: `http://localhost:8080`.
- **OLLAMA_BASE / OLLAMA_MODEL**: 로컬 AI 서비스 주소와 모델 이름.
- **OLLAMA_AUTO_START**: 로컬 Ollama가 꺼져 있으면 자동으로 시작할지 여부.
- **FLET_SECRET_KEY**: 파일 업로드 URL 서명 키. 이 프로젝트의 `.env`에는 무작위 키를 생성해 두었습니다.

`.env`는 Git에 포함되지 않습니다. 다른 PC에서는 `.env.example`을 `.env`로 복사하고 키를 새로 생성하세요.
이미 설정된 운영체제 환경 변수는 `.env`보다 우선합니다.

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
│  ├─ uploads/       업로드 원본
│  ├─ web_uploads/   브라우저 업로드 파일
│  ├─ images/        최근 분석 그래프
│  ├─ reports/       분석별 JSON · 최근 AI 진단 · 검증 기록
│  ├─ logs/          server.log 등 실행 로그
│  └─ fem/           명령행 FEM 분석 결과
└─ past/             기존 프로젝트·실행 파일·결과·참고 자료
```

`SOC_SAM2` 원본은 `past/SOC_SAM2`에 보관했습니다. 실행 코드는 `past`를 참조하지 않습니다.
그전에 보관했던 학습 자료는 `past/SOC_SAM2_training`에 있습니다.
BAT 파일과 이전 실행 도구는 `past/launchers_v2`에 보관했으며, PS1 파일은 삭제했습니다.

## 사용과 결과 확인

화면에서 `test/test.jpg` 또는 온도 CSV를 선택한 다음 **분석 시작**을 누릅니다.
분석 JSON은 실행 시각별로 저장됩니다. `result/images`와 `latest_diagnosis.txt`는 최신 결과로 갱신됩니다.
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

`python main.py`로 서버를 실행한 상태에서 화면을 점검하려면:

```bat
python test/check_web.py
python test/check_web.py --ai
python test/check_upload.py
```

HTML 버전은 `python main2.py`로 실행하고 `python test/check_html.py`로 점검합니다.
Edge 또는 Chrome을 화면 없는 모드로 열어 실제 파일 업로드·SAM2/FEM 분석·JSON 다운로드·모바일 배치를 확인합니다.
이 점검에서 AI 진단과 채팅 응답은 테스트 데이터로 대체하며, 실제 AI 모델을 다시 호출하지 않습니다.
화면 캡처는 `result/browser`, 검증 결과는 `result/reports/html_ui_check.json`에 저장됩니다.

점검은 실제 분석을 실행하므로 최신 결과 파일이 갱신됩니다.
CSV 일괄 분석은 `python -m core.thermal_stress_fem_system past/csv --all`로 실행할 수 있습니다.
