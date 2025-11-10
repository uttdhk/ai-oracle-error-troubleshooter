# AI Oracle Error Troubleshooter

LangGraph **multi-agent** + **RAG (FAISS)** 기반 Oracle 에러 분석 도우미입니다.  
로컬 Oracle PDF를 우선 근거로 삼고(**Strict 모드**), **근거가 부족할 때만** 신뢰 도메인을 대상으로 **웹 폴백(Web Fallback)**을 수행합니다.  
각 조치 라인에는 **[R#]**(로컬) 또는 **[W#]**(웹) 태그를 강제하여 **출처를 명확히 구분**합니다.

---

## ✨ 핵심 기능
- **Multi-Agent (LangGraph)**: `retrieve → analyze → solution_local → (로컬 문서 없음 & 허용 시)(web_fallback) → solution_web`
- **RAG**: PDF → chunk → 임베딩 → **FAISS** 검색 (진행률 / ETA 로그, **manifest.json** 해시 기록)
- **웹 폴백(Streamlit)**: **DuckDuckGo** 기반 검색 + **trafilatura** 본문 추출  
  (DDG HTML 리다이렉트 해제, 사내 TLS 환경 폴백 옵션, ORA 코드 엄격 매칭)
- **출처 강제**: Fix / Verification 각 라인에 [R#] / [W#] 태그 필수
- **메모리 유지**: `MemorySaver` + `thread_id` 기반 세션 연속성

---

## 🧱 폴더 구조
```
ai-oracle-error-troubleshooter/
├─ app/
│  ├─ __init__.py
│  ├─ agents/
│  │  ├─ __init__.py
│  │  ├─ supervisor.py
│  │  ├─ error_analyzer.py
│  │  └─ solution_writer.py
│  ├─ rag/
│  │  ├─ __init__.py
│  │  ├─ ingest.py
│  │  └─ retriever.py
│  ├─ server/
│  │  ├─ __init__.py
│  │  └─ api.py
│  ├─ tools/
│  │  ├─ __init__.py
│  │  └─ graph_viz.py
│  ├─ web/
│  │  ├─ __init__.py
│  │  └─ search.py
│  ├─ settings.py
│  └─ streamlit_app.py
├─ data/
│  ├─ pdfs/
│  └─ faiss_index/
├─ .env
├─ requirements.txt
└─ README.md
```

---

## 🔑 환경 변수 (.env 예시)
```bash
AOAI_ENDPOINT=https://<your-azure-openai-endpoint>.openai.azure.com/
AOAI_API_KEY=<your-key>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AOAI_DEPLOY_GPT4O=gpt-4o
AOAI_DEPLOY_GPT4O_MINI=gpt-4o-mini
AOAI_DEPLOY_EMBED_3_LARGE=text-embedding-3-large
```

---

## 📦 설치
```bash
# 1️⃣ 가상환경 생성
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# 2️⃣ 최신 pip으로 업그레이드
python -m pip install --upgrade pip setuptools wheel

# 3️⃣ 필수 패키지 설치
pip install -r requirements.txt
```

---

## 📚 인덱싱 (RAG 생성)
```bash
# PDF 문서 임베딩 → FAISS 인덱스 생성
python -m app.rag.ingest --pdf_dir ./data/pdfs --db_dir ./data/faiss_index --batch_size 32
# 완전 초기화 시 --rebuild 추가
```

---

## ▶ 실행 (Streamlit)
```bash
streamlit run app/streamlit_app.py --server.port 8080
```
- **Allow web fallback**: 로컬 문서에 직접 조치가 없을 때만 웹 보강 ([W#])  
- 상태:  
  - “🔍 분석중…” → 로컬 분석 중  
  - “🌐 웹 검색중…” → 폴백 수행 중  
  - “✅ 완료” → 결과 표시  

---

## 🌐 FastAPI 실행
```bash
uvicorn app.server.api:app --reload --port 8000
```

예제 요청 (PowerShell):
```powershell
$DB = (Resolve-Path .\data\faiss_index).Path
$body = @{
  query     = "ORA-12143"
  db_dir    = $DB
  strict    = $true
  allow_web = $true
  locale    = "ko"
} | ConvertTo-Json

$response = Invoke-RestMethod -Method POST "http://127.0.0.1:8000/troubleshoot" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body $body
$response
```

응답(JSON 예시):
```json
{
  "causes": [
    "The specified pluggable database (PDB) does not exist.",
    "The user does not have privileges to access the PDB."
  ],
  "solution_markdown": "## 요약 ...",
  "web_sources": [
    {"wid": "W1", "title": "...", "url": "..."}
  ]
}
```

---

## ✅ 그래프 시각화
```bash
npm i -g @mermaid-js/mermaid-cli@10
python -m app.tools.graph_viz
```

---

## 💬 자주 묻는 문제
- `ModuleNotFoundError: app` → 루트에서 실행 필요
- 웹 폴백 결과 0건 → STRICT_ORA_MATCH / 길이 컷 확인
- `thread_id` 오류 → 세션 생성 시 자동 주입 확인
- 로컬 Source가 비어 있음 → Unknown source 방어 로직 적용됨

---

## 🧾 License
This project is distributed under the MIT License.

---

## 🧠 Author
**uttdhk**  
AI Oracle Error Troubleshooter (2025)
