import argparse
import os
import time
import json
import hashlib
from math import ceil
from datetime import timedelta
from typing import List, Dict

from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

from .retriever import build_embeddings

# 파일의 SHA-256 해시값(고유 지문)을 계산하는 함수
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# 지식 파일(예: Oracle 오류 PDF, 벡터 DB, 문서 세트 등)의 목록과 메타데이터를 로드하는 함수
def load_manifest(db_dir: str) -> Dict:
    path = os.path.join(db_dir, "manifest.json")
    if not os.path.exists(path):
        return {"files": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# 지식 파일을 저장하는 함수
def save_manifest(db_dir: str, manifest: Dict):
    os.makedirs(db_dir, exist_ok=True)
    path = os.path.join(db_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

# PDF 문서를 AI 학습이나 검색(RAG)에 사용할 수 있도록 “청크(chunk)” 단위로 분할하는 함수
def build_chunks_for_pdf(pdf_path: str, splitter: RecursiveCharacterTextSplitter) -> List[Document]:
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    chunks = splitter.split_documents(pages)
    for d in chunks:
        d.metadata = d.metadata or {}
        d.metadata.setdefault("source", os.path.basename(pdf_path))
    return chunks

# FAISS(벡터 검색 인덱스)를 새로 만들거나, 기존 인덱스를 불러오는 함수
def build_or_load_faiss(db_dir: str, embeddings) -> FAISS:
    return FAISS.load_local(db_dir, embeddings, allow_dangerous_deserialization=True)

# 여러 문서를 벡터 인덱싱(임베딩)할 때 진행 상태(progress)를 표시하며 처리하는 함수
def index_with_progress(all_chunks: List[Document], db_dir: str, embeddings, start_with_existing: bool, batch_size: int = 64):
    total = len(all_chunks)
    if total == 0:
        print("[INFO] No new chunks to index. Nothing to do.")
        return

    os.makedirs(db_dir, exist_ok=True)
    num_batches = (total + batch_size - 1) // batch_size
    print(f"[INFO] Building embeddings and updating FAISS index...")
    print(f"[INFO] Total NEW chunks: {total} | Batch size: {batch_size} | Batches: {num_batches}")

    start = time.time()
    vs = None

    if start_with_existing and os.path.exists(os.path.join(db_dir, "index.faiss")):
        vs = build_or_load_faiss(db_dir, embeddings)

    processed = 0
    for b in range(num_batches):
        s = b * batch_size
        e = min((b + 1) * batch_size, total)
        batch_docs = all_chunks[s:e]

        if vs is None:
            vs = FAISS.from_documents(batch_docs, embeddings)
        else:
            vs.add_documents(batch_docs)

        processed = e
        elapsed = time.time() - start
        est_total = (elapsed / processed) * total if processed > 0 else 0
        remaining = max(0.0, est_total - elapsed)
        percent = (processed / total) * 100.0
        print(f"[PROGRESS] {processed}/{total} ({percent:5.1f}%) | elapsed={timedelta(seconds=int(elapsed))} | eta={timedelta(seconds=int(remaining))}")

    vs.save_local(db_dir)
    total_elapsed = time.time() - start
    print(f"[INFO] Saved/updated FAISS index in {db_dir}. Added chunks: {total}")
    print(f"[INFO] Total time: {timedelta(seconds=int(total_elapsed))}")


def main(pdf_dir: str, db_dir: str, batch_size: int, rebuild: bool, merge: bool):
    os.makedirs(db_dir, exist_ok=True)

    manifest = load_manifest(db_dir)
    known = {f["hash"]: f for f in manifest.get("files", [])}

    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)

    pdf_files = [os.path.join(pdf_dir, f) for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"[WARN] No PDF files found in: {pdf_dir}")
        return

    if rebuild:
        print("[INFO] Rebuild mode: existing index will be overwritten.")
        manifest = {"files": []}
        known = {}

    if os.path.exists(os.path.join(db_dir, "index.faiss")):
        if rebuild:
            print("[INFO] Existing FAISS index found but will be replaced.")
        elif merge:
            print("[INFO] Existing FAISS index found. MERGE mode enabled (only new PDFs will be indexed).")
        else:
            print("[INFO] Existing FAISS index found. No merge requested; exiting.")
            return
    else:
        print("[INFO] No existing FAISS index. A new one will be created.")

    new_chunks: List[Document] = []
    to_add_files = []

    for i, path in enumerate(sorted(pdf_files)):
        file_hash = sha256_file(path)
        base = os.path.basename(path)

        if not rebuild and merge and file_hash in known:
            print(f"[SKIP] {base}: already indexed (hash matched).")
            continue

        print(f"[INFO] [{i+1}/{len(pdf_files)}] Loading & chunking: {base}")
        chunks = build_chunks_for_pdf(path, splitter)
        for d in chunks:
            d.metadata["file_hash"] = file_hash
        new_chunks.extend(chunks)
        to_add_files.append({"name": base, "hash": file_hash, "chunks": len(chunks)})

    print(f"[INFO] Split complete. NEW chunks to add: {len(new_chunks)}")

    embeddings = build_embeddings()
    start_with_existing = (not rebuild) and os.path.exists(os.path.join(db_dir, "index.faiss"))
    index_with_progress(new_chunks, db_dir, embeddings, start_with_existing=start_with_existing, batch_size=batch_size)

    for f in to_add_files:
        manifest["files"] = [x for x in manifest.get("files", []) if x["hash"] != f["hash"]]
        manifest["files"].append({
            "name": f["name"],
            "hash": f["hash"],
            "chunks": f["chunks"],
            "added_at": int(time.time()),
        })
    save_manifest(db_dir, manifest)

    print(f"[INFO] Manifest updated. Total files indexed: {len(manifest['files'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf_dir", required=True)
    parser.add_argument("--db_dir", required=True)
    parser.add_argument("--batch_size", type=int, default=64, help="Embedding batch size (default: 64)")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the whole index from scratch (ignore existing index/manifest).")
    parser.add_argument("--merge", action="store_true", help="Merge: add only new PDFs that have not been indexed yet.")
    args = parser.parse_args()

    merge = args.merge or True
    rebuild = args.rebuild or False

    main(args.pdf_dir, args.db_dir, batch_size=args.batch_size, rebuild=rebuild, merge=merge)
