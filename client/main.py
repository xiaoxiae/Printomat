#!/usr/bin/env python3
"""Desktop Printer Client - connects to server and prints received jobs.

This is a standalone client that:
1. Connects to the server via WebSocket
2. Receives print jobs
3. Simulates printing (or can be extended for real printers)
4. Sends acknowledgments back to the server
"""

import asyncio
import websockets
import json
import sys
from datetime import datetime
from typing import Optional
import time
from pathlib import Path
from .config import Config

try:
    from escpos.printer import Usb
    HAS_ESCPOS = True
except ImportError:
    HAS_ESCPOS = False


class PrinterClient:
    """WebSocket client for receiving and processing print jobs."""

    def __init__(self, server_url: str, auth_token: str,
                 printer_vendor_id: Optional[int] = None, printer_product_id: Optional[int] = None):
        """Initialize the printer client.

        Args:
            server_url: WebSocket server URL (e.g., ws://localhost:8000/ws)
            auth_token: Authentication token for the printer
            printer_vendor_id: USB vendor ID for ESC/POS printer (e.g., 0x0471)
            printer_product_id: USB product ID for ESC/POS printer (e.g., 0x0055)
        """
        self.server_url = server_url
        self.auth_token = auth_token
        self.job_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.printer = None
        self.printer_vendor_id = printer_vendor_id
        self.printer_product_id = printer_product_id

        # Initialize ESC/POS printer if credentials provided
        if self.printer_vendor_id and self.printer_product_id:
            self._initialize_printer()

    def log(self, message: str, level: str = "INFO", end: str = "\n"):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if level == "ERROR":
            symbol = "✗"
        elif level == "SUCCESS":
            symbol = "✓"
        elif level == "WARN":
            symbol = "!"
        else:
            symbol = "→"

        print(f"[{timestamp}] {symbol} {message}", end=end)

    def get_server_address(self) -> str:
        """Extract server address from URL for display."""
        # Parse ws://localhost:8000/ws -> localhost:8000
        return self.server_url.replace("ws://", "").replace("wss://", "").split("/")[0]

    def _initialize_printer(self) -> bool:
        """Initialize connection to ESC/POS printer via USB.

        Returns:
            True if printer initialized successfully, False otherwise
        """
        if not HAS_ESCPOS:
            self.log("python-escpos not installed. Run: pip install python-escpos pyusb", level="ERROR")
            return False

        try:
            self.printer = Usb(self.printer_vendor_id, self.printer_product_id)
            self.log(f"Printer initialized (vendor: 0x{self.printer_vendor_id:04x}, product: 0x{self.printer_product_id:04x})", level="SUCCESS")
            return True
        except Exception as e:
            self.log(f"Failed to initialize printer: {e}", level="ERROR")
            self.log("Tip: Check USB vendor and product IDs with: lsusb", level="WARN")
            self.printer = None
            return False

    def _format_message(self, content: str, from_name: str, date_str: str, job_type: str) -> str:
        """Format a message with headers before printing.

        Args:
            content: The message content
            from_name: Sender (IP or friendship token name)
            date_str: ISO format datetime string
            job_type: Type of content

        Returns:
            Formatted message string
        """
        # Parse ISO datetime to readable format
        try:
            dt = datetime.fromisoformat(date_str)
            readable_date = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            readable_date = date_str

        separator = "-" * 40
        formatted = f"""{separator}
From: {from_name}
Date: {readable_date}

{content}

{separator}"""
        return formatted

    async def print_job(self, job_id: int, content: str, job_type: str,
                       from_name: Optional[str] = None, date_str: Optional[str] = None) -> bool:
        """Print a job to the ESC/POS printer (or simulate if not available).

        Args:
            job_id: Unique job identifier
            content: Content to print
            job_type: Type of content (text, image, etc.)
            from_name: Sender (IP or friendship token name)
            date_str: ISO format datetime string

        Returns:
            True if print succeeded, False otherwise
        """
        self.job_count += 1

        # Format message with headers if metadata is provided
        if from_name and date_str:
            formatted_content = self._format_message(content, from_name, date_str, job_type)
        else:
            formatted_content = content

        # Print to actual device if available, otherwise simulate
        try:
            if self.printer:
                await asyncio.sleep(0.1)  # Brief delay for I/O
                # Send to printer
                self.printer.text(formatted_content)
                self.printer.text("\n\n")  # Add blank lines at end
                self.printer.cut()  # Cut the paper
            else:
                # Simulate printing without device
                await asyncio.sleep(0.5)
        except Exception as e:
            self.log(f"Failed to print job {job_id}: {e}", level="ERROR")
            self.failure_count += 1
            return False

        self.success_count += 1
        return True

    async def run(self):
        """Main client loop - connect and process jobs."""
        self.log(f"Printer Client Starting")
        self.log(f"Server: {self.get_server_address()}")

        uri = f"{self.server_url}?token={self.auth_token}"

        connection_attempts = 0
        while True:
            try:
                connection_attempts += 1
                self.log(f"Connecting to server (attempt {connection_attempts})...")

                async with websockets.connect(uri) as websocket:
                    connection_attempts = 0
                    self.log(f"Connected to server successfully", level="SUCCESS")

                    # Process messages indefinitely
                    while True:
                        try:
                            # Receive job from server
                            message = await websocket.recv()
                            job_data = json.loads(message)

                            job_id = job_data.get("id")
                            content = job_data.get("content", "")
                            job_type = job_data.get("type", "text")
                            from_name = job_data.get("from")
                            date_str = job_data.get("date")

                            # Print the job
                            success = await self.print_job(job_id, content, job_type, from_name, date_str)

                            # Send acknowledgment
                            if success:
                                ack = {"status": "success"}
                            else:
                                ack = {"status": "failed", "error_message": "Print failed"}

                            await websocket.send(json.dumps(ack))

                        except json.JSONDecodeError as e:
                            self.log(f"Failed to parse message: {e}", level="ERROR")
                            # Send failure acknowledgment
                            await websocket.send(json.dumps({"status": "failed", "error_message": str(e)}))

            except websockets.exceptions.ConnectionClosed:
                self.log(f"Connection closed by server", level="WARN")
                self.log(f"Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

            except websockets.exceptions.InvalidStatusCode as e:
                self.log(f"Authentication failed (invalid token?): {e}", level="ERROR")
                self.log(f"Exiting...")
                break

            except Exception as e:
                self.log(f"Connection error: {e}", level="ERROR")
                self.log(f"Retrying in 5 seconds...")
                await asyncio.sleep(5)

    def cleanup(self):
        """Clean up resources, particularly closing the printer connection."""
        if self.printer:
            try:
                self.printer.close()
                self.log("Printer connection closed", level="INFO")
            except Exception as e:
                self.log(f"Error closing printer: {e}", level="WARN")

    async def run_with_signal_handler(self):
        """Run the client with graceful shutdown on Ctrl+C."""
        try:
            await self.run()
        except KeyboardInterrupt:
            self.log("", level="WARN")
            self.log("Shutting down...", level="WARN")
            self.cleanup()
            sys.exit(0)


def main():
    """Initialize and run the printer client."""
    # Load configuration (look for config.toml in the client directory)
    config_path = Path(__file__).parent / "config.toml"
    config = Config(str(config_path))

    # Create and run client
    client = PrinterClient(
        server_url=config.get_server_url(),
        auth_token=config.get_auth_token(),
        printer_vendor_id=config.get_printer_vendor_id(),
        printer_product_id=config.get_printer_product_id()
    )

    # Run with signal handler for graceful shutdown
    try:
        asyncio.run(client.run_with_signal_handler())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
