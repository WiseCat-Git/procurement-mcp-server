"""
pipeline.py — Procurement Knowledge Base Ingestion Pipeline

Reads raw documents from the data/ folder, extracts text (PDF or OCR),
parses structured fields, stores everything in SQLite with FTS5,
and pre-computes cross-document relationship flags.

Usage:
    python pipeline.py --data ../data\ (3\)/data
"""

import argparse
import os
import re
import sqlite3
import json
from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

# ── Constants ────────────────────────────────────────────────────────────────

CATEGORIES = ["invoices", "purchase_orders", "shipping_orders",
               "inventory_reports", "contracts"]

# Tesseract path for Windows
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

DB_PATH = Path("db/knowledge_base.db")
EXTRACTED_DIR = Path("db/extracted")

# ── Database setup ────────────────────────────────────────────────────────────

def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id              TEXT PRIMARY KEY,
            filename        TEXT NOT NULL,
            category        TEXT NOT NULL,
            filepath        TEXT NOT NULL,
            order_id        TEXT,
            vendor          TEXT,
            doc_date        TEXT,
            amount          TEXT,
            period          TEXT,
            raw_text        TEXT,
            extraction_method TEXT,
            has_matching_po       INTEGER DEFAULT 0,
            has_matching_invoice  INTEGER DEFAULT 0,
            has_matching_shipment INTEGER DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
        USING fts5(
            id UNINDEXED,
            filename,
            category,
            vendor,
            raw_text,
            content='documents',
            content_rowid='rowid'
        );

        CREATE TABLE IF NOT EXISTS document_links (
            order_id    TEXT NOT NULL,
            doc_id_a    TEXT NOT NULL,
            doc_id_b    TEXT NOT NULL,
            link_type   TEXT NOT NULL,
            PRIMARY KEY (doc_id_a, doc_id_b)
        );
    """)
    conn.commit()

# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text_pdf(filepath: Path) -> tuple[str, str]:
    """Try direct PDF text extraction. Returns (text, method)."""
    try:
        with pdfplumber.open(filepath) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(pages).strip()
        if len(text) > 50:
            return text, "pdfplumber"
    except Exception:
        pass
    return "", "failed"


def extract_text_ocr(filepath: Path) -> tuple[str, str]:
    """OCR extraction for image files or scanned PDFs."""
    try:
        if filepath.suffix.lower() in [".jpg", ".jpeg", ".png"]:
            img = Image.open(filepath)
            text = pytesseract.image_to_string(img)
            return text.strip(), "tesseract_image"
        else:
            images = convert_from_path(str(filepath), dpi=200)
            pages = [pytesseract.image_to_string(img) for img in images]
            return "\n".join(pages).strip(), "tesseract_pdf"
    except Exception as e:
        return f"[OCR failed: {e}]", "ocr_failed"


def extract_text(filepath: Path) -> tuple[str, str]:
    """Route to correct extraction method based on format and content."""
    if filepath.suffix.lower() in [".jpg", ".jpeg", ".png"]:
        return extract_text_ocr(filepath)
    text, method = extract_text_pdf(filepath)
    if method == "failed" or len(text) < 50:
        return extract_text_ocr(filepath)
    return text, method

# ── Field parsing ─────────────────────────────────────────────────────────────

def parse_order_id(filename: str, text: str) -> str | None:
    """Extract order ID from filename first, then body text."""
    # From filename: invoice_10248.pdf, purchase_orders_10248.pdf, order_10248.pdf
    m = re.search(r'(\d{5})', filename)
    if m:
        return m.group(1)
    # From text body
    patterns = [
        r'[Oo]rder\s*[#Nn]o?\.?\s*:?\s*(\d{4,6})',
        r'[Ii]nvoice\s*[#Nn]o?\.?\s*:?\s*(\d{4,6})',
        r'PO\s*[#Nn]o?\.?\s*:?\s*(\d{4,6})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None


def parse_vendor(text: str) -> str | None:
    patterns = [
        r'(?:Vendor|Supplier|From|Bill\s+To|Sold\s+By)[:\s]+([A-Z][A-Za-z0-9\s&.,\-]{2,40})',
        r'(?:Company|Customer)[:\s]+([A-Z][A-Za-z0-9\s&.,\-]{2,40})',
        r'TotalEnergies',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = m.group(0) if 'TotalEnergies' in p else m.group(1)
            return val.strip()[:80]
    return None


def parse_date(text: str) -> str | None:
    patterns = [
        r'\b(\d{4}-\d{2}-\d{2})\b',
        r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b',
        r'\b(\w+ \d{1,2},?\s*\d{4})\b',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None


def parse_amount(text: str) -> str | None:
    m = re.search(r'(?:Total|Amount|Grand\s+Total)[:\s$€£]*([0-9,]+\.?\d{0,2})', text, re.IGNORECASE)
    if m:
        return m.group(1).replace(',', '')
    return None


def parse_period(filename: str) -> str | None:
    """Extract YYYY-MM period from inventory report filenames."""
    m = re.search(r'(\d{4}-\d{2})', filename)
    return m.group(1) if m else None


def build_doc_id(category: str, filename: str) -> str:
    stem = Path(filename).stem
    return f"{category}/{stem}"

# ── Core ingestion ────────────────────────────────────────────────────────────

def ingest_file(filepath: Path, category: str, conn) -> dict:
    filename = filepath.name
    doc_id = build_doc_id(category, filename)

    print(f"  Processing: {filename}")

    text, method = extract_text(filepath)

    # Save raw text for lineage
    out_path = EXTRACTED_DIR / f"{doc_id.replace('/', '_')}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    order_id = parse_order_id(filename, text)
    vendor   = parse_vendor(text)
    date     = parse_date(text)
    amount   = parse_amount(text)
    period   = parse_period(filename) if category == "inventory_reports" else None

    conn.execute("""
        INSERT OR REPLACE INTO documents
            (id, filename, category, filepath, order_id, vendor,
             doc_date, amount, period, raw_text, extraction_method)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (doc_id, filename, category, str(filepath), order_id,
          vendor, date, amount, period, text, method))

    # Sync FTS
    conn.execute("INSERT OR REPLACE INTO documents_fts(id, filename, category, vendor, raw_text) VALUES (?,?,?,?,?)",
                 (doc_id, filename, category, vendor or "", text))

    conn.commit()

    return {"doc_id": doc_id, "order_id": order_id, "method": method}

# ── Relationship materialization ──────────────────────────────────────────────

def materialize_relationships(conn):
    """Pre-compute order_id joins and mismatch flags across categories."""
    print("\nMaterializing cross-document relationships...")

    # Build order_id → {category: [doc_ids]} map
    rows = conn.execute(
        "SELECT id, category, order_id FROM documents WHERE order_id IS NOT NULL"
    ).fetchall()

    order_map: dict[str, dict[str, list]] = {}
    for doc_id, cat, oid in rows:
        order_map.setdefault(oid, {}).setdefault(cat, []).append(doc_id)

    # Insert document_links
    conn.execute("DELETE FROM document_links")
    for oid, cat_map in order_map.items():
        all_docs = [(cat, did) for cat, dids in cat_map.items() for did in dids]
        for i, (cat_a, did_a) in enumerate(all_docs):
            for cat_b, did_b in all_docs[i+1:]:
                link_type = f"{cat_a}↔{cat_b}"
                conn.execute(
                    "INSERT OR IGNORE INTO document_links VALUES (?,?,?,?)",
                    (oid, did_a, did_b, link_type)
                )

    # Set mismatch flags
    for oid, cat_map in order_map.items():
        has_inv  = "invoices" in cat_map
        has_po   = "purchase_orders" in cat_map
        has_ship = "shipping_orders" in cat_map

        for cat, dids in cat_map.items():
            for did in dids:
                conn.execute("""
                    UPDATE documents SET
                        has_matching_po       = ?,
                        has_matching_invoice  = ?,
                        has_matching_shipment = ?
                    WHERE id = ?
                """, (int(has_po), int(has_inv), int(has_ship), did))

    conn.commit()

    # Report mismatches
    missing_po = conn.execute("""
        SELECT filename FROM documents
        WHERE category = 'invoices' AND has_matching_po = 0
    """).fetchall()

    missing_inv = conn.execute("""
        SELECT filename FROM documents
        WHERE category = 'purchase_orders' AND has_matching_invoice = 0
    """).fetchall()

    missing_ship = conn.execute("""
        SELECT filename FROM documents
        WHERE category IN ('invoices','purchase_orders') AND has_matching_shipment = 0
    """).fetchall()

    print(f"  Invoices missing a PO:       {[r[0] for r in missing_po]}")
    print(f"  POs missing an invoice:      {[r[0] for r in missing_inv]}")
    print(f"  Docs missing a shipment:     {[r[0] for r in missing_ship]}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Procurement pipeline")
    parser.add_argument("--data", required=True, help="Path to data root folder")
    args = parser.parse_args()

    data_root = Path(args.data)
    if not data_root.exists():
        print(f"Error: data folder not found at {data_root}")
        return

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total = 0
    for category in CATEGORIES:
        cat_path = data_root / category
        if not cat_path.exists():
            print(f"Skipping missing folder: {cat_path}")
            continue

        print(f"\n── {category} ──")
        for f in sorted(cat_path.iterdir()):
            if f.suffix.lower() in [".pdf", ".jpg", ".jpeg", ".png"]:
                result = ingest_file(f, category, conn)
                print(f"    ✓ {result['doc_id']} | order={result['order_id']} | method={result['method']}")
                total += 1

    materialize_relationships(conn)
    conn.close()

    print(f"\n✅ Pipeline complete — {total} documents ingested into {DB_PATH}")


if __name__ == "__main__":
    main()