from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
from config import Config
from models import Base, get_database_engine, get_session_local, PrintRequest, PrinterStatus
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import json
import time
import threading
import sys
from console import run_console

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

# Queue configuration
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


class ClientAcknowledgment(BaseModel):
    status: str  # "success" or "failed"
    error_message: Optional[str] = None


class PrinterMessage(BaseModel):
    content: str
    type: str


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


def get_queue_position(request_id: int, session) -> int:
    """Get position of a request in the queue by querying database."""
    # Count queued messages with higher priority or earlier creation time
    queued_before = session.query(PrintRequest).filter(
        PrintRequest.status == "queued"
    ).order_by(
        PrintRequest.is_priority.desc(),
        PrintRequest.created_at.asc()
    ).all()

    for idx, req in enumerate(queued_before):
        if req.id == request_id:
            return idx
    return -1


@app.on_event("startup")
async def startup_event():
    """Initialize on server startup."""
    print("Server starting up...")
    print(f"Database: {config.get_database_url()}")

    # Initialize printer status if not exists
    session = SessionLocal()
    try:
        printer_status = session.query(PrinterStatus).first()
        if not printer_status:
            printer_status = PrinterStatus(is_connected=False)
            session.add(printer_status)
            session.commit()
        print("Printer status table initialized")
    finally:
        session.close()

    # Start interactive console in a separate thread
    console_thread = threading.Thread(
        target=run_console,
        args=(config, SessionLocal),
        daemon=False
    )
    console_thread.start()
    print("Interactive console started. Type 'help' for commands.")


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
        if not token_data:
            queued_count = session.query(PrintRequest).filter(
                PrintRequest.status.in_(["queued", "printing"])
            ).count()
            if queued_count >= queue_max_size:
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
            status="queued"  # Always start as queued, will be sent by WebSocket handler
        )

        session.add(print_request)
        session.commit()
        session.refresh(print_request)

        # If friendship token user, they should be printed immediately
        # In the spec, priority users bypass queue but still need to be queued
        # They will just be at the front of the queue
        if token_data:
            return {
                "status": "printing_immediately",
                "message": token_data.get("message", "Thanks for the message!")
            }

        # Regular user: return queue position
        position = get_queue_position(print_request.id, session)
        estimated_wait = position * 1  # 1 minute per position

        return {
            "status": "queued",
            "position": position,
            "estimated_wait_minutes": estimated_wait
        }

    finally:
        session.close()


@app.websocket("/ws")
async def websocket_printer_endpoint(websocket: WebSocket):
    """WebSocket endpoint for printer client.

    Handles both sending queued messages and receiving acknowledgments.
    Only allows one active printer connection at a time.
    """
    # Get auth token from query parameters
    auth_token = websocket.query_params.get("token")
    expected_token = config.get_printer_token()

    # Authenticate
    if not auth_token or auth_token != expected_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        print("Printer client connection rejected: invalid token")
        return

    # Check if printer is already connected via database
    session = SessionLocal()
    try:
        printer_status = session.query(PrinterStatus).first()
        if printer_status and printer_status.is_connected:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Another printer is already connected")
            print("Printer client connection rejected: already connected")
            return

        # Mark printer as connected
        if printer_status:
            printer_status.is_connected = True
            printer_status.connected_at = datetime.utcnow()
        else:
            printer_status = PrinterStatus(is_connected=True, connected_at=datetime.utcnow())
            session.add(printer_status)
        session.commit()
    finally:
        session.close()

    await websocket.accept()
    print("Printer client connected successfully")

    send_interval = config.get_queue_send_interval()
    last_send_time = time.time()
    currently_printing_id = None

    try:
        while True:
            current_time = time.time()
            time_since_last_send = current_time - last_send_time

            # Check if it's time to send next message (respecting send interval)
            if time_since_last_send >= send_interval:
                session = SessionLocal()
                try:
                    # Get next queued message (priority first, then FIFO)
                    next_message = session.query(PrintRequest).filter(
                        PrintRequest.status == "queued"
                    ).order_by(
                        PrintRequest.is_priority.desc(),
                        PrintRequest.created_at.asc()
                    ).first()

                    if next_message:
                        # Update status to printing
                        next_message.status = "printing"
                        session.commit()

                        # Send to printer
                        message_data = {
                            "content": next_message.content,
                            "type": next_message.type
                        }
                        await websocket.send_json(message_data)
                        currently_printing_id = next_message.id
                        print(f"Sent message {next_message.id} to printer client")
                        last_send_time = current_time
                finally:
                    session.close()

            # Wait for acknowledgment with timeout (check for acks frequently)
            try:
                ack_text = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                ack_data = json.loads(ack_text)

                if currently_printing_id is None:
                    print("Received acknowledgment but no message is currently printing")
                    continue

                # Update database based on acknowledgment
                session = SessionLocal()
                try:
                    print_req = session.query(PrintRequest).filter(
                        PrintRequest.id == currently_printing_id
                    ).first()

                    if print_req:
                        if ack_data.get("status") == "success":
                            print(f"Printer acknowledged success for message {currently_printing_id}")
                            print_req.status = "printed"
                            print_req.printed_at = datetime.utcnow()
                        else:
                            error_msg = ack_data.get("error_message", "Unknown error")
                            print(f"Printer reported failure for message {currently_printing_id}: {error_msg}")
                            print_req.status = "failed"
                            print_req.printed_at = datetime.utcnow()
                            print_req.error_message = error_msg
                        session.commit()
                finally:
                    session.close()

                currently_printing_id = None

            except asyncio.TimeoutError:
                # No ack received, continue waiting for send interval
                pass

    except WebSocketDisconnect:
        print("Printer client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # Mark printer as disconnected in database
        session = SessionLocal()
        try:
            printer_status = session.query(PrinterStatus).first()
            if printer_status:
                printer_status.is_connected = False
                session.commit()
        finally:
            session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
