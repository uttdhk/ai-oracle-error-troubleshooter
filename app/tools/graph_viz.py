# app/tools/graph_viz.py
from __future__ import annotations
from typing import Tuple, Union, Callable
from langgraph.graph import StateGraph, END
import os, subprocess, tempfile, shutil
from app.agents import supervisor as sup

# 리스트나 딕셔너리 등 여러 후보 중에서 “하나를 선택(pick)”하는 내부 유틸리티 함수
def _pick(cands: list[str], default: Callable = lambda s: s) -> tuple[Callable, str, bool]:
    for name in cands:
        fn = getattr(sup, name, None)
        if callable(fn):
            return fn, name, True
    return default, cands[0], False

# LangGraph의 StateGraph를 생성·설정·컴파일해서 실행 가능한 앱(app)을 만드는 내부 빌더 함수
def _build_state_graph():
    AgentState = getattr(sup, "AgentState", None)
    if AgentState is None:
        from dataclasses import dataclass, field
        @dataclass
        class AgentState:
            user_input: str = ""
            db_dir: str = ""
            strict: bool = True
            allow_web: bool = False
            locale: str = "en"
            retrieved_text: str = ""
            references: list = field(default_factory=list)
            web_sources: list = field(default_factory=list)
            web_refs: list = field(default_factory=list)
            web_result_count: int = 0

    retrieve_fn, _, _ = _pick(["node_retrieve", "retrieve", "retrieve_node"])
    analyze_fn,  _, _ = _pick(["node_analyze", "analyze", "analyze_node"])
    write_fn,    _, has_write = _pick(["node_write_solution","write_solution","node_solution","node_solution_writer","node_write"])
    web_fn,      _, has_web   = _pick(["node_web_fallback","node_web_search","web_fallback","node_web"])

    g = StateGraph(AgentState)
    g.add_node("retrieve", retrieve_fn)
    g.add_node("analyze", analyze_fn)
    g.add_node("write_solution", write_fn if has_write else (lambda s: s))
    if has_web:
        g.add_node("web_search", web_fn)

    g.set_entry_point("retrieve")
    if has_web:
        g.add_edge("retrieve", "analyze")
        g.add_edge("retrieve", "web_search")
        g.add_edge("web_search", "analyze")
        g.add_edge("web_search", "write_solution")
    else:
        g.add_edge("retrieve", "analyze")
    g.add_edge("analyze", "write_solution")
    g.add_edge("write_solution", END)
    return g

# Mermaid CLI 실행 파일(mmdc)의 위치를 찾아 반환하는 내부 헬퍼
def _find_mmdc_path() -> str | None:
    """
    Windows에서는 보통 %AppData%\\npm\\mmdc.cmd
    예) C:\\Users\\<User>\\AppData\\Roaming\\npm\\mmdc.cmd
    """
    # 1) PATH에서 검색
    for name in ("mmdc", "mmdc.cmd"):
        p = shutil.which(name)
        if p:
            return p
    # 2) npm prefix에서 유추
    try:
        prefix = subprocess.check_output(["npm", "prefix", "-g"], text=True).strip()
        # Windows 글로벌 bin
        cand = os.path.join(prefix, "mmdc.cmd")
        if os.path.exists(cand):
            return cand
        # Unix 계열
        cand = os.path.join(prefix, "bin", "mmdc")
        if os.path.exists(cand):
            return cand
    except Exception:
        pass
    # 3) Windows AppData Roaming
    appdata = os.getenv("APPDATA")
    if appdata:
        cand = os.path.join(appdata, "npm", "mmdc.cmd")
        if os.path.exists(cand):
            return cand
    return None

# _find_mmdc_path가 찾은 Mermaid CLI(mmdc)를 실제로 실행해, Mermaid 코드(.mmd)를 PNG 이미지로 렌더링(render) 하는 함수
def _render_png_via_mmdc(mermaid_src: str) -> bytes | None:
    mmdc = _find_mmdc_path()
    if not mmdc:
        print("[graph_viz] mmdc not found in PATH. Install with: npm i -g @mermaid-js/mermaid-cli@10")
        return None
    with tempfile.TemporaryDirectory() as td:
        mmd = os.path.join(td, "graph.mmd")
        out = os.path.join(td, "graph.png")
        with open(mmd, "w", encoding="utf-8") as f:
            f.write(mermaid_src)
        try:
            subprocess.run([mmdc, "-i", mmd, "-o", out, "-b", "transparent"], check=True, capture_output=True, text=True)
            with open(out, "rb") as f:
                return f.read()
        except subprocess.CalledProcessError as e:
            print("[graph_viz] mmdc failed:", e.stderr or e.stdout)
        except Exception as e:
            print("[graph_viz] mmdc exception:", repr(e))
    return None

# LangGraph나 Mermaid 다이어그램을 PNG 이미지 또는 Mermaid 원본(.mmd) 파일로 내보내는(export) 기능을 담당하는 유틸리티 함수
def export_png_or_mermaid(debug: bool=False) -> Tuple[str, Union[bytes, str]]:
    g = _build_state_graph()
    compiled = g.compile()
    # 1) LangGraph 내장 PNG 시도
    try:
        png = compiled.get_graph().draw_mermaid_png()
        if png:
            if debug: print("[graph_viz] built-in PNG OK")
            return "png", png
    except Exception as e:
        if debug: print("[graph_viz] built-in PNG failed:", repr(e))
    # 2) mmdc 폴백
    mermaid_src = compiled.get_graph().draw_mermaid()
    png2 = _render_png_via_mmdc(mermaid_src)
    if png2:
        if debug: print("[graph_viz] mmdc PNG OK")
        return "png", png2
    # 3) 최후: Mermaid 텍스트
    if debug: print("[graph_viz] fallback to Mermaid text")
    return "mermaid", mermaid_src

# CLI 실행 지원: python -m app.tools.graph_viz
if __name__ == "__main__":
    kind, payload = export_png_or_mermaid(debug=True)
    if kind == "png":
        with open("langgraph.png", "wb") as f:
            f.write(payload)
        print("✅ Saved: langgraph.png")
    else:
        with open("langgraph.mmd", "w", encoding="utf-8") as f:
            f.write(payload)
        print("⚠️ PNG failed → Saved Mermaid: langgraph.mmd")
