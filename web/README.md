# 웹디자이너로 화면 편집하기

이 폴더는 빌드 과정이 없는 일반 HTML·CSS·JavaScript 웹 화면입니다.
Python 실행 진입점은 프로젝트 루트의 `main2.py`이며, 기존 `main.py`는 Flet 화면을 유지합니다.

## 편집과 실행

1. Pinegrow 같은 로컬 HTML 편집 도구에서 **`web` 폴더를 프로젝트로 열고 `index.html`을 선택**합니다.
2. 글자, 색상, 여백, 크기, 카드 배치 등을 수정하고 저장합니다.
3. Anaconda Prompt에서 `conda activate SOC` 후 프로젝트 루트에서 `python main2.py`를 실행합니다.
4. `.env`의 `SERVER_URL` 주소로 접속합니다. 기본 주소는 `http://127.0.0.1:8000`입니다.
5. 편집 후 브라우저를 새로고침하면 새 디자인이 표시됩니다. HTML·CSS 변경에는 서버 재시작이 필요하지 않습니다.

파일을 직접 열어도 화면 디자인을 볼 수 있습니다. 이 경우 분석 기능은 비활성화됩니다.
실제 파일 업로드와 결과 확인은 Python 서버의 주소로 접속해서 진행하세요.

### Zaemit 저장 호환성

Zaemit 0.0.28은 `./style.css`처럼 `./`가 붙은 참조를 읽을 때와 저장할 때의 파일 이름을 다르게 다룹니다.
이 프로젝트는 이를 피하도록 `href="style.css"`, `src="app.js"`로 연결합니다. 앞에 `./`를 붙이지 마세요.
Zaemit 미리보기에서는 분석 API를 호출하지 않도록 처리했습니다.
분석 동작은 `python main2.py`로 연 서버에서 확인하세요.

경로를 바꾸거나 외부에서 복구한 뒤에는 기존 Zaemit 편집 탭을 저장하지 말고 닫은 다음 HTML 파일을 다시 여세요.
기존 탭은 변경 전 파일 이름과 편집 내용을 메모리에 유지할 수 있습니다.

## 세 파일의 역할

- **index.html**: 편집할 화면의 실제 요소와 문구가 있습니다. Python이나 템플릿 문법이 포함되어 있지 않습니다.
- **style.css**: 색상·간격·모서리·글꼴과 반응형 배치가 있습니다. 맨 위의 `:root`에서 공통 디자인 값을 바꿀 수 있습니다.
- **app.js**: `/api/upload`, `/api/analyze`, `/api/diagnose`, `/api/chat`과 연결합니다. 외부 JavaScript 라이브러리나 CDN이 필요하지 않습니다.

## 수정할 때 유지할 연결

문구와 스타일은 자유롭게 바꿀 수 있습니다. 기능 연결에 사용되는 **id, input name, data-result-image 속성은 유지**하세요.
같은 id를 가진 요소를 복제하지 마세요. 기존 요소를 이동해 레이아웃을 바꾸는 것은 가능합니다.

| 화면 요소 | 연결 이름 |
| --- | --- |
| 파일 선택 · 업로드 영역 | `fileInput`, `dropZone`, `selectedFile` |
| 분석 폼 · 실행 버튼 | `analysisForm`, `inputSettings`, `analyzeButton` |
| 촬영일 · 시나리오 · 해상도 | `captureDate`, `scenario`, `meshSize` |
| 상세 물성 설정 | `customProps`, `customFields`, `elasticModulus`, `poissonRatio`, `thermalExpansion`, `tensileStrength` |
| AI 진단 | `autoDiagnose`, `diagnoseButton`, `diagnosisContent` |
| 결과 다운로드 | `downloadButton` |
| 채팅 | `chatForm`, `chatInput`, `chatButton`, `chatMessages` |

그 밖의 결과 표시 요소 id도 `app.js`에서 찾아 값을 넣는 데 사용합니다.
`analysisForm` 안의 입력 요소와 `chatForm`은 각각 현재 폼 안에 유지하세요.
`.chart-placeholder`, `.image-empty`, `.chat-empty`, `.chat-message` 클래스는 표시 상태에도 사용됩니다.
결과 이미지와 그 안내 문구는 같은 부모 요소 안에 두세요.

결과 이미지의 `data-result-image` 값은 서버가 저장하는 파일 이름입니다.
`gauge.png`, `donut.png`, `pipeline_result.png`, `risk_overlay.png`, `fem_results.png`를 사용합니다.
초기 화면의 `—` 표시는 분석 전 빈 값이며, 분석이 끝나면 실제 값으로 바뀝니다.

## 동작 확인

- `test/test.jpg`를 선택하고 분석하면 SAM2·FEM 결과가 표시됩니다.
- AI 진단 자동 생성을 해제하면 FEM 결과만 먼저 확인할 수 있습니다. 이후 **AI 진단 생성**을 누를 수 있습니다.
- **결과 JSON 다운로드**는 현재 화면의 분석 결과를 저장합니다.
- 자동 점검은 서버를 실행한 상태에서 `python test/check_html.py`로 실행합니다. 이 점검은 AI·채팅 응답만 테스트 데이터로 대체합니다.

분석 원본, 이미지, 보고서와 로그는 기존과 같이 프로젝트의 `result` 폴더에 저장됩니다.
