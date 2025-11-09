from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status, Form
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from .config import Config
from .models import Base, get_database_engine, get_session_local, PrintRequest
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import json
import time
import threading
import sys
import os
import logging
from .console import run_console


def setup_logger(name: str = __name__) -> logging.Logger:
    """Create a dedicated logger with explicit console handler.

    This ensures the logger won't be hijacked by other modules.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Remove any existing handlers to prevent duplicates
    logger.handlers.clear()

    # Create console handler with explicit stream
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)

    # Prevent propagation to root logger (avoid duplicate output)
    logger.propagate = False

    return logger


# Create dedicated logger
logger = setup_logger("PrintomatServer")

# Load configuration (look for config.toml in the server directory)
config_path = Path(__file__).parent / "config.toml"
config = Config(str(config_path))

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

# Setup CORS middleware
cors_origins = config.get_cors_allow_origins()
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

# Setup Jinja2 templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Queue configuration
queue_max_size = config.get_queue_max_size()

# Global printer connection status
printer_connected = False

# Console thread reference for shutdown
console_thread = None


# Pydantic models
class SubmitRequest(BaseModel):
    message: Optional[str] = None  # Text message (optional)
    image: Optional[str] = None    # Base64-encoded image (optional)
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
    global console_thread
    logger.info("Server starting up...")
    logger.info(f"Database: {config.get_database_url()}")

    try:
        # Start interactive console in a separate daemon thread
        console_thread = threading.Thread(
            target=run_console,
            args=(config, SessionLocal),
            daemon=True
        )
        console_thread.start()
        logger.info("Interactive console started. Type 'help' for commands.")
    except Exception as e:
        logger.error(f"Failed to start interactive console: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on server shutdown."""
    logger.info("Server shutting down...")


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.get("/form")
async def get_form(request: Request):
    """Serve the submission form."""
    return templates.TemplateResponse("form.html", {"request": request})


async def _process_submit_request(message: Optional[str], image: Optional[str], token: Optional[str], request: Request, is_form_submission: bool = False):
    """Core submission logic shared by both JSON and form endpoints."""
    session = SessionLocal()
    try:
        logger.debug(f"Processing submit request from {request.client.host if request.client else 'unknown'}")
        client_ip = get_client_ip(request)

        # Validate that at least message or image is provided
        if not message and not image:
            logger.debug(f"Invalid request from {client_ip}: no message or image provided")
            response = {
                "error": "invalid_request",
                "message": "At least message or image must be provided"
            }
            if is_form_submission:
                return response, 400, True
            return JSONResponse(status_code=400, content=response)

        # Check if token is provided and validate it
        token_data = None
        if token:
            token_data = config.get_friendship_token_by_value(token)
            if not token_data:
                # Invalid token provided
                logger.warning(f"Invalid friendship token provided from {client_ip}")
                response = {
                    "error": "invalid_token",
                    "message": "Invalid friendship token"
                }
                if is_form_submission:
                    return response, 400, True
                return JSONResponse(status_code=400, content=response)
            logger.debug(f"Valid friendship token used from {client_ip} (label: {token_data.get('label')})")

        # If not a friendship token user, check rate limit
        if not token_data:
            is_allowed, minutes_until_retry = check_rate_limit(client_ip, session)
            if not is_allowed:
                logger.warning(f"Rate limit exceeded for {client_ip} (retry in {minutes_until_retry} minutes)")
                response = {
                    "error": "rate_limited",
                    "message": f"Try again in {minutes_until_retry} minutes"
                }
                if is_form_submission:
                    return response, 429, True
                return JSONResponse(status_code=429, content=response)

        # Check if queue is full (only for non-priority users)
        if not token_data:
            queued_count = session.query(PrintRequest).filter(
                PrintRequest.status.in_(["queued", "printing"])
            ).count()
            if queued_count >= queue_max_size:
                logger.warning(f"Queue full: rejected request from {client_ip} (current queue: {queued_count}/{queue_max_size})")
                response = {
                    "error": "queue_full",
                    "message": "Queue is currently full, try again later"
                }
                if is_form_submission:
                    return response, 503, True
                return JSONResponse(status_code=503, content=response)

        # Determine content type
        if message and image:
            content_type = "mixed"
        elif image:
            content_type = "image"
        else:
            content_type = "text"

        # Create print request in database
        try:
            print_request = PrintRequest(
                type=content_type,
                message_content=message,
                image_content=image,
                submitter_ip=client_ip,
                is_priority=bool(token_data),
                friendship_token_label=token_data.get("label") if token_data else None,
                friendship_token_name=token_data.get("name") if token_data else None,
                status="queued"  # Always start as queued, will be sent by WebSocket handler
            )

            session.add(print_request)
            session.commit()
            session.refresh(print_request)
        except Exception as e:
            logger.error(f"Failed to create print request from {client_ip}: {e}", exc_info=True)
            response = {
                "error": "database_error",
                "message": "Failed to process request. Please try again later."
            }
            if is_form_submission:
                return response, 500, True
            return JSONResponse(status_code=500, content=response)

        # Get queue position (for all users, in case printer is down)
        position = get_queue_position(print_request.id, session)
        estimated_wait = position * 1  # 1 minute per position

        # If friendship token user, they should be printed immediately
        # In the spec, priority users bypass queue but still need to be queued
        # They will just be at the front of the queue
        if token_data:
            logger.info(f"Priority request queued from {client_ip} (request_id: {print_request.id}, type: {content_type})")
            response = {
                "status": "printing_immediately",
                "message": token_data.get("message", "Thanks for the message!"),
                "position": position,
                "estimated_wait_minutes": estimated_wait,
                "printer_connected": printer_connected
            }
            if is_form_submission:
                return response, 200, False
            return response

        # Regular user: return queue position
        logger.info(f"Regular request queued from {client_ip} (request_id: {print_request.id}, position: {position}, type: {content_type})")
        response = {
            "status": "queued",
            "position": position,
            "estimated_wait_minutes": estimated_wait,
            "printer_connected": printer_connected
        }
        if is_form_submission:
            return response, 200, False
        return response

    finally:
        session.close()


@app.post("/submit")
async def submit_print_request(request: Request):
    """Submit a print request via JSON or form data."""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        # Handle JSON request
        try:
            request_data = await request.json()
            message = request_data.get("message")
            image = request_data.get("image")
            token = request_data.get("token")

            return await _process_submit_request(message, image, token, request, is_form_submission=False)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_json", "message": "Invalid JSON"}
            )
    else:
        # Handle form submission (redirect to result page)
        try:
            form_data = await request.form()
            message = form_data.get("message")
            image = form_data.get("image")
            token = form_data.get("token") or None

            response_data, _, is_error = await _process_submit_request(message, image, token, request, is_form_submission=True)

            # Render appropriate template based on response
            # For HTMX form swaps, we always return 200 so the swap happens
            if is_error:
                error = response_data.get("error", "unknown_error")
                message = response_data.get("message", "An error occurred")
                minutes_until_retry = 0

                if error == "rate_limited":
                    minutes_until_retry = int(message.split()[-2]) if "minutes" in message else 0

                return templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "error": error,
                        "minutes_until_retry": minutes_until_retry
                    }
                )
            else:
                status = response_data.get("status", "unknown")
                is_priority = status == "printing_immediately"
                estimated_wait_minutes = response_data.get("estimated_wait_minutes", "?")
                position = response_data.get("position", "?")
                message = response_data.get("message", "Thanks for the message!")
                printer_is_connected = response_data.get("printer_connected", False)

                return templates.TemplateResponse(
                    "success.html",
                    {
                        "request": request,
                        "is_priority": is_priority,
                        "message": message,
                        "estimated_wait_minutes": estimated_wait_minutes,
                        "position": position,
                        "printer_connected": printer_is_connected
                    }
                )
        except Exception as e:
            client_ip = get_client_ip(request)
            logger.error(f"Unexpected error in form submission from {client_ip}: {e}", exc_info=True)
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "error": "internal_error",
                    "message": "Internal server error. Please try again later."
                }
            )


@app.websocket("/ws")
async def websocket_printer_endpoint(websocket: WebSocket):
    """WebSocket endpoint for printer client.

    Handles both sending queued messages and receiving acknowledgments.
    Priority messages are sent immediately (with 1-second check interval).
    Regular messages respect the configured send interval (60 seconds by default).
    """
    global printer_connected

    # Get auth token from query parameters
    auth_token = websocket.query_params.get("token")
    expected_token = config.get_printer_token()

    # Authenticate
    if not auth_token or auth_token != expected_token:
        logger.warning(f"Printer client connection rejected: invalid/missing token (provided: {bool(auth_token)})")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await websocket.accept()
    printer_connected = True
    logger.info(f"Printer client connected successfully (remote: {websocket.client})")

    send_interval = config.get_queue_send_interval()
    last_send_time = time.time()
    currently_printing_id = None

    try:
        while True:
            current_time = time.time()
            time_since_last_send = current_time - last_send_time

            session = SessionLocal()
            try:
                # Get next queued message (priority first, then FIFO)
                next_message = session.query(PrintRequest).filter(
                    PrintRequest.status == "queued"
                ).order_by(
                    PrintRequest.is_priority.desc(),
                    PrintRequest.created_at.asc()
                ).first()

                # Determine if we should send this message
                should_send = False
                if next_message:
                    if next_message.is_priority:
                        # Priority messages: send immediately (no cooldown)
                        should_send = True
                    elif time_since_last_send >= send_interval:
                        # Regular messages: respect send interval
                        should_send = True

                if should_send and next_message:
                    try:
                        # Update status to printing
                        next_message.status = "printing"
                        session.commit()

                        # Determine sender: friend name or IP address
                        from_name = next_message.friendship_token_name or next_message.submitter_ip

                        # Send to printer
                        message_data = {
                            "from": from_name,
                            "date": datetime.utcnow().isoformat()
                        }
                        # Include optional message and/or image fields
                        if next_message.message_content:
                            message_data["message"] = next_message.message_content
                        if next_message.image_content:
                            message_data["image"] = next_message.image_content

                        await websocket.send_json(message_data)
                        currently_printing_id = next_message.id
                        is_priority = next_message.is_priority
                        logger.info(f"Sent message {next_message.id} to printer client (priority={is_priority}, from={from_name})")
                        last_send_time = current_time
                    except (WebSocketDisconnect, RuntimeError) as e:
                        # WebSocket is closed or in an invalid state - re-raise to disconnect handler
                        raise
                    except Exception as e:
                        logger.error(f"Failed to send message {next_message.id} to printer: {e}", exc_info=True)
                        next_message.status = "failed"
                        next_message.error_message = f"Server error sending to printer: {str(e)}"
                        session.commit()
            finally:
                session.close()

            # Wait for acknowledgment with timeout (check for acks frequently)
            try:
                ack_text = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)

                try:
                    ack_data = json.loads(ack_text)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse acknowledgment JSON: {e}. Received: {ack_text}")
                    continue

                if currently_printing_id is None:
                    logger.warning(f"Received acknowledgment but no message is currently printing: {ack_data}")
                    continue

                # Update database based on acknowledgment
                session = SessionLocal()
                try:
                    print_req = session.query(PrintRequest).filter(
                        PrintRequest.id == currently_printing_id
                    ).first()

                    if print_req:
                        if ack_data.get("status") == "success":
                            logger.info(f"Printer acknowledged success for message {currently_printing_id}")
                            print_req.status = "printed"
                            print_req.printed_at = datetime.utcnow()
                        else:
                            error_msg = ack_data.get("error_message", "Unknown error")
                            logger.warning(f"Printer reported failure for message {currently_printing_id}: {error_msg}")
                            print_req.status = "failed"
                            print_req.printed_at = datetime.utcnow()
                            print_req.error_message = error_msg
                        session.commit()
                    else:
                        logger.error(f"Received acknowledgment for unknown message ID {currently_printing_id}")
                except Exception as e:
                    logger.error(f"Failed to update print request {currently_printing_id} after acknowledgment: {e}", exc_info=True)
                finally:
                    session.close()

                currently_printing_id = None

            except asyncio.TimeoutError:
                pass
            except (WebSocketDisconnect, RuntimeError) as e:
                # WebSocket is closed - re-raise to disconnect handler
                raise
            except Exception as e:
                logger.error(f"Unexpected error while waiting for acknowledgment: {e}", exc_info=True)

    except WebSocketDisconnect:
        printer_connected = False
        logger.info("Printer client disconnected")
    except Exception as e:
        printer_connected = False
        logger.error(f"WebSocket error: {e}", exc_info=True)
