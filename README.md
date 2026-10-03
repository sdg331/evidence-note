# 근거노트

채용 관련 문서에서 질문과 관련된 내용을 찾고, 답변의 근거와 저장된 발췌문을 확인하는 웹 데모입니다. 공식 자료의 일부를 검색하는 시연과 사용자가 올린 문서를 탐색하는 로컬 작업 공간을 제공합니다.

## 문제와 시연 범위

채용 정보를 읽는 사람은 긴 가이드에서 필요한 구절을 찾고 출처를 다시 확인해야 합니다. 근거노트는 **질문 → 검색 → 쪽수와 발췌 확인 → 공식 원문 확인**의 흐름을 보여줍니다. 근거가 없으면 답을 만들지 않고 근거 없음으로 표시합니다.

시연 자료는 고용노동부·한국산업인력공단의 **2024년 『공감채용 가이드 핸드북』** 중 인쇄 **53·64·70쪽**에서 관련 문단을 골라 OCR 후 이미지와 대조해 **요약**한 것입니다. [공식 게시 페이지](https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20240400051)에 원본과 **공공누리 제1유형(출처 표시)**이 표시됩니다. [데이터와 원본 대응표](demo/README.md)에 실제 검색 범위를 적었습니다. **92쪽 전체를 색인한 결과나 현행 법률 안내가 아닙니다.**

## 3분 시연

1. 공식 자료 질문 **“채용 불합격 통지 방법은?”**을 선택하고 답변과 **53쪽** 근거를 확인합니다.
2. **“검수한 발췌 요약 확인”**에서 저장된 문장을 보고 **“공식 원문 보기”**로 출처를 확인합니다.
3. **“지원서에 주민등록번호를 기재해야 하나요?”**를 물어 근거 없는 질문의 거절을 확인합니다.
4. 로컬 Ollama 모델을 설치했다면 **AI 답변 생성**을 선택해 생성 답변과 `[1]` 인용을 확인합니다. 답변의 사실성은 출처와 대조해야 합니다.

## 구현

| 영역 | 현재 구현 |
| --- | --- |
| 화면 | React, TypeScript, Vite; 반응형 문서 목록·질문·근거·발췌 확인 |
| API와 저장 | FastAPI, SQLite; 파일 검증, 원문/쪽수 저장, 이전 DB 구조 호환 |
| 기본 검색 | 한국어 질문 단서 추출과 키워드 점수; 근거가 부족하면 거절 |
| 선택형 의미 검색 | 로컬 Ollama `bge-m3`; 키워드 검색이 실패할 때만 사용, 기본 비활성화 |
| 선택형 AI 답변 | 로컬 Ollama 또는 OpenAI; 검색 근거만 전달, 인용 번호 형식 검증 |
| 공개 시연 모드 | 문서 수정과 모델 호출 차단, 준비된 자료의 검색만 제공 |

AI 답변은 자체 학습 모델이 아닙니다. 인용 번호가 유효해도 문장 자체가 사실인지 자동으로 보증하지는 않습니다. 가상 온보딩 문서는 실제 회사 정책이 아닙니다.

## 실행

Python 3.10 이상과 Node.js 20.19.x 또는 22.12 이상이 필요합니다. 저장소 루트에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m scripts.seed_demo --db backend/data/documents.sqlite3
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

다른 터미널에서 화면을 실행합니다.

```bash
cd frontend
npm ci
npm run dev
```

Vite가 표시한 로컬 주소를 엽니다. 기본 포트는 5173이며 이미 사용 중이면 다른 포트를 표시합니다. API 상태는 <http://127.0.0.1:8000/api/health>, 명세는 <http://127.0.0.1:8000/docs>에서 확인할 수 있습니다. `seed_demo`는 기존 문서를 삭제하지 않고 같은 자료의 중복 추가를 건너뜁니다.

### 로컬 AI 시연

Ollama를 별도로 설치·실행하고 `exaone3.5:2.4b`와 `bge-m3`를 준비한 뒤 API 서버를 다음 설정으로 실행합니다. 모델이 없어도 기본 검색은 동작합니다. `SEMANTIC_RETRIEVAL=1`은 검증용 선택 사항입니다.

```bash
ANSWER_PROVIDER=ollama OLLAMA_MODEL=exaone3.5:2.4b SEMANTIC_RETRIEVAL=1 \
  python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

AI 답변을 선택하면 질문과 최대 3개 근거가 **서버의 로컬 Ollama**로 전달됩니다. OpenAI는 `backend/.env.example`의 `OPENAI_API_KEY`, `OPENAI_MODEL`을 서버 환경에 설정한 경우에만 사용할 수 있으며 호출 비용이 발생할 수 있습니다. 키나 문서를 코드에 넣지 마세요.

### 읽기 전용 시연

준비된 자료만 보여주는 공개 시연에는 별도 DB를 만들고 다음처럼 실행할 수 있습니다. 이 모드에서는 업로드, 삭제, AI 생성, 의미 검색을 차단합니다. 인증과 사용자별 저장소가 없으므로 실제 서비스 공개 배포의 대체 수단은 아닙니다.

```bash
python -m scripts.seed_demo --db backend/data/competition-demo.sqlite3
PUBLIC_DEMO=1 DOCUMENT_QA_DB_PATH=backend/data/competition-demo.sqlite3 \
  python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## 검증

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q backend/tests
python -m backend.evaluation.run
python -m backend.evaluation.run --semantic
python -m scripts.evaluate_demo
SEMANTIC_RETRIEVAL=1 python -m scripts.evaluate_demo
cd frontend && npm run build
```

2026-10-03 로컬 확인: API 테스트 **51개 통과**, 프런트엔드 빌드 통과. 공식 가이드 **3쪽의 검수 요약**에 대해 작성한 13개 근거 질문의 첫 번째 출처 쪽수는 기본 검색 **12/13**, 로컬 의미 검색 보조를 켰을 때 **13/13** 일치했습니다. 자료 밖 질문 **7/7**은 두 설정 모두 근거 없음으로 처리했습니다. 이것은 작은 자체 작성 회귀 세트의 결과이며, 다른 문서나 실제 사용자의 질문에서 같은 수치를 보장하지 않습니다. [평가 질문](demo/evaluation_cases.json)과 [실행 코드](scripts/evaluate_demo.py)를 공개합니다.

별도의 가상 문서 회귀 세트에서는 기본 검색의 첫 출처 일치 **6/7**, 의미 검색 보조 사용 시 **7/7**, 근거 없음 처리 **3/3**이었습니다. 의미 검색 관련 명령은 Ollama와 `bge-m3`가 실행 중일 때 재현할 수 있습니다.

## 제한과 대회 제출 전 작업

- 제공하는 공식 자료는 2024년 판본의 일부입니다. 이미지형 PDF 전체의 OCR과 페이지별 검수는 아직 구현되지 않았습니다. 사용자 PDF 업로드는 **텍스트층이 있는 5MB 이하 파일**만 지원합니다.
- 의미 검색의 유사도 기준은 작은 시연 자료에 맞춘 임시값입니다. 다른 분야 자료에서 오탐이 없는지 별도 평가가 필요합니다.
- 생성 답변은 근거 번호 형식을 검증하지만 사실성 평가나 법률 검토를 대신하지 않습니다.
- 로컬 작업 공간에는 계정·권한 분리와 저장 데이터 암호화가 없습니다. 민감한 문서를 올리지 마세요. 공개 배포 전에는 인증, 사용자별 데이터 분리, 보관·삭제 정책, 업로드 방어 및 모델 호출 제한이 필요합니다.
- 특정 대회 요강, 주제, 마감일이 아직 정해지지 않았습니다. 제출 전 요강에 맞춰 사용성 검증, 데이터 범위, 발표 자료와 배포 방식을 확정해야 합니다.

이 프로젝트의 시연 데이터 출처는 [고용노동부 공식 게시 페이지](https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20240400051)이며, 시연용 요약은 출처·판본·쪽수를 화면과 데이터에 표시합니다.
