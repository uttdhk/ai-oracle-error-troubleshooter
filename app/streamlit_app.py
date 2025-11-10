# app/streamlit_app.py
import time
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../<project-root>
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import uuid
import streamlit as st
from app.agents.supervisor import run_pipeline_two_step
from app.agents.supervisor import run_pipeline
from app.settings import AOAI_ENDPOINT, AOAI_DEPLOY_EMBED_3_LARGE


st.set_page_config(page_title="AI Oracle Error Troubleshooter", page_icon="🛠️", layout="wide")
st.title("🛠️ AI Oracle Error Troubleshooter")


# ----------------------------
# 세션 상태: 입력/옵션 기본값 (최초 1회만)
# ----------------------------
if "query" not in st.session_state:
    st.session_state["query"] = ""  # 기본값
if "allow_web" not in st.session_state:
    st.session_state["allow_web"] = True
if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = str(uuid.uuid4())
if "prefer_ko" not in st.session_state:
    st.session_state["prefer_ko"] = True    # 기본은 한글 보기 ON

with st.sidebar:
    st.subheader("Settings")
    db_dir = st.text_input("FAISS DB dir", value="./data/faiss_index")
    
    allow_web_fallback = st.checkbox(
        "Allow web fallback(로컬 문서가 없을 때만 웹 보강)",
        key="allow_web",
    )
    prefer_ko  = st.checkbox(
        "결과 한글로 보기",
        key="prefer_ko",
    )

    
    st.caption("🔎 환경 변수 확인")
    st.write("AOAI_ENDPOINT:", "OK" if AOAI_ENDPOINT else "❌")
    st.write("EMBED_DEPLOY:", AOAI_DEPLOY_EMBED_3_LARGE or "❌")
    st.divider()
    st.caption("인덱싱 명령")
    st.code("python -m app.rag.ingest --pdf_dir ./data/pdfs --db_dir ./data/faiss_index --batch_size 32", language="bash")



# 입력창: 고정 key로 세션 값 유지
user_input = st.text_area(
    "Oracle 에러 코드 / 메시지 / 로그 입력",
    key="query",
  #  value=st.session_state["query"],
    height=160,
    placeholder="예) ORA-65144: invalid pluggable database",
)

if st.button("분석하기"):

    # 한글 결과를 원하는 경우, 입력 앞에 한국어 지시문을 붙여 LLM이 한국어로 응답하도록 유도
    effective_input = (
        f"모든 응답은 한국어로 작성해 주세요.\n{user_input}"
        if st.session_state.get("prefer_ko", True)   # 또는 prefer_ko
        else user_input
    )

    with st.status("🔎 분석중...", expanded=True) as status:
        # 1) 로컬 단계
        local = run_pipeline_two_step(
            user_input,
            db_dir=db_dir,
            allow_web=bool(st.session_state.get("allow_web", True)),
            prefer_ko=st.session_state.get("prefer_ko", True),   # ✅ locale 전달
        )
        if local.get("need_web"):
            status.update(label="🌐 웹 검색중...", state="running")
            time.sleep(1.0)  # 👈 1초만 잠시 보여줌 (streamlit이 바로 완료로 바꾸지 않게)
            # 2) 이미 run_pipeline_two_step 안에서 웹까지 끝났음
            #    (두 단계 수행 결과가 local 변수에 들어있음)

        # 완료
        status.update(label="✅ 완료", state="complete")

    # 결과 렌더링
    st.subheader("Root Causes(근본 원인)")
    st.json(local.get("causes", {}))

    st.subheader("Fix Guidance(해결 방안)")
    st.markdown(local.get("solution_markdown", "") or "No guidance generated.")

    st.subheader("Local Sources(로컬 문서 근거)")
    refs = local.get("references", []) or []
    if refs:
        for ref in refs:
            rid = ref.get("rid", "")
            fn = ref.get("filename", "")
            pg = ref.get("page", "")
            suffix = f" (p.{pg})" if pg not in (None, "", 0) else ""
            st.markdown(f"- **{rid}**: {fn}{suffix}")
    else:
        # Fallback: retrieved_text에서 [R#] 헤더만 추출해 표시
        import re
        retrieved_text = local.get("retrieved_text", "") or ""
        headers = re.findall(r"^\[R(\d+)\]\s*(.+)$", retrieved_text, re.MULTILINE)
        if headers:
            for num, line in headers[:10]:
                st.markdown(f"- **R{num}**: {line}")
        else:
            st.write("로컬 문서 직접 근거 없음")

    st.subheader("Web Sources(웹 문서 근거)")
    web_refs = local.get("web_sources") or []
    if web_refs:
        for r in web_refs:
            st.markdown(f'- [{r.get("title","link")}]({r.get("url","")})')
    else:
        if local.get("need_web"):
            st.write("웹 검색 시도됨(0건).")
        else:
            st.write("로컬에서 해결됨(웹 폴백 불필요).")