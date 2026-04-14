"""
index.py — Build RAG Index for Day 09 Lab
Reads docs from data/docs/, embeds with OpenAI text-embedding-3-small,
and stores into ChromaDB collection 'day09_docs'.

Run:
    python index.py
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DOCS_DIR = Path(__file__).parent / "data" / "docs"
CHROMA_DB_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "day09_docs"
CHUNK_SIZE_CHARS = 1600   # ~400 tokens
OVERLAP_CHARS = 200


def get_embedding(text: str) -> list:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.embeddings.create(input=text, model="text-embedding-3-small")
    return response.data[0].embedding


def preprocess(raw: str, filepath: str) -> dict:
    lines = raw.strip().split("\n")
    metadata = {
        "source": Path(filepath).name,
        "department": "unknown",
        "effective_date": "unknown",
        "access": "internal",
        "section": "",
    }
    content_lines = []
    header_done = False
    for line in lines:
        if not header_done:
            if line.startswith("Source:"):
                metadata["source"] = line.replace("Source:", "").strip()
            elif line.startswith("Department:"):
                metadata["department"] = line.replace("Department:", "").strip()
            elif line.startswith("Effective Date:"):
                metadata["effective_date"] = line.replace("Effective Date:", "").strip()
            elif line.startswith("Access:"):
                metadata["access"] = line.replace("Access:", "").strip()
            elif line.startswith("==="):
                header_done = True
                content_lines.append(line)
            elif line.strip() == "" or line.isupper():
                continue
        else:
            content_lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(content_lines))
    return {"text": text, "metadata": metadata}


def chunk(doc: dict) -> list:
    text = doc["text"]
    base_meta = doc["metadata"].copy()
    chunks = []
    sections = re.split(r"(===.*?===)", text)
    current_section = "General"
    current_text = ""

    for part in sections:
        if re.match(r"===.*?===", part):
            if current_text.strip():
                chunks.extend(_split(current_text.strip(), base_meta, current_section))
            current_section = part.strip("= ").strip()
            current_text = ""
        else:
            current_text += part

    if current_text.strip():
        chunks.extend(_split(current_text.strip(), base_meta, current_section))

    return chunks


def _split(text: str, base_meta: dict, section: str) -> list:
    if len(text) <= CHUNK_SIZE_CHARS:
        return [{"text": text, "metadata": {**base_meta, "section": section}}]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE_CHARS, len(text))
        chunks.append({"text": text[start:end], "metadata": {**base_meta, "section": section}})
        start = end - OVERLAP_CHARS
    return chunks


def build_index():
    import chromadb
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))

    # Delete and recreate for clean index
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted existing collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    total = 0
    for filepath in sorted(DOCS_DIR.glob("*.txt")):
        print(f"  Indexing: {filepath.name}")
        raw = filepath.read_text(encoding="utf-8")
        doc = preprocess(raw, str(filepath))
        chunks = chunk(doc)
        for i, c in enumerate(chunks):
            chunk_id = f"{filepath.stem}_{i}"
            embedding = get_embedding(c["text"])
            collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[c["text"]],
                metadatas=[c["metadata"]],
            )
        print(f"    → {len(chunks)} chunks")
        total += len(chunks)

    print(f"\nDone! Total chunks indexed: {total}")
    print(f"Collection: '{COLLECTION_NAME}' at {CHROMA_DB_DIR}")
    return total


if __name__ == "__main__":
    print("=" * 50)
    print("Day 09 — Build RAG Index")
    print("=" * 50)
    n = build_index()

    # Quick verify
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    col = client.get_collection(COLLECTION_NAME)
    print(f"\nVerify: collection has {col.count()} chunks")
    sample = col.get(limit=3, include=["documents", "metadatas"])
    for doc, meta in zip(sample["documents"], sample["metadatas"]):
        print(f"  [{meta.get('source')}] {doc[:80]}...")
