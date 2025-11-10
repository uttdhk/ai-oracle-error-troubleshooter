
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.agents.supervisor import run_pipeline

app = FastAPI(title="Debate Arena API", description="AI Oracle Error Troubleshooter API", version="0.1.0")

class Req(BaseModel):
    query: str
    db_dir: str
    strict: bool = True
    allow_web: bool = False
    locale: Optional[str] = "en"  # 🔹 추가: 응답 언어 기본값 영어

# 사용자 입력(오류 메시지/상황)을 받아 원인 분석 → 자료 검색 → 해결책 제시까지 한 번에 처리하는 “문제 해결 오케스트레이터” 역할의 함수
@app.post("/troubleshoot")
def troubleshoot(req: Req):
    out = run_pipeline(
        user_input=req.query,
        db_dir=req.db_dir,
        thread_id=None,
        strict=req.strict,
        allow_web=req.allow_web
    )
    # charset 명시
    return JSONResponse(content=out, media_type="application/json; charset=utf-8")