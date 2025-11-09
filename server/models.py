from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from pathlib import Path

Base = declarative_base()


class PrintRequest(Base):
    __tablename__ = "print_requests"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), nullable=False)
    message_content = Column(Text, nullable=True)  # Text message (optional)
    image_content = Column(Text, nullable=True)  # Base64-encoded image (optional)
    submitter_ip = Column(String(45), nullable=False, index=True)
    is_priority = Column(Boolean, default=False)
    friendship_token_name = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, index=True)  # queued, printing, printed, failed
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    printed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


def get_database_engine(db_url: str, connect_args=None):
    """Create and return a database engine.

    For SQLite databases, ensures the parent directory exists.
    """
    # For SQLite databases, create parent directory if needed
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

    if connect_args:
        return create_engine(db_url, connect_args=connect_args)
    return create_engine(db_url)


def get_session_local(engine):
    """Create a session factory."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
