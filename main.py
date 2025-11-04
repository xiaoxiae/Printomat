from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from config import Config
from models import Base, get_database_engine, get_session_local

# Load configuration
config = Config("config.toml")

# Initialize database
db_url = config.get_database_url()
if db_url.startswith("sqlite"):
    engine = get_database_engine(db_url, connect_args={"check_same_thread": False})
else:
    engine = get_database_engine(db_url)
SessionLocal = get_session_local(engine)

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="Receipt Printer Server")


@app.on_event("startup")
async def startup_event():
    """Initialize on server startup."""
    print("Server starting up...")
    print(f"Database: {config.get_database_url()}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on server shutdown."""
    print("Server shutting down...")


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
