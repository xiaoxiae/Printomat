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
import logging
from datetime import datetime
from typing import Optional
import time
import base64
from pathlib import Path
from .config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

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
        self.logger = logging.getLogger(__name__)

        # Initialize debug print directory (relative to client module location)
        self.debug_print_dir = Path(__file__).parent / "print"
        self.debug_print_dir.mkdir(exist_ok=True)

        # Initialize ESC/POS printer if credentials provided
        if self.printer_vendor_id and self.printer_product_id:
            self._initialize_printer()

    def _save_debug_print(self, content: str) -> None:
        """Save debug print to file with datetime name.

        Args:
            content: The formatted content to save
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Format: YYYYMMdd_HHMMSS_mmm
            filename = self.debug_print_dir / f"{timestamp}.txt"
            filename.write_text(content)
        except Exception as e:
            self.logger.warning(f"Failed to save debug print: {e}")

    def _save_debug_image(self, image_bytes: bytes) -> str:
        """Save debug image to file with datetime name.

        Args:
            image_bytes: The binary image data to save

        Returns:
            Path to the saved image file
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Format: YYYYMMdd_HHMMSS_mmm
            filename = self.debug_print_dir / f"{timestamp}.png"
            filename.write_bytes(image_bytes)
            return str(filename)
        except Exception as e:
            self.logger.warning(f"Failed to save debug image: {e}")
            return None

    def _initialize_printer(self) -> bool:
        """Initialize connection to ESC/POS printer via USB.

        Returns:
            True if printer initialized successfully, False otherwise
        """
        if not HAS_ESCPOS:
            self.logger.error("python-escpos not installed. Run: pip install python-escpos pyusb")
            return False

        try:
            self.printer = Usb(self.printer_vendor_id, self.printer_product_id)
            self.logger.info(f"Printer initialized (vendor: 0x{self.printer_vendor_id:04x}, product: 0x{self.printer_product_id:04x})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize printer: {e}")
            self.logger.warning("Tip: Check USB vendor and product IDs with: lsusb")
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

    async def print_job(self, job_id: Optional[int], message_content: Optional[str],
                       image_content: Optional[str],
                       from_name: Optional[str] = None, date_str: Optional[str] = None) -> bool:
        """Print a job to the ESC/POS printer (or simulate if not available).

        Args:
            job_id: Unique job identifier (unused, for compatibility)
            message_content: Optional text message to print
            image_content: Optional base64-encoded image to print
            from_name: Sender (IP or friendship token name)
            date_str: ISO format datetime string

        Returns:
            True if print succeeded, False otherwise
        """
        self.job_count += 1

        # Log what we're printing
        content_types = []
        if message_content:
            content_types.append("message")
        if image_content:
            content_types.append("image")
        content_desc = " + ".join(content_types) if content_types else "unknown"
        self.logger.info(f"Printing: {content_desc} from {from_name}")

        try:
            # Print text message if provided
            if message_content:
                await self._print_message(message_content, from_name, date_str)

            # Print image if provided
            if image_content:
                await self._print_image(image_content, from_name, date_str)

            # Add spacing and cut after all content
            if self.printer:
                self.printer.text("\n\n")  # Add blank lines at end
                self.printer.cut()  # Cut the paper

        except Exception as e:
            self.failure_count += 1
            self.logger.error(f"Print failed ({self.success_count} / {self.failure_count}): {e}")
            return False

        self.success_count += 1
        self.logger.info(f"Success! ({self.success_count} / {self.failure_count})")
        return True

    async def _print_message(self, message_content: str, from_name: Optional[str] = None,
                            date_str: Optional[str] = None) -> None:
        """Print a text message to the ESC/POS printer.

        Args:
            message_content: Text message to print
            from_name: Sender (IP or friendship token name)
            date_str: ISO format datetime string
        """
        # Format message with headers if metadata is provided
        if from_name and date_str:
            formatted_content = self._format_message(message_content, from_name, date_str, "text")
        else:
            formatted_content = message_content

        # Save debug print to file
        self._save_debug_print(formatted_content)

        # Print to actual device if available
        if self.printer:
            await asyncio.sleep(0.1)  # Brief delay for I/O
            self.printer.text(formatted_content)
        else:
            # Simulate printing without device
            await asyncio.sleep(0.5)

    async def _print_image(self, base64_content: str, from_name: Optional[str] = None,
                           date_str: Optional[str] = None) -> None:
        """Print an image to the ESC/POS printer.

        Args:
            base64_content: Base64-encoded image bytes
            from_name: Sender (IP or friendship token name)
            date_str: ISO format datetime string
        """
        # Decode base64 content to binary
        image_bytes = base64.b64decode(base64_content)

        # Save debug image to file
        image_path = self._save_debug_image(image_bytes)
        if image_path:
            self.logger.info(f"Image saved to {image_path}")

        # Print to actual device if available
        if self.printer:
            await asyncio.sleep(0.1)  # Brief delay for I/O

            # Print header with sender info if available
            if from_name and date_str:
                try:
                    dt = datetime.fromisoformat(date_str)
                    readable_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    readable_date = date_str

                header = f"{'-' * 40}\nFrom: {from_name}\nDate: {readable_date}\n{'-' * 40}\n"
                self.printer.text(header)

            # Print the image
            self.printer.image(image_path)
        else:
            # Simulate printing without device
            await asyncio.sleep(0.5)

    async def run(self):
        """Main client loop - connect and process jobs."""
        self.logger.info("Printer Client Starting")
        self.logger.info(f"Server: {self.server_url}")

        uri = f"{self.server_url}?token={self.auth_token}"

        connection_attempts = 0
        while True:
            try:
                connection_attempts += 1
                self.logger.info(f"Connecting to server (attempt {connection_attempts})...")

                async with websockets.connect(uri) as websocket:
                    connection_attempts = 0
                    self.logger.info("Connected to server successfully")

                    # Process messages indefinitely
                    while True:
                        try:
                            # Receive job from server
                            message = await websocket.recv()
                            self.logger.info("Message received")

                            job_data = json.loads(message)

                            message_content = job_data.get("message")
                            image_content = job_data.get("image")
                            from_name = job_data.get("from", "unknown")
                            date_str = job_data.get("date")

                            # Print the job (both message and/or image)
                            success = await self.print_job(None, message_content, image_content, from_name, date_str)

                            # Send acknowledgment
                            if success:
                                ack = {"status": "success"}
                            else:
                                ack = {"status": "failed", "error_message": "Print failed"}

                            await websocket.send(json.dumps(ack))

                        except json.JSONDecodeError as e:
                            self.logger.error(f"Failed to parse message: {e}")
                            # Send failure acknowledgment
                            await websocket.send(json.dumps({"status": "failed", "error_message": str(e)}))

            except websockets.exceptions.ConnectionClosed:
                self.logger.warning("Connection closed by server")
                self.logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

            except websockets.exceptions.InvalidStatusCode as e:
                self.logger.error(f"Authentication failed (invalid token?): {e}")
                self.logger.info("Exiting...")
                break

            except Exception as e:
                self.logger.error(f"Connection error: {e}")
                self.logger.info("Retrying in 5 seconds...")
                await asyncio.sleep(5)

    def cleanup(self):
        """Clean up resources, particularly closing the printer connection."""
        if self.printer:
            try:
                self.printer.close()
                self.logger.info("Printer connection closed")
            except Exception as e:
                self.logger.warning(f"Error closing printer: {e}")

    async def run_with_signal_handler(self):
        """Run the client with graceful shutdown on Ctrl+C."""
        try:
            await self.run()
        except KeyboardInterrupt:
            self.logger.warning("")
            self.logger.warning("Shutting down...")
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
