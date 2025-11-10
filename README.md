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

(이하 내용은 동일 — 설치, 인덱싱, Streamlit, FastAPI, License, Author 포함)
