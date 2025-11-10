from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from ..settings import AOAI_ENDPOINT, AOAI_API_KEY, AOAI_DEPLOY_GPT4O, AZURE_OPENAI_API_VERSION
import re  # 정규표현식(Regular Expression) 기능을 사용하기 위한 표준 라이브러리를 불러오는 코드

STRICT_PROMPT_EN = (
    "Use ONLY local context tags [R#]. Write concise, step-by-step guidance. "
    "Each action/verification line must end with its evidence tag like [R1]. "
    "Write in English."
)
ASSIST_PROMPT_WITH_WEB_EN = (
    "Prefer local context [R#], and you MAY use [W#] if provided. "
    "Each action/verification line must end with its evidence tag like [R1] or [W1]. "
    "Write in English."
)

STRICT_PROMPT_KO = (
    "로컬 근거 태그 [R#]만 사용하여 간결한 단계별 가이드를 작성하세요. "
    "각 조치/검증 줄 끝에는 반드시 [R1] 형태의 근거 태그를 포함하세요. "
    "한국어로 작성하세요."
)
ASSIST_PROMPT_WITH_WEB_KO = (
    "로컬 근거 [R#]를 우선 사용하되, 제공된 경우 [W#]도 사용할 수 있습니다. "
    "각 조치/검증 줄 끝에는 [R1] 또는 [W1] 형태의 근거 태그를 반드시 포함하세요. "
    "한국어로 작성하세요."
)

def _system_prompt(strict: bool, has_web: bool, locale: str) -> str:
    """언어(locale)에 따라 프롬프트를 구성하고, 반드시 해당 언어로 답하도록 명시."""
    if locale.lower() == "ko":
        base_prompt = STRICT_PROMPT_KO if (strict and not has_web) else ASSIST_PROMPT_WITH_WEB_KO
        lang_hint = "\n\n모든 응답은 반드시 한국어로 작성하세요."
    else:
        base_prompt = STRICT_PROMPT_EN if (strict and not has_web) else ASSIST_PROMPT_WITH_WEB_EN
        lang_hint = "\n\nYou must respond **only in English**. Do not include Korean."

    return base_prompt + lang_hint

def _strip_unreferenced_lines(md: str) -> str:
    # 필요시 [R#]/[W#] 미포함 줄 제거 로직을 여기에 추가
    return md

def run(
    model: str,
    user_input: str,
    causes_json: Dict[str, Any],
    retrieved_context: str,
    *,
    strict: bool = True,
    web_context: str = "",
    locale: str = "en",  # 🔹 추가: 'ko'이면 한국어 본문
) -> str:
    llm = AzureChatOpenAI(
        azure_endpoint=AOAI_ENDPOINT,
        api_key=AOAI_API_KEY,
        model=model or AOAI_DEPLOY_GPT4O,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0.1 if (strict and not web_context) else 0.2,
    )
    system_prompt = _system_prompt(strict, bool(web_context), locale)

    ctx = f"Local context:\n{retrieved_context or '(empty)'}\n"
    if web_context:
        ctx += f"\n---\nWeb context:\n{web_context}\n"

    # 🔸 결과 언어 보장 문구(추가 안전장치)
    lang_hint = "모든 본문은 반드시 한국어로 작성하세요." if locale == "ko" else "Write the entire answer in English."

    msgs = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=(
            f"{lang_hint}\n\n"
            f"User input:\n{user_input}\n\n"
            f"Causes JSON:{causes_json}\n\n"
            f"{ctx}\n"
            "Write a Markdown guide with these sections:\n"
            "- 요약(Summary)\n- 권장 조치(Recommended Actions)\n- 검증 방법(Verification)\n- 참고(References)\n"
            "Every action/verification bullet MUST end with its evidence tag like [R1] or [W1]."
        )),
    ]
    resp = llm.invoke(msgs)
    md = resp.content or ""
    return _strip_unreferenced_lines(md)
