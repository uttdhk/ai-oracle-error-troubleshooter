# app/settings.py
"""
Centralized settings/env loader.
- Force-load .env from project root even when running as a module
- Provide clear validation errors if Azure OpenAI credentials are missing
"""
import os
from pathlib import Path

# 1) .env 강제 로드 (프로젝트 루트: app 상위 폴더)
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent   # <repo>/ai-oracle-error-troubleshooter/app -> parent = <repo>/ai-oracle-error-troubleshooter
    DOTENV_PATH = PROJECT_ROOT / ".env"
    if DOTENV_PATH.exists():
        load_dotenv(DOTENV_PATH.as_posix())  # 경로 명시
except Exception:
    # python-dotenv 미설치 또는 기타 이슈시 조용히 진행 (아래 validation이 잡아줌)
    pass

# 2) 환경변수 읽기
AOAI_ENDPOINT = os.getenv("AOAI_ENDPOINT", "").strip()
AOAI_API_KEY = os.getenv("AOAI_API_KEY", "").strip()
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview").strip()

# 모델 배포명(Deployment name)
AOAI_DEPLOY_GPT4O = os.getenv("AOAI_DEPLOY_GPT4O", "gpt-4o").strip()
AOAI_DEPLOY_GPT4O_MINI = os.getenv("AOAI_DEPLOY_GPT4O_MINI", "gpt-4o-mini").strip()
AOAI_DEPLOY_EMBED_3_LARGE = os.getenv("AOAI_DEPLOY_EMBED_3_LARGE", "text-embedding-3-large").strip()

# OpenAI SDK 호환(일부 내부 경로에서 필요할 수 있음)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", AOAI_ENDPOINT).strip()
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", AOAI_API_KEY).strip()

# 3) 기본 검증 + 친절 메시지
missing = []
if not AOAI_ENDPOINT:
    missing.append("AOAI_ENDPOINT")
if not AOAI_API_KEY:
    missing.append("AOAI_API_KEY")
if not AOAI_DEPLOY_EMBED_3_LARGE:
    missing.append("AOAI_DEPLOY_EMBED_3_LARGE (Azure '임베딩' Deployment name)")
# GPT 모델은 스트림릿/서버에서만 필요할 수 있으니 임베딩 우선 확인

if missing:
    hint = (
        "환경변수(.env)를 확인하세요. 예시:\n"
        "AOAI_ENDPOINT=https://<your-aoai-endpoint>.openai.azure.com/\n"
        "AOAI_API_KEY=<your-aoai-api-key>\n"
        "AZURE_OPENAI_API_VERSION=2024-08-01-preview\n"
        "AOAI_DEPLOY_EMBED_3_LARGE=text-embedding-3-large  # Azure 포털의 '배포 이름'\n"
    )
    # 개발 중에는 메시지를 바로 보이게
    raise RuntimeError(f"[settings] Missing required variables: {', '.join(missing)}\n{hint}")
