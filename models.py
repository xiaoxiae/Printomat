from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()


class PrintRequest(Base):
    __tablename__ = "print_requests"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    type = Column(String(50), nullable=False)
    submitter_ip = Column(String(45), nullable=False, index=True)
    is_priority = Column(Boolean, default=False)
    friendship_token_label = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, index=True)  # queued, printing, printed, failed
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    printed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


class PrinterStatus(Base):
    __tablename__ = "printer_status"

    id = Column(Integer, primary_key=True, index=True)
    is_connected = Column(Boolean, default=False)
    connected_at = Column(DateTime, nullable=True)


def get_database_engine(db_url: str, connect_args=None):
    """Create and return a database engine."""
    if connect_args:
        return create_engine(db_url, connect_args=connect_args)
    return create_engine(db_url)


def get_session_local(engine):
    """Create a session factory."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
