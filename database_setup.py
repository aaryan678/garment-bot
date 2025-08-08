"""TinyDB-backed storage for style tracking.

This module replaces the previous SQLAlchemy/SQLite setup with a much
lighter TinyDB JSON database.  All helper functions return simple objects
with attribute access to keep the rest of the application code small.
"""

from __future__ import annotations

from datetime import datetime, date
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

from tinydb import TinyDB, Query

# ---------------------------------------------------------------------------
# Constants / setup
# ---------------------------------------------------------------------------

STAGE_LABELS = [
    "Pre-fit",
    "Fit",
    "Bulk",
    "Bulk in-house",
    "FPT",
    "GPT",
    "PP",
    "Accessories in-house",
    "Cutting sheet",
    "Inline",
    "Stitching",
    "Finishing",
    "Packing",
    "Dispatch",
]

# Store TinyDB JSON next to the application (same location as previous DB)
DB_PATH = Path("production.json")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_db = TinyDB(DB_PATH)
_styles = _db.table("styles")
Q = Query()


def _to_style(doc) -> SimpleNamespace:
    """Convert a TinyDB document to an object with attribute access."""
    data = dict(doc)
    data["created_at"] = datetime.fromisoformat(data["created_at"])
    return SimpleNamespace(id=doc.doc_id, **data)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def add_style(merchant: str, brand: str, style_no: str, garment: str, colour: str, total_qty: Optional[int] = None, dispatch_date: Optional[str] = None) -> int:
    """Add a new style to the database and return its ID.
    total_qty is optional integer; dispatch_date is optional ISO date string (YYYY-MM-DD).
    """

    doc_id = _styles.insert(
        {
            "merchant": merchant,
            "brand": brand,
            "style_no": style_no,
            "garment": garment,
            "colour": colour,
            "stage": 0,
            "active": True,
            "created_at": datetime.utcnow().isoformat(),
            "bulk_eta": None,
            "acc_barcode": None,
            "acc_trims": None,
            "acc_washcare": None,
            "acc_other": None,
            "cut_qty": None,
            "stitch_qty": None,
            "finish_qty": None,
            "pack_qty": None,
            "total_qty": int(total_qty) if total_qty is not None else None,
            "dispatch_date": dispatch_date,
        }
    )
    return int(doc_id)


def get_styles_by_merchant(merchant: str, active_only: bool = True) -> List[SimpleNamespace]:
    """Return all styles for a given merchant sorted by creation time (newest first)."""

    docs = _styles.search(Q.merchant == merchant)
    if active_only:
        docs = [d for d in docs if d.get("active", True)]
    docs.sort(key=lambda d: datetime.fromisoformat(d["created_at"]), reverse=True)
    return [_to_style(d) for d in docs]


def get_all_styles() -> List[SimpleNamespace]:
    """Return all styles in the database sorted by creation time (newest first)."""

    docs = _styles.all()
    docs.sort(key=lambda d: datetime.fromisoformat(d["created_at"]), reverse=True)
    return [_to_style(d) for d in docs]


def get_style_by_id(style_id: int) -> Optional[SimpleNamespace]:
    """Fetch a single style by its ID."""

    doc = _styles.get(doc_id=style_id)
    return _to_style(doc) if doc else None


def update_style_stage(style_id: int, stage: int) -> None:
    """Update the stage of a style. Dispatch (13) marks it inactive."""

    doc = _styles.get(doc_id=style_id)
    if not doc:
        return

    doc["stage"] = stage
    if stage == 13:  # Dispatch stage → deactivate
        doc["active"] = False
    _styles.update(doc, doc_ids=[style_id])


def update_style_quantities(style_id: int, stitch_qty: Optional[int] = None, finish_qty: Optional[int] = None, pack_qty: Optional[int] = None, cut_qty: Optional[int] = None) -> None:
    """Update quantity fields for a style. Only provided fields are updated."""
    doc = _styles.get(doc_id=style_id)
    if not doc:
        return
    if cut_qty is not None:
        doc["cut_qty"] = int(cut_qty)
    if stitch_qty is not None:
        doc["stitch_qty"] = int(stitch_qty)
    if finish_qty is not None:
        doc["finish_qty"] = int(finish_qty)
    if pack_qty is not None:
        doc["pack_qty"] = int(pack_qty)
    _styles.update(doc, doc_ids=[style_id])


def delete_style(style_id: int) -> bool:
    """Soft delete a style by setting active=False."""

    doc = _styles.get(doc_id=style_id)
    if doc and doc.get("active", True):
        _styles.update({"active": False}, doc_ids=[style_id])
        return True
    return False


def get_archived_styles_by_merchant(merchant: str) -> List[SimpleNamespace]:
    """Return all archived (inactive) styles for a merchant."""

    docs = _styles.search((Q.merchant == merchant) & (Q.active == False))
    docs.sort(key=lambda d: datetime.fromisoformat(d["created_at"]), reverse=True)
    return [_to_style(d) for d in docs]


def restore_style(style_id: int) -> bool:
    """Reactivate an archived style."""

    doc = _styles.get(doc_id=style_id)
    if doc and not doc.get("active", True):
        _styles.update({"active": True}, doc_ids=[style_id])
        return True
    return False


def backup_database() -> None:
    """Create a dated backup of the TinyDB file."""

    import shutil

    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"production_{date.today()}.json"
    shutil.copyfile(DB_PATH, backup_path)
    print(f"Database backed up to: {backup_path}")


def init_database() -> None:
    """Ensure the database file exists."""

    _styles.all()  # touching the table creates the file on disk
    print(f"Database initialized at: {DB_PATH.resolve()}")


if __name__ == "__main__":
    init_database()
    print("Database setup complete!")

