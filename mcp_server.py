import sqlite3
from pathlib import Path
from typing import Optional
import fastmcp

DB_PATH = Path("C:/procurement-mcp/db/knowledge_base.db")

mcp = fastmcp.FastMCP(
    name="procurement-knowledge-base",
    instructions="You are connected to a procurement document knowledge base. Use tools to retrieve and reason over invoices, purchase orders, shipping orders, inventory reports, and contracts. Always include source references.",
)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def snippet(text, max_chars=300):
    if not text:
        return ""
    return text[:max_chars].strip() + ("..." if len(text) > max_chars else "")

@mcp.tool()
def search_documents(query: str, category: Optional[str] = None) -> dict:
    """Full-text search across all documents. Category filter: invoices, purchase_orders, shipping_orders, inventory_reports, contracts."""
    conn = get_conn()
    try:
        if category:
            rows = conn.execute("SELECT d.id, d.filename, d.category, d.order_id, d.vendor, d.doc_date, d.amount, d.raw_text FROM documents_fts f JOIN documents d ON d.id = f.id WHERE documents_fts MATCH ? AND d.category = ? LIMIT 10", (query, category)).fetchall()
        else:
            rows = conn.execute("SELECT d.id, d.filename, d.category, d.order_id, d.vendor, d.doc_date, d.amount, d.raw_text FROM documents_fts f JOIN documents d ON d.id = f.id WHERE documents_fts MATCH ? LIMIT 10", (query,)).fetchall()
        results = [{"source": dict(r)["filename"], "category": dict(r)["category"], "order_id": dict(r)["order_id"], "vendor": dict(r)["vendor"], "date": dict(r)["doc_date"], "excerpt": snippet(dict(r)["raw_text"])} for r in rows]
        return {"query": query, "count": len(results), "results": results}
    finally:
        conn.close()

@mcp.tool()
def get_document(doc_id: str) -> dict:
    """Retrieve full text and metadata for a document by its ID (e.g. invoices/invoice_10248)."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return {"error": f"Not found: {doc_id}"}
        d = dict(row)
        return {"source": d["filename"], "category": d["category"], "order_id": d["order_id"], "vendor": d["vendor"], "date": d["doc_date"], "amount": d["amount"], "has_matching_po": bool(d["has_matching_po"]), "has_matching_invoice": bool(d["has_matching_invoice"]), "has_matching_shipment": bool(d["has_matching_shipment"]), "full_text": d["raw_text"]}
    finally:
        conn.close()

@mcp.tool()
def match_order(order_id: str) -> dict:
    """Find all documents linked to a specific order ID across all categories."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, filename, category, vendor, doc_date, amount, has_matching_po, has_matching_invoice, has_matching_shipment, raw_text FROM documents WHERE order_id = ?", (order_id,)).fetchall()
        if not rows:
            return {"order_id": order_id, "found": False, "documents": []}
        docs = [{"source": dict(r)["filename"], "category": dict(r)["category"], "vendor": dict(r)["vendor"], "date": dict(r)["doc_date"], "amount": dict(r)["amount"], "has_matching_po": bool(dict(r)["has_matching_po"]), "has_matching_invoice": bool(dict(r)["has_matching_invoice"]), "has_matching_shipment": bool(dict(r)["has_matching_shipment"]), "excerpt": snippet(dict(r)["raw_text"])} for r in rows]
        cats = list({d["category"] for d in docs})
        missing = [c for c in ["invoices", "purchase_orders", "shipping_orders"] if c not in cats]
        return {"order_id": order_id, "found": True, "categories_found": cats, "missing_categories": missing, "documents": docs}
    finally:
        conn.close()

@mcp.tool()
def find_mismatches(doc_type: str) -> dict:
    """Find documents missing a counterpart. doc_type: invoices_without_po, pos_without_invoice, invoices_without_shipment, pos_without_shipment, unmatched_shipments."""
    queries = {
        "invoices_without_po": "SELECT filename, category, order_id, vendor, doc_date FROM documents WHERE category='invoices' AND has_matching_po=0",
        "pos_without_invoice": "SELECT filename, category, order_id, vendor, doc_date FROM documents WHERE category='purchase_orders' AND has_matching_invoice=0",
        "invoices_without_shipment": "SELECT filename, category, order_id, vendor, doc_date FROM documents WHERE category='invoices' AND has_matching_shipment=0",
        "pos_without_shipment": "SELECT filename, category, order_id, vendor, doc_date FROM documents WHERE category='purchase_orders' AND has_matching_shipment=0",
        "unmatched_shipments": "SELECT filename, category, order_id, vendor, doc_date FROM documents WHERE category='shipping_orders' AND has_matching_invoice=0 AND has_matching_po=0",
    }
    if doc_type not in queries:
        return {"error": f"Unknown type. Choose from: {list(queries.keys())}"}
    conn = get_conn()
    try:
        rows = conn.execute(queries[doc_type]).fetchall()
        return {"mismatch_type": doc_type, "count": len(rows), "documents": [{"source": dict(r)["filename"], "category": dict(r)["category"], "order_id": dict(r)["order_id"], "vendor": dict(r)["vendor"], "date": dict(r)["doc_date"]} for r in rows]}
    finally:
        conn.close()

@mcp.tool()
def list_inventory_periods() -> dict:
    """List all inventory reports and the time periods they cover."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT filename, period, doc_date, raw_text FROM documents WHERE category='inventory_reports' ORDER BY period ASC").fetchall()
        reports = [{"source": dict(r)["filename"], "period": dict(r)["period"], "excerpt": snippet(dict(r)["raw_text"], 200)} for r in rows]
        periods = [r["period"] for r in reports if r["period"]]
        return {"count": len(reports), "date_range": f"{min(periods)} to {max(periods)}" if periods else "unknown", "reports": reports}
    finally:
        conn.close()

@mcp.tool()
def get_contract_terms(query: str) -> dict:
    """Search for terms or clauses within contracts."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT d.id, d.filename, d.vendor, d.doc_date, d.raw_text FROM documents_fts f JOIN documents d ON d.id = f.id WHERE documents_fts MATCH ? AND d.category='contracts' LIMIT 5", (query,)).fetchall()
        if not rows:
            rows = conn.execute("SELECT id, filename, vendor, doc_date, raw_text FROM documents WHERE category='contracts' AND lower(raw_text) LIKE lower(?) LIMIT 5", (f"%{query}%",)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            text = d["raw_text"] or ""
            idx = text.lower().find(query.lower())
            passage = ("..." + text[max(0,idx-100):min(len(text),idx+400)].strip() + "...") if idx >= 0 else snippet(text, 400)
            results.append({"source": d["filename"], "vendor": d["vendor"], "date": d["doc_date"], "passage": passage})
        return {"query": query, "count": len(results), "results": results}
    finally:
        conn.close()

@mcp.tool()
def get_related_documents(doc_id: str) -> dict:
    """Find all documents related to a given document via shared order ID."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT order_id, filename, category FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return {"error": f"Document not found: {doc_id}"}
        d = dict(row)
        order_id = d["order_id"]
        if not order_id:
            return {"doc_id": doc_id, "source": d["filename"], "order_id": None, "message": "No order ID — cannot find related documents.", "related": []}
        rows = conn.execute("SELECT id, filename, category, vendor, doc_date, amount FROM documents WHERE order_id = ? AND id != ?", (order_id, doc_id)).fetchall()
        related = [{"source": dict(r)["filename"], "doc_id": dict(r)["id"], "category": dict(r)["category"], "vendor": dict(r)["vendor"], "date": dict(r)["doc_date"], "amount": dict(r)["amount"]} for r in rows]
        return {"doc_id": doc_id, "source": d["filename"], "order_id": order_id, "related_count": len(related), "related": related}
    finally:
        conn.close()

@mcp.tool()
def search_by_vendor(vendor_name: str) -> dict:
    """Find all documents related to a specific vendor or supplier name (partial match supported)."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, filename, category, order_id, vendor, doc_date, amount, raw_text FROM documents WHERE lower(vendor) LIKE lower(?) ORDER BY category, doc_date", (f"%{vendor_name}%",)).fetchall()
        fts_rows = conn.execute("SELECT d.id, d.filename, d.category, d.order_id, d.vendor, d.doc_date, d.amount, d.raw_text FROM documents_fts f JOIN documents d ON d.id = f.id WHERE documents_fts MATCH ?", (vendor_name,)).fetchall()
        seen = set()
        results = []
        for r in list(rows) + list(fts_rows):
            d = dict(r)
            if d["id"] not in seen:
                seen.add(d["id"])
                results.append({"source": d["filename"], "doc_id": d["id"], "category": d["category"], "order_id": d["order_id"], "vendor": d["vendor"], "date": d["doc_date"], "amount": d["amount"], "excerpt": snippet(d["raw_text"], 200)})
        return {"vendor_query": vendor_name, "count": len(results), "results": results}
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run()