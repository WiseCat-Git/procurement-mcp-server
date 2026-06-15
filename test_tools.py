"""
test_tools.py — Programmatic validation of all MCP tools

Imports the tool functions directly from mcp_server and runs
a test case for each one. No MCP client needed.

Usage:
    python test_tools.py

Expected: all 8 tests pass with PASS prefix.
"""

import sys
import json
from pathlib import Path

# ── Point to the correct DB before importing server ───────────────────────────
# mcp_server uses an absolute path so this is just a safety check
DB_PATH = Path("C:/procurement-mcp/db/knowledge_base.db")
if not DB_PATH.exists():
    # Fallback: try relative path (when running from project folder)
    DB_PATH = Path("db/knowledge_base.db")
    if not DB_PATH.exists():
        print("ERROR: knowledge_base.db not found. Run pipeline.py first.")
        sys.exit(1)

# ── Import tools directly from mcp_server ────────────────────────────────────
sys.path.insert(0, str(Path("C:/procurement-mcp")))
from mcp_server import (
    search_documents,
    get_document,
    match_order,
    find_mismatches,
    list_inventory_periods,
    get_contract_terms,
    get_related_documents,
    search_by_vendor,
)

# ── Test runner ───────────────────────────────────────────────────────────────

passed = 0
failed = 0

def run_test(name: str, result: dict, assertion_fn):
    global passed, failed
    try:
        assertion_fn(result)
        print(f"  PASS  {name}")
        passed += 1
    except AssertionError as e:
        print(f"  FAIL  {name} — {e}")
        print(f"        Result: {json.dumps(result, indent=2)[:300]}")
        failed += 1

# ── Tests ─────────────────────────────────────────────────────────────────────

print("\n── search_documents ──────────────────────────────────────────")

result = search_documents("Hungry Owl")
run_test(
    "search_documents: finds vendor by name",
    result,
    lambda r: r["count"] > 0 and any("Hungry" in (d.get("excerpt") or "") or "Hungry" in (d.get("vendor") or "") for d in r["results"])
)

result = search_documents("invoice", category="invoices")
run_test(
    "search_documents: category filter works",
    result,
    lambda r: all(d["category"] == "invoices" for d in r["results"])
)

print("\n── get_document ──────────────────────────────────────────────")

result = get_document("invoices/invoice_10248")
run_test(
    "get_document: retrieves known invoice",
    result,
    lambda r: r.get("order_id") == "10248" and r.get("category") == "invoices"
)

result = get_document("invoices/nonexistent_doc")
run_test(
    "get_document: returns error for unknown doc",
    result,
    lambda r: "error" in r
)

print("\n── match_order ───────────────────────────────────────────────")

result = match_order("10248")
run_test(
    "match_order: order 10248 has invoice + PO + shipment",
    result,
    lambda r: r["found"] and set(r["categories_found"]) >= {"invoices", "purchase_orders", "shipping_orders"}
)

result = match_order("10687")
run_test(
    "match_order: order 10687 missing PO",
    result,
    lambda r: r["found"] and "purchase_orders" in r["missing_categories"]
)

print("\n── find_mismatches ───────────────────────────────────────────")

result = find_mismatches("invoices_without_po")
run_test(
    "find_mismatches: finds invoices without PO",
    result,
    lambda r: r["count"] > 0
)

result = find_mismatches("pos_without_invoice")
run_test(
    "find_mismatches: finds POs without invoice",
    result,
    lambda r: r["count"] > 0
)

print("\n── list_inventory_periods ────────────────────────────────────")

result = list_inventory_periods()
run_test(
    "list_inventory_periods: returns 7 reports spanning 2016–2018",
    result,
    lambda r: r["count"] == 7 and "2016" in r["date_range"] and "2018" in r["date_range"]
)

print("\n── get_contract_terms ────────────────────────────────────────")

result = get_contract_terms("delivery")
run_test(
    "get_contract_terms: finds delivery terms in contract",
    result,
    lambda r: r["count"] > 0 and any("delivery" in (d.get("passage") or "").lower() for d in r["results"])
)

print("\n── get_related_documents ─────────────────────────────────────")

result = get_related_documents("invoices/invoice_10248")
run_test(
    "get_related_documents: invoice_10248 has related docs",
    result,
    lambda r: r["related_count"] > 0 and r["order_id"] == "10248"
)

result = get_related_documents("invoices/batch2-0998")
run_test(
    "get_related_documents: batch invoice with no order_id handled gracefully",
    result,
    lambda r: r.get("order_id") is None and "related" in r
)

print("\n── search_by_vendor ──────────────────────────────────────────")

result = search_by_vendor("TotalEnergies")
run_test(
    "search_by_vendor: finds TotalEnergies contract",
    result,
    lambda r: r["count"] > 0 and any("contract" in d["category"] for d in r["results"])
)

result = search_by_vendor("Hungry Owl")
run_test(
    "search_by_vendor: finds Hungry Owl documents",
    result,
    lambda r: r["count"] > 0
)

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'─'*55}")
print(f"  Results: {passed} passed, {failed} failed out of {passed + failed} tests")
print(f"{'─'*55}\n")

if failed > 0:
    sys.exit(1)