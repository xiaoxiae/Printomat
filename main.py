from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
from config import Config
from models import Base, get_database_engine, get_session_local, PrintRequest
from datetime import datetime, timedelta
from collections import deque
from typing import Optional

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

# In-memory queue
message_queue = deque()
queue_max_size = config.get_queue_max_size()


# Pydantic models
class SubmitRequest(BaseModel):
    content: str
    type: str
    token: Optional[str] = None


class SubmitResponse(BaseModel):
    status: str
    position: Optional[int] = None
    estimated_wait_minutes: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


# Helper functions
def get_client_ip(request: Request) -> str:
    """Extract client IP address from request."""
    if request.client:
        return request.client.host
    return "unknown"


def check_rate_limit(ip: str, session) -> tuple[bool, Optional[int]]:
    """
    Check if IP is rate limited.
    Returns (is_allowed, minutes_until_retry)
    """
    cooldown_hours = config.get_rate_limit_cooldown_hours()
    cutoff_time = datetime.utcnow() - timedelta(hours=cooldown_hours)

    last_request = session.query(PrintRequest).filter(
        PrintRequest.submitter_ip == ip,
        PrintRequest.created_at > cutoff_time
    ).order_by(PrintRequest.created_at.desc()).first()

    if last_request:
        time_since = datetime.utcnow() - last_request.created_at
        cooldown_seconds = cooldown_hours * 3600
        retry_after_seconds = cooldown_seconds - time_since.total_seconds()
        if retry_after_seconds > 0:
            minutes_until_retry = int(retry_after_seconds / 60) + 1
            return False, minutes_until_retry

    return True, None


def get_queue_position(request_id: int) -> int:
    """Get position of a request in the queue."""
    position = 0
    for item in message_queue:
        if item["id"] == request_id:
            return position
        position += 1
    return -1


@app.on_event("startup")
async def startup_event():
    """Initialize on server startup."""
    global message_queue
    print("Server starting up...")
    print(f"Database: {config.get_database_url()}")

    # Load pending messages from database into queue
    session = SessionLocal()
    try:
        pending_requests = session.query(PrintRequest).filter(
            PrintRequest.status.in_(["queued", "printing"])
        ).order_by(
            PrintRequest.is_priority.desc(),
            PrintRequest.created_at.asc()
        ).all()

        for req in pending_requests:
            message_queue.append({
                "id": req.id,
                "content": req.content,
                "type": req.type,
                "is_priority": req.is_priority,
                "friendship_token_label": req.friendship_token_label
            })

        print(f"Loaded {len(pending_requests)} pending messages into queue")
    finally:
        session.close()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on server shutdown."""
    print("Server shutting down...")


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.post("/submit")
async def submit_print_request(request_data: SubmitRequest, request: Request):
    """Submit a print request."""
    global message_queue

    session = SessionLocal()
    try:
        client_ip = get_client_ip(request)

        # Check if token is provided and validate it
        token_data = None
        if request_data.token:
            token_data = config.get_friendship_token_by_value(request_data.token)
            if not token_data:
                # Invalid token provided
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_token",
                        "message": "Invalid friendship token"
                    }
                )

        # If not a friendship token user, check rate limit
        if not token_data:
            is_allowed, minutes_until_retry = check_rate_limit(client_ip, session)
            if not is_allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "message": f"Try again in {minutes_until_retry} minutes"
                    }
                )

        # Check if queue is full (only for non-priority users)
        if not token_data and len(message_queue) >= queue_max_size:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "queue_full",
                    "message": "Queue is currently full, try again later"
                }
            )

        # Create print request in database
        print_request = PrintRequest(
            content=request_data.content,
            type=request_data.type,
            submitter_ip=client_ip,
            is_priority=bool(token_data),
            friendship_token_label=token_data.get("label") if token_data else None,
            status="printing" if token_data else "queued"
        )

        session.add(print_request)
        session.commit()
        session.refresh(print_request)

        # If friendship token user, send immediately (simulate)
        if token_data:
            message_queue.appendleft({
                "id": print_request.id,
                "content": request_data.content,
                "type": request_data.type,
                "is_priority": True,
                "friendship_token_label": token_data.get("label")
            })

            return {
                "status": "printing_immediately",
                "message": token_data.get("message", "Thanks for the message!")
            }

        # Regular user: add to queue
        message_queue.append({
            "id": print_request.id,
            "content": request_data.content,
            "type": request_data.type,
            "is_priority": False,
            "friendship_token_label": None
        })

        position = get_queue_position(print_request.id)
        estimated_wait = position * 1  # 1 minute per position

        return {
            "status": "queued",
            "position": position,
            "estimated_wait_minutes": estimated_wait
        }

    finally:
        session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
