"""Error Analyzer agent.
- Always returns a strict JSON via structured output (Pydantic).
- Output: {"causes": [str, ...], "notes": str}
"""
from typing import Dict, Any, List
from pydantic import BaseModel, Field  # 입력 데이터를 “검증된 형태의 객체”로 바꿔주는 도구
from langchain_openai import AzureChatOpenAI # LLM(대형 언어 모델)을 “조립해서 응용”하기 위한 파이썬 프레임워크
from langchain_core.messages import SystemMessage, HumanMessage # “대화 메시지(Message)” 구조를 정의하는 핵심 모듈
from ..settings import AOAI_ENDPOINT, AOAI_API_KEY, AOAI_DEPLOY_GPT4O, AZURE_OPENAI_API_VERSION

# 클래스 정의: CausesModel — 데이터/동작을 묶는 청사진
class CausesModel(BaseModel):
    causes: List[str] = Field(default_factory=list, description="Short bullet reasons")
    notes: str = Field(default="", description="One-line note")

def _sys_prompt(locale: str) -> str:
    # locale에 따라 설명 언어만 바뀌고, JSON 키(causes/notes)는 유지
    if locale == "ko":
        return (
            "당신은 시니어 Oracle DBA입니다.\n"
            "사용자 입력과 로컬 Oracle 문서 발췌를 바탕으로 간결한 근본 원인을 생성하세요.\n"
            "추측은 피하고 제공된 문맥에만 근거하세요. 최대 4개 불릿으로 작성합니다.\n"
            "반드시 다음 JSON 구조만 출력하세요: {\"causes\": [문장들], \"notes\": \"한 줄 메모\"}\n"
            "모든 문장은 한국어로 작성하세요."
        )
    return (
        "You are a senior Oracle DBA.\n"
        "Given the user's error text and retrieved Oracle doc snippets, produce concise root causes.\n"
        "Avoid speculation; stick to provided context. Max 4 bullets.\n"
        "You must output only this JSON: {\"causes\": [sentences], \"notes\": \"one line note\"}\n"
        "Write in English."
    )

def run(
    model: str,
    user_input: str,
    retrieved_context: str,
    *,
    strict: bool = True,
    locale: str = "en",  # 🔹 추가: 'ko'이면 한국어 설명
) -> Dict[str, Any]:
    # temperature 낮게 + JSON 강제
    llm = AzureChatOpenAI(
        azure_endpoint=AOAI_ENDPOINT,
        api_key=AOAI_API_KEY,
        model=model or AOAI_DEPLOY_GPT4O,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0.0,
    )
    structured = llm.with_structured_output(CausesModel)

    msgs = [
        SystemMessage(content=_sys_prompt(locale)),
        HumanMessage(content=(
            "User error:\n"
            f"{user_input}\n\n"
            "Retrieved Oracle snippets (may be empty):\n"
            f"{(retrieved_context or '')[:8000]}\n"
        ))
    ]

    try:
        obj: CausesModel = structured.invoke(msgs)
        data = obj.model_dump()
    except Exception:
        data = {"causes": [], "notes": "Parser failed; please refine input or context."}

    # 빈 결과일 때 최소 힌트라도 제공
    if not data.get("causes"):
        import re
        m = re.findall(r"(ORA-\d{5})", user_input or "")
        if m:
            if locale == "ko":
                data["causes"] = [f"{m[0]} 오류가 발생했습니다. 문서의 네트워크/인증 설정을 확인하세요."]
                data.setdefault("notes", "로컬 문맥에서 강한 근거를 찾지 못해 일반 힌트를 제시했습니다.")
            else:
                data["causes"] = [f"{m[0]} occurred. Check sqlnet/auth settings and network per docs."]
                data.setdefault("notes", "No strong evidence in retrieved context; using generic hint.")
    return data
