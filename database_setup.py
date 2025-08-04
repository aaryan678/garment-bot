# ----------  LOCAL DB SETUP  ----------
from sqlalchemy import (create_engine, Column, Integer, String, DateTime,
                        Boolean, Date, func)
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from sqlalchemy import create_engine

# Stage labels for the workflow
STAGE_LABELS = [
    "Pre-fit", "Fit", "Bulk", "Bulk in-house",
    "FPT", "GPT", "PP", "Accessories in-house",
    "Cutting sheet", "Stitching", "Finishing",
    "Inline", "Packing", "Dispatch"
]

DB_PATH = "/var/lib/bot/production.db"                      # one file, lives next to app.py
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
Base = declarative_base()
Session = sessionmaker(bind=engine, expire_on_commit=False)

class Style(Base):
    """One row per style, keyed on merchant + style_no."""
    __tablename__ = "styles"
    id         = Column(Integer, primary_key=True)
    merchant   = Column(String(64), nullable=False)
    brand      = Column(String(64), nullable=False)
    style_no   = Column(String(64), nullable=False)
    garment    = Column(String(64), nullable=False)
    colour     = Column(String(64), nullable=False)

    stage      = Column(Integer, default=0)    # 0 ≙ Pre-fit
    active     = Column(Boolean, default=True)

    # placeholders for the extra data we'll capture later
    bulk_eta   = Column(Date,     nullable=True)
    acc_barcode  = Column(String, nullable=True)
    acc_trims    = Column(String, nullable=True)
    acc_washcare = Column(String, nullable=True)
    acc_other    = Column(String, nullable=True)
    stitch_qty   = Column(Integer, nullable=True)
    finish_qty   = Column(Integer, nullable=True)
    pack_qty     = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        # optional uniqueness so the same merchant can't add dupes
        {"sqlite_autoincrement": True},
    )

def init_database():
    """Initialize the database and create tables."""
    Base.metadata.create_all(engine)
    print(f"Database initialized at: {os.path.abspath(DB_PATH)}")

def add_style(merchant, brand, style_no, garment, colour):
    """Add a new style to the database."""
    with Session() as db:
        style_row = Style(
            merchant = merchant,
            brand    = brand,
            style_no = style_no,
            garment  = garment,
            colour   = colour,
            stage    = 0,
            active   = True
        )
        db.add(style_row)
        db.commit()
        return style_row.id

def get_styles_by_merchant(merchant, active_only=True):
    """Get all styles for a specific merchant."""
    with Session() as db:
        query = db.query(Style).filter_by(merchant=merchant)
        if active_only:
            query = query.filter_by(active=True)
        styles = query.order_by(Style.created_at.desc()).all()
        return styles

def get_all_styles():
    """Get all styles from the database."""
    with Session() as db:
        styles = (
            db.query(Style)
              .order_by(Style.created_at.desc())
              .all()
        )
        return styles

def update_style_stage(style_id, stage):
    """Update the stage of a specific style."""
    with Session() as db:
        style = db.query(Style).filter_by(id=style_id).first()
        if style:
            style.stage = stage
            if stage == 13:  # Dispatch stage → deactivate
                style.active = False
            db.commit()

def get_style_by_id(style_id):
    """Get a specific style by ID."""
    with Session() as db:
        style = db.query(Style).filter_by(id=style_id).first()
        return style

def delete_style(style_id):
    """Soft delete a style by ID (archive it)."""
    with Session() as db:
        style = db.query(Style).filter_by(id=style_id).first()
        if style and style.active:
            style.active = False
            db.commit()
            return True
        return False

def get_archived_styles_by_merchant(merchant):
    """Get all archived (inactive) styles for a specific merchant."""
    with Session() as db:
        styles = (
            db.query(Style)
              .filter_by(merchant=merchant, active=False)
              .order_by(Style.created_at.desc())
              .all()
        )
        return styles

def restore_style(style_id):
    """Restore an archived style by ID (set active=True)."""
    with Session() as db:
        style = db.query(Style).filter_by(id=style_id).first()
        if style and not style.active:
            style.active = True
            db.commit()
            return True
        return False

def backup_database():
    """Create a backup of the database."""
    import shutil
    import datetime
    
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    backup_path = f"{backup_dir}/production_{datetime.date.today()}.db"
    shutil.copyfile(DB_PATH, backup_path)
    print(f"Database backed up to: {backup_path}")

if __name__ == "__main__":
    # Initialize the database when this file is run directly
    init_database()
    print("Database setup complete!") 