"""Engineering knowledge base: curated guides + the user's own books, app notes and datasheets.

Documents are split into sections (Markdown headings / PDF pages) and indexed
with SQLite FTS5 (BM25). Sources: ``knowledge/guides`` shipped with RL PCB,
``knowledge/checklists``, and any folder the user ingests (PDF, MD, TXT, HTML).
"""
from __future__ import annotations

import glob
import hashlib
import html
import os
import re
import sqlite3
import subprocess
from typing import Dict, Iterable, List, Optional

from ..config import data_dir, knowledge_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, kind TEXT, digest TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, doc_id INTEGER, heading TEXT, loc TEXT, text TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(heading, text, title, tokenize='porter unicode61');
"""

_STOP = {"the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "with", "how", "what", "why", "is", "are", "do",
         "i", "my", "we", "should", "can", "be", "it", "this", "that", "at", "by", "from", "as", "does", "which"}


class KnowledgeBase:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(data_dir(), "knowledge.db")
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------ ingest
    def ensure_builtin(self):
        """Index the shipped guides (fast; skips unchanged files)."""
        files = glob.glob(os.path.join(knowledge_dir(), "**", "*.md"), recursive=True)
        return self.ingest_files(files, source="builtin")

    def ingest_folder(self, folder: str, source: str = "user") -> Dict[str, int]:
        exts = (".pdf", ".md", ".txt", ".html", ".htm", ".markdown", ".rst")
        files = [p for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True) if p.lower().endswith(exts)]
        return self.ingest_files(files, source=source)

    def ingest_files(self, files: Iterable[str], source: str = "user") -> Dict[str, int]:
        stats = {"indexed": 0, "unchanged": 0, "failed": 0, "chunks": 0}
        cur = self.db.cursor()
        for path in files:
            try:
                digest = _digest(path)
                row = cur.execute("SELECT id, digest FROM docs WHERE path=?", (path,)).fetchone()
                if row and row["digest"] == digest:
                    stats["unchanged"] += 1
                    continue
                title, kind, chunks = extract(path)
                if not chunks:
                    stats["failed"] += 1
                    continue
                if row:
                    self._delete_doc(cur, row["id"])
                cur.execute("INSERT OR REPLACE INTO docs(path,title,kind,digest,source) VALUES(?,?,?,?,?)",
                            (path, title, kind, digest, source))
                doc_id = cur.lastrowid
                for heading, loc, text in chunks:
                    cur.execute("INSERT INTO chunks(doc_id,heading,loc,text) VALUES(?,?,?,?)", (doc_id, heading, loc, text))
                    cur.execute("INSERT INTO chunks_fts(rowid,heading,text,title) VALUES(?,?,?,?)",
                                (cur.lastrowid, heading, text, title))
                stats["indexed"] += 1
                stats["chunks"] += len(chunks)
            except Exception:  # noqa
                stats["failed"] += 1
        self.db.commit()
        return stats

    def _delete_doc(self, cur, doc_id):
        ids = [r[0] for r in cur.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()]
        for i in ids:
            cur.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
        cur.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        cur.execute("DELETE FROM docs WHERE id=?", (doc_id,))

    # ------------------------------------------------------------ query
    def search(self, query: str, limit: int = 6, source: Optional[str] = None, max_chars: int = 1800) -> List[dict]:
        toks = [t for t in re.findall(r"[A-Za-z0-9+.\-]+", query.lower()) if t not in _STOP and len(t) > 1]
        if not toks:
            return []
        # OR query ranked by BM25, headings weighted up
        q = " OR ".join(f'"{t}"' for t in toks)
        sql = ("SELECT c.id, c.heading, c.loc, c.text, d.title, d.path, d.source, bm25(chunks_fts, 4.0, 1.0, 2.0) AS s "
               "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid JOIN docs d ON d.id = c.doc_id "
               "WHERE chunks_fts MATCH ?")
        args: list = [q]
        if source:
            sql += " AND d.source = ?"
            args.append(source)
        sql += " ORDER BY s LIMIT ?"
        args.append(limit * 4)
        rows = self.db.execute(sql, args).fetchall()
        # boost chunks that contain more distinct query terms
        def cover(r):
            low = (r["heading"] + " " + r["text"]).lower()
            return sum(1 for t in set(toks) if t in low)
        rows = sorted(rows, key=lambda r: (-cover(r), r["s"]))[:limit]
        out = []
        for r in rows:
            text = r["text"]
            out.append({"title": r["title"], "section": r["heading"], "where": r["loc"],
                        "file": os.path.basename(r["path"]), "source": r["source"],
                        "text": text if len(text) <= max_chars else text[:max_chars] + " …"})
        return out

    def list_docs(self, source: Optional[str] = None) -> List[dict]:
        sql = "SELECT d.title, d.path, d.kind, d.source, COUNT(c.id) n FROM docs d LEFT JOIN chunks c ON c.doc_id=d.id"
        args = []
        if source:
            sql += " WHERE d.source=?"
            args.append(source)
        sql += " GROUP BY d.id ORDER BY d.source, d.title"
        return [{"title": r["title"], "file": os.path.basename(r["path"]), "kind": r["kind"], "source": r["source"],
                 "sections": r["n"]} for r in self.db.execute(sql, args).fetchall()]

    def read(self, file_or_title: str, section: Optional[str] = None, max_chars: int = 12000) -> dict:
        row = self.db.execute("SELECT * FROM docs WHERE path LIKE ? OR title LIKE ? LIMIT 1",
                              (f"%{file_or_title}%", f"%{file_or_title}%")).fetchone()
        if not row:
            return {"error": f"No document matching '{file_or_title}'"}
        chunks = self.db.execute("SELECT heading, loc, text FROM chunks WHERE doc_id=? ORDER BY id", (row["id"],)).fetchall()
        if section:
            chunks = [c for c in chunks if section.lower() in c["heading"].lower()] or chunks
        text = "\n\n".join(f"## {c['heading']}\n{c['text']}" for c in chunks)
        return {"title": row["title"], "file": os.path.basename(row["path"]),
                "sections": [c["heading"] for c in self.db.execute("SELECT heading FROM chunks WHERE doc_id=? ORDER BY id", (row["id"],))],
                "text": text[:max_chars] + (" …(truncated; ask for a section)" if len(text) > max_chars else "")}


# ---------------------------------------------------------------- extraction
def _digest(path: str) -> str:
    h = hashlib.sha1()
    st = os.stat(path)
    h.update(f"{st.st_size}-{st.st_mtime}".encode())
    return h.hexdigest()


def extract(path: str):
    low = path.lower()
    if low.endswith(".pdf"):
        return _extract_pdf(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if low.endswith((".html", ".htm")):
        text = _html_to_text(text)
    return _split_markdown(path, text)


def _split_markdown(path: str, text: str, max_len: int = 2500):
    title = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta_tags = ""
    if fm:
        t = re.search(r"^title:\s*(.+)$", fm.group(1), re.M)
        if t:
            title = t.group(1).strip().strip('"')
        tg = re.search(r"^tags:\s*(.+)$", fm.group(1), re.M)
        meta_tags = tg.group(1) if tg else ""
        text = text[fm.end():]
    chunks = []
    heading = title
    buf: List[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            for i in range(0, len(body), max_len):
                part = body[i:i + max_len]
                chunks.append((heading if i == 0 else f"{heading} (cont.)", "", (meta_tags + "\n" if i == 0 and meta_tags else "") + part))
    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            buf = []
            heading = m.group(2).strip()
        else:
            buf.append(line)
    flush()
    return title, "markdown", chunks


def _extract_pdf(path: str):
    title = os.path.splitext(os.path.basename(path))[0]
    pages: List[str] = []
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            if doc.metadata and doc.metadata.get("title"):
                title = doc.metadata["title"] or title
            pages = [p.get_text() for p in doc]
    except ImportError:
        try:
            from pypdf import PdfReader

            r = PdfReader(path)
            pages = [(p.extract_text() or "") for p in r.pages]
        except ImportError:
            try:
                out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=300).stdout
                pages = out.split("\f")
            except (OSError, subprocess.SubprocessError):
                pages = []
    chunks = []
    for i, t in enumerate(pages):
        t = re.sub(r"[ \t]+", " ", t).strip()
        if len(t) < 40:
            continue
        head = next((ln.strip() for ln in t.splitlines() if len(ln.strip()) > 8), f"page {i+1}")[:120]
        for j in range(0, len(t), 2500):
            chunks.append((head, f"page {i+1}", t[j:j + 2500]))
    return title, "pdf", chunks


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<h([1-4])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", s)
    s = re.sub(r"(?i)</h[1-4]>", "\n", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s)
