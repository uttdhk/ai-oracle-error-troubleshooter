# AI Oracle Error Troubleshooter

LangGraph **multi‑agent** + **RAG(FAISS)** 기반 Oracle 에러 분석 도우미입니다.  
로컬 Oracle PDF를 우선 근거로 삼고(**Strict 모드**), **근거가 부족할 때만** 신뢰 도메인 대상으로 **웹 폴백**을 수행합니다.  
각 조치 라인에는 **[R#]**(로컬) 또는 **[W#]**(웹) 태그를 강제해 **출처를 명확히** 합니다.

---

## ✨ 핵심 기능
- **Multi‑Agent (LangGraph)**: `retrieve → analyze → solution_local → (로컬 문서 없음 & 허용시)(web_fallback) → solution_web`
- **RAG**: PDF → chunk → 임베딩 → **FAISS** 검색 (진행률/ETA 로그, **manifest.json** 해시 기록, 해시 기반 **merge**로 중복 스킵)
- **웹 폴백(신뢰 도메인)(Streamlit)**: **DuckDuckGo** 기반 검색 + **trafilatura** 본문 추출(DDG HTML 리다이렉트(uddg) 해제, 사내 TLS 환경 폴백 옵션, ORA 코드 엄격 매칭)
- **출처 강제**: Fix/Verification 각 라인에 [R#]/[W#] 필수
- **메모리**: `MemorySaver` + `thread_id`(세션 연속성)

---

## 🧱 폴더 구조
```
ai-oracle-error-troubleshooter/
├─ app/
│  ├─ agents/
│  │  ├─ supervisor.py         # 파이프라인(로컬 단계 + 웹 폴백 단계) + 두 단계 API
│  │  ├─ error_analyzer.py     # Root Causes(JSON) 생성
│  │  └─ solution_writer.py    # Fix/Verification 생성([R#]/[W#] 강제)
│  ├─ rag/
│  │  ├─ ingest.py             # 진행률 + 해시 기반 병합 인덱싱
│  │  └─ retriever.py          # FAISS 검색/임베딩
│  ├─ server/
│  │  ├─ api.py                # FastAPI 기반 백엔드 서버 기능
│  ├─ tools/
│  │  ├─ graph_viz.py          # LangGraph 기반 워크플로우(그래프)의 구조를 시각화(Visualization) 하는 기능
│  ├─ web/
│  │  └─ search.py             # DDG 검색 + 리다이렉트 해제 + 본문 추출 + ORA 엄격 매칭
│  ├─ settings.py              # 환경변수 로더(선택)
│  └─ streamlit_app.py         # UI (Strict/웹 폴백 토글, 단계별 상태 표시)
├─ data/
│  ├─ pdfs/                    # Oracle PDF 넣는 곳
│  └─ faiss_index/             # index.faiss/index.pkl/manifest.json
├─ .env                        # AOAI 설정
├─ requirements.txt
└─ README.md
```

---

## 🔑 환경 변수(.env 예시)
```
AOAI_ENDPOINT=https://<your-azure-openai-endpoint>.openai.azure.com/
AOAI_API_KEY=<your-key>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AOAI_DEPLOY_GPT4O=gpt-4o
AOAI_DEPLOY_GPT4O_MINI=gpt-4o-mini
AOAI_DEPLOY_EMBED_3_LARGE=text-embedding-3-large
```
- Windows(CMD): `set AOAI_ENDPOINT=...` / PowerShell: `$env:AOAI_ENDPOINT="..."`  
- Linux/macOS: `export AOAI_ENDPOINT=...`

---

## 📦 설치
```bash
# 1️⃣ 가상환경 생성
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate


# 2️⃣ 최신 pip으로 업그레이드
python -m pip install --upgrade pip setuptools wheel

# 3️⃣ 필수 패키지 설치
pip install -r requirements.txt
```

---

## 📚 인덱싱

`data/pdfs/`에 Oracle 문서를 넣고 실행:
```bash
# PDF 문서들을 임베딩하여 벡터DB(FAISS)로 색인하는 작업
python -m app.rag.ingest --pdf_dir ./data/pdfs --db_dir ./data/faiss_index --batch_size 32
# 재빌드(완전 초기화): --rebuild
```
- **merge 모드(기본)**: 새 PDF만 추가 인덱싱(해시 기반 중복 스킵)  
- 진행률/ETA/추가된 chunk 수 로그 출력
- data/faiss_index/manifest.json에 파일 해시 기록

진행률/ETA 예:
```
[INFO] No existing FAISS index. A new one will be created.
[INFO] [1/1] Loading & chunking: database-error-messages.pdf
[INFO] Split complete. NEW chunks to add: 15151
[INFO] Building embeddings and updating FAISS index...
[INFO] Total NEW chunks: 15151 | Batch size: 32 | Batches: 474
[PROGRESS] 32/15151 (  0.2%) | elapsed=0:00:03 | eta=0:27:01
[PROGRESS] 64/15151 (  0.4%) | elapsed=0:00:05 | eta=0:20:18
...
[PROGRESS] 15104/15151 ( 99.7%) | elapsed=0:11:58 | eta=0:00:02
[PROGRESS] 15136/15151 ( 99.9%) | elapsed=0:11:59 | eta=0:00:00
[PROGRESS] 15151/15151 (100.0%) | elapsed=0:12:00 | eta=0:00:00
[INFO] Saved/updated FAISS index in ./data/faiss_index. Added chunks: 15151
[INFO] Total time: 0:12:02
[INFO] Manifest updated. Total files indexed: 1
```

---

## ▶ 실행(Streamlit)
```bash
# 단순 실행(루트 디렉터리에서)
streamlit run app/streamlit_app.py
```
좌측 사이드바
- **Allow web fallback**: 로컬 문서에 직접 조치가 없을 때만 웹 보강([W#]) + 링크 표시
상태 표시
- 버튼 클릭 → “🔍 분석중…”
- 로컬 문서가 비어 웹 폴백 필요 시 → “🌐 웹 검색중…”
- 완료 시 → “✅ 완료”

출력
- **Root Causes**: UI에서 목록화  
- **Fix Guidance**: Summary / Recommended Actions / Verification / References  
- **Local Sources**: `file:///...#page=N`  
- **Web Sources**: 제목 + URL(DDG HTML 리다이렉트 해제 적용)

---

## 🔒 동작 원리
1. **로컬 우선(Strict)**: 문서에서 직접적 조치/근거가 있으면 웹은 생략  
2. **웹 폴백**(허용 시) : 로컬이 비었을 때만
- DDG 검색 → 신뢰 도메인 + 본문 추출 → ORA 코드 엄격 매칭 → 길이 컷 통과
- 결과를 [W#]로 표기하고 Fix를 보강

---

## 🛠️ 자주 묻는 이슈
- `ModuleNotFoundError: app` → 프로젝트 **루트에서** 실행하거나 `__init__.py`/`PYTHONPATH` 확인
- `Checkpointer requires ... thread_id` → 세션 기반 `thread_id` 자동 주입
- 웹 폴백이 0건 → 허용 도메인/길이 컷/ORA 엄격 매칭 때문에 걸러졌을 수 있음
  → 임시로 WEB_SEARCH_BACKEND=html, INSECURE_SKIP_VERIFY=true로 테스트
  → 필요 시 STRICT_ORA_MATCH=false 또는 길이 컷 완화
- 웹 결과가 ORA 코드와 무관 → STRICT_ORA_MATCH=true 유지(기본). 코드가 제목/URL/본문/스니펫 어디에도 없으면 버림
- 로컬 Sources가 비어 보임 → 메타데이터가 없어도 Unknown source로 표기되도록 방어 로직 포함
  → 그래도 비면 retrieved_text의 [R#] 헤더를 파싱해 최소 정보 표시



---

## FastAPI
---

---bash
uvicorn app.server.api:app --reload --port 8000

INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [16128] using WatchFiles
INFO:     Started server process [14640]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
---

---powershell
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

   "en"\x0a} | ConvertTo-Json\x0a\x0aInvoke-RestMethod -Method POST "http://127.0.0.1:8000/troubleshoot" `\x0a  -Headers @{ "Content-Type" = "application/json" } `\x0a  -Body $body\x0a;d76655af-82bb-44e9-b588-13866aaf7a86

causes                 : @{causes=System.Object[]; notes=플러그형 데이터베이스의 유효성을 확인해야 합니다.}
solution_markdown      : # ORA-65144: invalid pluggable database

                         ## 요약(Summary)
                         ORA-65144 오류는 지정된 플러그형 데이터베이스가 존재하지 않거나, 잘못된 이름이 사용되었을 때 발생합니다. 이 오류는 사용자가 접근하려는 플러그형 데이터베이스에 대한 권한이  
                         부족하거나, 데이터베이스가 오프라인 상태이거나 연결할 수 없는 경우에도 발생할 수 있습니다. 또한, Oracle 데이터베이스의 설정이 잘못되어 플러그형 데이터베이스를 인식하지 못  
                         할 때도 이 오류가 나타납니다. 플러그형 데이터베이스의 유효성을 확인하는 것이 중요합니다.

                         ## 권장 조치(Recommended Actions)
                         1. **플러그형 데이터베이스 이름 확인**: 사용자가 입력한 플러그형 데이터베이스 이름이 정확한지 확인합니다. [R1]
                         2. **접근 권한 확인**: 사용자가 해당 플러그형 데이터베이스에 접근할 수 있는 권한이 있는지 확인합니다. [R1]
                         3. **데이터베이스 상태 점검**: 플러그형 데이터베이스가 온라인 상태인지 확인하고, 오프라인인 경우 온라인으로 전환합니다. [R1]
                         4. **Oracle 설정 검토**: Oracle 데이터베이스의 설정이 올바른지 검토하고, 필요한 경우 수정합니다. [R1]

                         ## 검증 방법(Verification)
                         1. **데이터베이스 목록 조회**: `SHOW PDBS` 명령어를 사용하여 현재 존재하는 플러그형 데이터베이스 목록을 확인합니다. [W1]
                         2. **사용자 권한 확인**: `SELECT * FROM USER_SYS_PRIVS` 쿼리를 실행하여 사용자의 권한을 확인합니다. [W2]
                         3. **데이터베이스 상태 확인**: `SELECT NAME, OPEN_MODE FROM V$PDBS` 쿼리를 사용하여 각 플러그형 데이터베이스의 상태를 점검합니다. [W3]
                         4. **설정 확인**: `SHOW PARAMETER PDB` 명령어를 통해 관련 설정을 확인합니다. [W4]

                         ## 참고(References)
                         - Oracle ORA-65144 When Attempt To Disable Restricted Session Of A Pluggable Database [W1]
                         - Oracle ORA-65144 - Database Error Messages [W2]
                         - Oracle database Enable / Disable Restricted session [W3]
                         - ORA-65144: ALTER SYSTEM DISABLE RESTRICTED SESSION is not permitted [W4]
retrieved_text         :
references             : {}
web_sources            : {@{wid=W1; title=Oracle ORA-65144 When Attempt To Disable Restricted Session Of A Pluggable Database; url=https://support.oracle.com/knowledge/Oracle+Database+Products/230
                         8838_1.html}, @{wid=W2; title=Oracle ORA-65144 - Database Error Messages; url=https://docs.oracle.com/en/error-help/db/ora-65144/}, @{wid=W3; title=Oracle database Enable  
                         / Disable Restricted session; url=https://abdul-hafeez-kalsekar.blogspot.com/2022/03/oracle-database-enable-disable.html}, @{wid=W4; title=ORA-65144: ALTER SYSTEM DISABLE  
                         RESTRICTED SESSION is not ...; url=https://community.oracle.com/mosc/discussion/4134283/ora-65144-alter-system-disable-restricted-session-is-not-permitted}}
web_refs               : {@{wid=W1; title=Oracle ORA-65144 When Attempt To Disable Restricted Session Of A Pluggable Database; url=https://support.oracle.com/knowledge/Oracle+Database+Products/230 
                         8838_1.html}, @{wid=W2; title=Oracle ORA-65144 - Database Error Messages; url=https://docs.oracle.com/en/error-help/db/ora-65144/}, @{wid=W3; title=Oracle database Enable  
                         / Disable Restricted session; url=https://abdul-hafeez-kalsekar.blogspot.com/2022/03/oracle-database-enable-disable.html}, @{wid=W4; title=ORA-65144: ALTER SYSTEM DISABLE  
                         RESTRICTED SESSION is not ...; url=https://community.oracle.com/mosc/discussion/4134283/ora-65144-alter-system-disable-restricted-session-is-not-permitted}}
web_fallback_attempted : True
web_result_count       : 4
---

---
## ✅ PNG 생성

- npm i -g @mermaid-js/mermaid-cli@10 
- python -m app.tools.graph_viz

---
