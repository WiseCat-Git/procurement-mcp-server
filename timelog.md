# Time Log — Procurement MCP Take-Home Exercise

Total budget: ~3–5 hours (per spec)

---

## Session 1 — 2026-06-12

| Task | Notes |
|---|---|
| Dataset audit (ls, file inventory, format analysis) | Identified 2 formats, order ID join key, intentional mismatches |
| Architecture design & stack decisions | SQLite FTS5 over vector DB, pdfplumber + OCR routing |
| Environment setup (Python, venv, dependencies, Tesseract) | py launcher issue, Tesseract PATH fix |
| `pipeline.py` — ingestion, OCR, field extraction, SQLite, FTS5, relationship materialization | First run: 45 docs, mismatch report correct |
| `mcp_server.py` — 6 MCP tools | stdout→stderr fix for Claude Desktop compatibility |
| Claude Desktop connection | Store app config path discovery, DXT extension manifest |
| Tested: "Which invoices are missing a PO?" + "What supports order 10687?" | Both answered correctly with source references |
| `requirements.txt` + `README.md` | Architecture, tradeoffs, known limitations, AI usage |

**Session total: ~1h 50min**

---

## Session 2 — 2026-06-15

Start time: 08:03 AM
End time: 08:27 AM

| Task | Notes |
|---|---|
| Added `get_related_documents` tool | Exposes document_links via shared order_id |
| Added `search_by_vendor` tool | Structured + FTS hybrid vendor search |
| Wrote `test_tools.py` | 14/14 tests passing |
| Pushed to GitHub | https://github.com/WiseCat-Git/procurement-mcp-server |

**Session total: ~25min**

---

## Running total

| Session | Date | Duration |
|---|---|---|
| Session 1 | 2026-06-12 | 1h 50min |
| Session 2 | 2026-06-15 | 25min |
| **Total** | | **~2h 15min** |