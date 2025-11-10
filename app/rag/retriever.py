"""FAISS retriever utilities.
- build_embeddings(): returns an Azure OpenAI embedding function
- retrieve(query, db_dir, k): loads FAISS and returns top-k Documents
"""
from typing import List
import os

from langchain_community.vectorstores import FAISS
from langchain_openai import AzureOpenAIEmbeddings
from langchain_core.documents import Document

from ..settings import (
    AOAI_ENDPOINT,
    AOAI_API_KEY,
    AOAI_DEPLOY_EMBED_3_LARGE,
    AZURE_OPENAI_API_VERSION,
)

# 텍스트 데이터를 벡터(embedding)로 변환해주는 함수
def build_embeddings() -> AzureOpenAIEmbeddings:
    # settings.py에서 1차 검증했지만 혹시 모를 상황을 위해 재확인
    if not AOAI_ENDPOINT or not AOAI_API_KEY or not AOAI_DEPLOY_EMBED_3_LARGE:
        raise RuntimeError(
            "[retriever] Azure OpenAI credentials or deployment name missing. "
            "Check .env and app/settings.py."
        )
    return AzureOpenAIEmbeddings(
        azure_endpoint=AOAI_ENDPOINT,
        api_key=AOAI_API_KEY,
        model=AOAI_DEPLOY_EMBED_3_LARGE,   # '배포 이름'(Deployment name)
        api_version=AZURE_OPENAI_API_VERSION,
    )

# 지식 검색 단계(retrieval step) 를 수행하는 함수
def retrieve(query: str, db_dir: str, k: int = 5) -> List[Document]:
    if not os.path.exists(os.path.join(db_dir, "index.faiss")):
        raise FileNotFoundError(f"FAISS index not found in {db_dir}. Run ingest first.")
    embeddings = build_embeddings()
    vs = FAISS.load_local(db_dir, embeddings, allow_dangerous_deserialization=True)
    docs = vs.similarity_search(query, k=k)
    return docs
