#!/usr/bin/env python3
"""Run document retention cleanup for indexed text and quarantined file bytes."""
from __future__ import annotations

import os

from core.document_retrieval import DocumentRetrievalStore
from core.orbits_quarantine import DocumentQuarantineStore


def main() -> None:
    database = os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3")
    indexed = DocumentRetrievalStore(database).expire_due()
    quarantined = DocumentQuarantineStore(database).expire_due()
    print(f"Expired indexed documents: {indexed}")
    print(f"Deleted expired quarantine objects: {quarantined}")


if __name__ == "__main__":
    main()
