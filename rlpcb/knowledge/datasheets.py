"""Fetch datasheets (PDF) into the knowledge base."""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
import urllib.request
from typing import Dict

from ..config import data_dir

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RLPCB/0.1"


def _download(url: str, dest_dir: str, name_hint: str = "") -> str:
    os.makedirs(dest_dir, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "")
        final = r.geturl()
    if not data.startswith(b"%PDF"):
        # many vendor links land on an HTML page that links the PDF
        html = data.decode("utf-8", errors="replace")
        m = re.search(r'href="([^"]+\.pdf[^"]*)"', html, re.I)
        if not m:
            raise RuntimeError(f"Not a PDF ({ctype}) and no PDF link found at {final}")
        link = urllib.parse.urljoin(final, m.group(1))
        return _download(link, dest_dir, name_hint)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", name_hint or os.path.basename(final.split("?")[0]) or "datasheet")
    if not stem.lower().endswith(".pdf"):
        stem += ".pdf"
    path = os.path.join(dest_dir, f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{stem}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def fetch_and_ingest(kb, url: str, focus: str, name_hint: str = "") -> Dict:
    import urllib.parse  # noqa: F401  (used by _download)
    try:
        path = _download(url, os.path.join(data_dir(), "datasheets"), name_hint)
    except Exception as e:  # noqa
        return {"error": f"Could not download {url}: {e}",
                "workaround": "Open the link in your browser, save the PDF into a folder (e.g. Documents\\Datasheets) "
                              "and ask me to ingest_documents that folder."}
    stats = kb.ingest_files([path], source="datasheet")
    hits = [h for h in kb.search(focus, limit=12, source="datasheet") if os.path.basename(path) == h["file"]][:6]
    return {"saved": path, "ingest": stats, "relevant_pages": hits,
            "tip": "Ask about any section: the datasheet is now searchable (search_knowledge source='datasheet')."}
