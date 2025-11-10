# app/agents/supervisor.py
"""
RAG 우선, 실패 시 WEB fallback.
- ORA 코드가 질의에 있으면 '직접 일치'하는 PDF 조각만 채택(정확 매칭 필터)
- 직접 일치가 없거나, (ORA코드가 없어도) 로컬 검색 결과가 비면 → 웹 검색/본문추출
- 결과: [R#]/[W#] 태그와 Local/Web Sources 함께 반환
"""
from __future__ import annotations  # 타입 힌트를 문자열로 처리하게 만드는 기능
from dataclasses import dataclass, field # “데이터 전용 클래스”를 간단하게 정의하기 위한 문법
from typing import Dict, Any, List, Optional, Tuple 
from uuid import uuid4 # 고유한 식별자(UUID, Universally Unique Identifier) 를 자동으로 생성하기 위한 코드
from langgraph.graph import StateGraph, END  # StateGraph : 그래프 기반 워크플로우 객체, END : 그래프 종료 노드의 상수
from langgraph.checkpoint.memory import MemorySaver # 간단한 인메모리 방식 저장소
from ..rag.retriever import retrieve
import os # 운영체제(OS, Operating System)와 상호작용하기 위한 표준 라이브러리
import re

# 모델 기본값: 환경변수에서 우선 가져오고, 없으면 빈 문자열로
MODEL = (
    os.getenv("AOAI_DEPLOY_GPT4O_MINI")
    or os.getenv("AOAI_DEPLOY_GPT4O")
    or os.getenv("OPENAI_DEPLOYMENT")
    or ""
)
from .error_analyzer import run as run_error_analyzer
from .solution_writer import run as run_solution_writer
from ..web.search import search_web_safely

# ---------- State ----------
@dataclass
class AgentState:
    user_input: str
    db_dir: str
    allow_web: bool = True
    # local
    retrieved_text: str = ""
    references: List[Dict[str, Any]] = field(default_factory=list)
    # analysis
    causes_json: Dict[str, Any] = field(default_factory=dict)
    solution_markdown: str = ""
    # web
    web_context: str = ""
    web_refs: List[Dict[str, str]] = field(default_factory=list)
    # debug
    web_attempted: bool = False
    web_result_count: int = 0

# ---------- Helpers ----------
# **Oracle 오류 코드(ORA-XXXX 형식)**를 문자열에서 추출하는 함수
def _extract_ora_code(q: str) -> Optional[str]:
    m = re.search(r"(ORA-\d{5})", (q or "").upper())
    return m.group(1) if m else None

# LangGraph를 기반으로 로컬 실행 블록들을 구성하는 함수
def _build_local_blocks(docs, start_index=1) -> Tuple[str, List[Dict[str, Any]]]:
    """
    반환 텍스트는 [R#] 태그를 헤더로 가진 블록들의 합치기.
    refs: [{"rid":"R1","filename":"...","page":3}, ...]
    """
    blocks, refs = [], []
    for i, d in enumerate(docs, start_index):
        # ✅ 메타데이터가 없거나 키가 다를 때도 안정적으로 참조 생성
        meta = getattr(d, "metadata", {}) or {}
        fn = (
            meta.get("source")
            or meta.get("filename")
            or meta.get("file")
            or meta.get("path")
            or "Unknown source"
        )
        page = (
            meta.get("page")
            or meta.get("pageno")
            or meta.get("page_number")
            or ""
        )
        header = f"[R{i}] {fn}" + (f" (p.{page})" if str(page).strip() else "")
        blocks.append(f"{header}\n{d.page_content}")
        refs.append({"rid": f"R{i}", "filename": fn, "page": page})
    return ("\n\n---\n\n".join(blocks)), refs

# 웹 검색 결과를 포함하는 흐름을 설계하는 함수
def _build_web_blocks(results: List[Dict[str, str]], start_index=1) -> Tuple[str, List[Dict[str, str]]]:
    """
    search_web_safely() 결과를 받아 [W#] 블록 텍스트 + UI용 web_refs 생성
    """
    blocks, refs = [], []
    idx = start_index
    for r in results:
        url = r.get("url") or r.get("href") or ""
        title = r.get("title") or url
        body  = r.get("text")  or r.get("content") or r.get("snippet") or ""
        if not url:
            continue
        header = f"[W{idx}] {title}\n{url}"
        if body:
            blocks.append(f"{header}\n{body}")
        else:
            blocks.append(header)
        refs.append({"wid": f"W{idx}", "title": title, "url": url})
        idx += 1
    return ("\n\n---\n\n".join(blocks)), refs

# ---------- Nodes ----------
# LangGraph나 LangChain 기반의 그래프(노드) 구조 안에서, "지식 검색 단계"를 담당하는 노드 함수
def node_retrieve(state: AgentState) -> AgentState:
    """RAG 검색 → ORA 직접 일치 필터."""
    k = 10
    docs = retrieve(state.user_input, state.db_dir, k=k)

    ora = _extract_ora_code(state.user_input)
    if ora:
        matched = [d for d in docs if ora in (d.page_content or "")]
    else:
        matched = docs

    if matched:
        text, refs = _build_local_blocks(matched, start_index=1)
        state.retrieved_text, state.references = text, refs
    else:
        state.retrieved_text, state.references = "", []
    return state

# LangGraph 기반 파이프라인에서 오류 메시지를 “분석(analyze)”하는 노드 함수
def node_analyze(state: AgentState) -> AgentState:
    """원인 JSON 작성(LLM). 로컬 문맥만 사용."""
    state.causes_json = run_error_analyzer(
        model=MODEL,
        user_input=state.user_input,
        retrieved_context=state.retrieved_text or "",
        strict=True,
        locale="ko" if getattr(state, "prefer_ko", True) else "en",  # ✅
    ) or {}
    return state

# 파이프라인에서 최종 해결책(솔루션)을 작성하는 노드
def node_solution(state: AgentState) -> AgentState:
    """해결 가이드(LLM). 우선 로컬 참조만으로 시도."""
    md = run_solution_writer(
        model=MODEL,
        user_input=state.user_input,
        causes_json=state.causes_json or {},
        retrieved_context=state.retrieved_text or "",
        strict=True,
        web_context="",   # 1차는 로컬만
        locale="ko" if getattr(state, "prefer_ko", True) else "en",  # ✅
    )
    state.solution_markdown = md or ""
    return state

# 로컬 검색/지식으로 해결이 불충분할 때 웹 검색을 수행해 결과를 보완하는 노드
def node_web_fallback(state: AgentState) -> AgentState:
    """
    로컬 문서가 없을 때만(=retrieved_text가 비었을 때) 웹 폴백 실행.
    UI가 '웹 폴백 근거 없음'으로 오인하지 않게, 0건이어도 placeholder 1건을 넣어준다.
    """
    # 1) Allow 체크
    if not state.allow_web:
        state.web_attempted = False
        state.web_result_count = 0
        state.web_context = ""
        state.web_refs = []
        return state

    # 2) 로컬 미확보(=문서에 없을 때)만 폴백
    need_web = not bool((state.retrieved_text or "").strip())
    if not need_web:
        state.web_attempted = False
        state.web_result_count = 0
        state.web_context = ""
        state.web_refs = []
        return state

    # 3) 웹 검색 실행
    results, queries = search_web_safely(state.user_input, max_results=6)
    state.web_attempted = True
    state.web_result_count = len(results)

    if results:
        web_text, web_refs = _build_web_blocks(results, start_index=1)
        state.web_context = web_text
        state.web_refs = web_refs

        # 웹 문맥으로 솔루션 1회 보강
        md2 = run_solution_writer(
            model=MODEL,
            user_input=state.user_input,
            causes_json=state.causes_json or {},
            retrieved_context=state.retrieved_text or "",
            strict=False,
            web_context=state.web_context or "",
            locale=("ko" if getattr(state, "prefer_ko", True) else "en"),  # ✅ 추가
        )
        if md2:
            state.solution_markdown = md2
    else:
        # 🔴 여기서가 핵심: UI가 '웹 폴백 근거 없음'으로 오인하지 않게 placeholder를 넣는다.
        placeholder = {
            "wid": "W0",
            "title": "웹 검색 시도됨 (0건)",
            "url": "about:blank",
        }
        state.web_context = "웹 검색을 시도했지만 허용 도메인/길이 기준에 맞는 본문을 찾지 못했습니다."
        state.web_refs = [placeholder]
        state.web_result_count = 0  # 실제 수집 0건임을 유지

    return state

# 여러 노드(node)를 엮어 LangGraph 실행 그래프를 구성하고, 실행 가능한 앱(app)을 반환하는 함수
def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("retrieve", node_retrieve)
    builder.add_node("analyze",  node_analyze)
    builder.add_node("solution", node_solution)
    builder.add_node("web",      node_web_fallback)

    builder.set_entry_point("retrieve")
    builder.add_edge("retrieve", "analyze")
    builder.add_edge("analyze",  "solution")
    builder.add_edge("solution", "web")

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)

# 웹을 쓰지 않고(offline) 로컬 지식만으로 1차 진단을 끝내는 실행 단계
def run_local_phase(
    user_input: str,
    db_dir: str,
    *,
    thread_id: str | None = None,
    prefer_ko: bool = True,   # ✅ locale 플래그 인자 추가
) -> AgentState:
    """retrieve → analyze → solution까지만 수행 (웹 미포함)"""
    state = AgentState(user_input=user_input, db_dir=db_dir, allow_web=True)
    state.prefer_ko = prefer_ko  # ✅ 로컬 단계 시작 전에 주입
    state = node_retrieve(state)
    state = node_analyze(state)
    state = node_solution(state)
    return state

# 로컬 단계에서 부족했던 근거를 웹 검색으로 채우고 최종 솔루션을 완성하는 함수
def run_web_phase(
    state: AgentState,
    *,
    thread_id: str | None = None,
) -> AgentState:
    """이미 로컬 단계를 마친 state에 대해, 필요 시 웹 폴백만 수행"""
    return node_web_fallback(state)

# 전체 오류 분석 파이프라인을 통합 실행하는 메인 엔트리 포인트
def run_pipeline(
    user_input: str,
    db_dir: str,
    thread_id: str | None = None,
    allow_web: bool = True,
    locale: str = "en",
    **kwargs,
) -> dict:
    # allow_web_fallback 정규화
    if "allow_web_fallback" in kwargs and kwargs["allow_web_fallback"] is not None:
        allow_web = bool(kwargs["allow_web_fallback"])

    app = build_graph()
    initial = AgentState(user_input=user_input, db_dir=db_dir, allow_web=allow_web)
    cfg = {"configurable": {"thread_id": thread_id or str(uuid4())}}
    result = app.invoke(initial, config=cfg)

    get = lambda k, d=None: (result.get(k, d) if isinstance(result, dict) else getattr(result, k, d))
    web_refs = get("web_refs", []) or []
    return {
        "causes": get("causes_json", {}),
        "solution_markdown": get("solution_markdown", ""),
        "retrieved_text": get("retrieved_text", ""),
        "references": get("references", []),
        "web_sources": web_refs,
        "web_refs": web_refs,
        "web_fallback_attempted": bool(get("web_attempted", False)),
        "web_result_count": int(get("web_result_count", 0) or 0),
    }

# **1단계(로컬) → 2단계(웹 보강, 필요 시만)**로 동작하는 오케스트레이터
def run_pipeline_two_step(
    user_input: str,
    db_dir: str,
    *,
    allow_web: bool = True,
    prefer_ko: bool = True,      # ✅ 추가
    thread_id: str | None = None,
) -> dict:
    """
    1) 로컬 단계 수행 → 2) 로컬 스니펫이 없고 allow_web=True면 웹 폴백만 수행
    UI에서 상태 라벨을 바꾸기 쉽게 단계가 분리된 호출.
    """

    # 1단계: 로컬 (분석 노드가 돌기 전에 prefer_ko를 전달)
    state = run_local_phase(
        user_input,
        db_dir,
        thread_id=thread_id,
        prefer_ko=prefer_ko,  # ✅ 핵심
    )

    # 2단계 조건 판정
    need_web = allow_web and not bool((state.retrieved_text or "").strip())

    if need_web:
        state.allow_web = True
        state = run_web_phase(state, thread_id=thread_id)
    else:
        # 웹 미시도 명시
        state.web_attempted = False
        state.web_result_count = 0
        state.web_refs = []
        state.web_context = ""

    # 반환 포맷은 run_pipeline과 동일
    return {
        "causes": state.causes_json or {},
        "solution_markdown": state.solution_markdown or "",
        "retrieved_text": state.retrieved_text or "",
        "references": state.references or [],
        "web_sources": state.web_refs or [],
        "web_refs": state.web_refs or [],
        "web_fallback_attempted": bool(state.web_attempted),
        "web_result_count": int(state.web_result_count or 0),
        "need_web": need_web,  # ✅ UI에 신호 제공
    }

__all__ = [
    "run_pipeline",
    "run_pipeline_two_step",
    "run_local_phase",
    "run_web_phase",
]