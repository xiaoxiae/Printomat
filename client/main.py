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
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional
import time


class PrinterClient:
    """WebSocket client for receiving and processing print jobs."""

    def __init__(self, server_url: str, auth_token: str, output_dir: Optional[str] = None, verbose: bool = True):
        """Initialize the printer client.

        Args:
            server_url: WebSocket server URL (e.g., ws://localhost:8000/ws)
            auth_token: Authentication token for the printer
            output_dir: Directory to save printed jobs (optional)
            verbose: Print detailed logging
        """
        self.server_url = server_url
        self.auth_token = auth_token
        self.output_dir = Path(output_dir) if output_dir else None
        self.verbose = verbose
        self.job_count = 0
        self.success_count = 0
        self.failure_count = 0

        # Create output directory if specified
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

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

        if self.verbose or level in ["ERROR", "WARN"]:
            print(f"[{timestamp}] {symbol} {message}", end=end)

    def get_server_address(self) -> str:
        """Extract server address from URL for display."""
        # Parse ws://localhost:8000/ws -> localhost:8000
        return self.server_url.replace("ws://", "").replace("wss://", "").split("/")[0]

    async def print_job(self, job_id: int, content: str, job_type: str) -> bool:
        """Simulate printing a job and return success/failure.

        Args:
            job_id: Unique job identifier
            content: Content to print
            job_type: Type of content (text, image, etc.)

        Returns:
            True if print succeeded, False otherwise
        """
        self.job_count += 1

        # Save to file if output directory specified
        if self.output_dir:
            filename = self.output_dir / f"job_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            try:
                with open(filename, "w") as f:
                    f.write(f"Job ID: {job_id}\n")
                    f.write(f"Type: {job_type}\n")
                    f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                    f.write("=" * 40 + "\n")
                    f.write(content)
                self.log(f"Saved job {job_id} to {filename}")
            except Exception as e:
                self.log(f"Failed to save job {job_id}: {e}", level="ERROR")
                return False

        # Simulate printing with a brief delay
        # In a real implementation, this would interact with actual printer hardware
        print_time = 0.5  # seconds
        self.log(f"Printing job {job_id} ({job_type}): {len(content)} chars... ", level="INFO", end="")
        await asyncio.sleep(print_time)
        print()  # newline after the in-place message

        self.success_count += 1
        self.log(f"Job {job_id} printed successfully", level="SUCCESS")
        return True

    async def run(self):
        """Main client loop - connect and process jobs."""
        self.log(f"Printer Client Starting")
        self.log(f"Server: {self.get_server_address()}")
        self.log(f"Output directory: {self.output_dir or '(none - memory only)'}")
        self.log("")

        uri = f"{self.server_url}?token={self.auth_token}"

        connection_attempts = 0
        while True:
            try:
                connection_attempts += 1
                self.log(f"Connecting to server (attempt {connection_attempts})...")

                async with websockets.connect(uri) as websocket:
                    connection_attempts = 0
                    self.log(f"Connected to server successfully", level="SUCCESS")
                    self.log("")

                    # Process messages indefinitely
                    while True:
                        try:
                            # Receive job from server
                            message = await websocket.recv()
                            job_data = json.loads(message)

                            job_id = job_data.get("id")
                            content = job_data.get("content", "")
                            job_type = job_data.get("type", "text")

                            self.log(f"Received job (type={job_type}, size={len(content)} chars)")

                            # Print the job
                            success = await self.print_job(job_id, content, job_type)

                            # Send acknowledgment
                            if success:
                                ack = {"status": "success"}
                            else:
                                ack = {"status": "failed", "error_message": "Print failed"}

                            await websocket.send(json.dumps(ack))
                            self.log(f"Sent acknowledgment (status={'success' if success else 'failed'})")
                            self.log("")

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

    def print_stats(self):
        """Print statistics about processed jobs."""
        self.log("")
        self.log("=" * 50)
        self.log("Statistics")
        self.log("=" * 50)
        self.log(f"Total jobs received: {self.job_count}")
        self.log(f"Successful prints: {self.success_count}")
        self.log(f"Failed prints: {self.failure_count}")
        if self.job_count > 0:
            success_rate = (self.success_count / self.job_count) * 100
            self.log(f"Success rate: {success_rate:.1f}%")

    async def run_with_signal_handler(self):
        """Run the client with graceful shutdown on Ctrl+C."""
        try:
            await self.run()
        except KeyboardInterrupt:
            self.log("", level="WARN")
            self.log("Shutting down...", level="WARN")
            self.print_stats()
            sys.exit(0)


def main():
    """Command-line interface for the printer client."""
    parser = argparse.ArgumentParser(
        description="Receipt Printer Desktop Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Connect to local server with default settings
  python printer_client.py

  # Connect to remote server with custom token
  python printer_client.py --server ws://192.168.1.100:8000/ws --token my-secret-token

  # Save printed jobs to a directory
  python printer_client.py --output-dir ./printed-jobs

  # Quiet mode (only show errors)
  python printer_client.py --quiet
        """
    )

    parser.add_argument(
        "--server",
        default="ws://localhost:8000/ws",
        help="WebSocket server URL (default: ws://localhost:8000/ws)"
    )
    parser.add_argument(
        "--token",
        default="secret-printer-token-here",
        help="Printer authentication token (default: secret-printer-token-here)"
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to save printed jobs (optional)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Quiet mode - only show errors"
    )

    args = parser.parse_args()

    # Create and run client
    client = PrinterClient(
        server_url=args.server,
        auth_token=args.token,
        output_dir=args.output_dir,
        verbose=not args.quiet
    )

    # Run with signal handler for graceful shutdown
    try:
        asyncio.run(client.run_with_signal_handler())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
