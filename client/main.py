#!/usr/bin/env python3
"""Desktop Printer Client - connects to server and prints received jobs.

This is a standalone client that:
1. Connects to the server via WebSocket
2. Receives print jobs
3. Simulates printing (or can be extended for real printers)
4. Sends acknowledgments back to the server
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import sys
import time
import websockets
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config
from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Usb

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class PrinterClient:
    """WebSocket client for receiving and processing print jobs."""

    def __init__(self, server_url: str, auth_token: str,
                 printer_vendor_id: Optional[int] = None, printer_product_id: Optional[int] = None,
                 printer_width_mm: float = 58, printer_dpi: int = 203,
                 printer_profile: Optional[str] = None,
                 printer_in_ep: Optional[int] = None, printer_out_ep: Optional[int] = None,
                 printer_max_width_pixels: Optional[int] = None,
                 font_path: Optional[str] = None):
        """Initialize the printer client.

        Args:
            server_url: WebSocket server URL (e.g., ws://localhost:8000/ws)
            auth_token: Authentication token for the printer
            printer_vendor_id: USB vendor ID for ESC/POS printer (e.g., 0x0471)
            printer_product_id: USB product ID for ESC/POS printer (e.g., 0x0055)
            printer_width_mm: Printer's printing area width in millimeters
            printer_dpi: Printer's DPI (dots per inch)
            printer_profile: ESC/POS printer profile (e.g., 'TM-T88III')
            printer_in_ep: USB IN endpoint address (e.g., 0x82)
            printer_out_ep: USB OUT endpoint address (e.g., 0x04)
            printer_max_width_pixels: Maximum image width in pixels (hardware limit)
            font_path: Path to font file for text rendering
        """
        self.server_url = server_url
        self.auth_token = auth_token
        self.job_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.printer = None
        self.printer_vendor_id = printer_vendor_id
        self.printer_product_id = printer_product_id
        self.printer_width_mm = printer_width_mm
        self.printer_dpi = printer_dpi
        self.printer_profile = printer_profile
        self.printer_in_ep = printer_in_ep
        self.printer_out_ep = printer_out_ep
        self.font_path = font_path

        # Calculate target width, respecting hardware limit
        calculated_width = int(printer_width_mm * printer_dpi / 25.4)
        if printer_max_width_pixels:
            self.target_width_pixels = min(calculated_width, printer_max_width_pixels)
        else:
            self.target_width_pixels = calculated_width

        self.logger = logging.getLogger(__name__)

        # Initialize debug print directory (relative to client module location)
        self.debug_print_dir = Path(__file__).parent / "print"
        self.debug_print_dir.mkdir(exist_ok=True)

        # Initialize ESC/POS printer if credentials provided
        self._initialize_printer()

    def _validate_and_process_image(self, base64_content: str) -> Optional[bytes]:
        """Validate and process an image from base64-encoded content.

        This method:
        1. Validates that the content is a valid image
        2. Resizes to match printer width (respecting hardware limits)
        3. Returns the resized image bytes, or None if validation fails

        Args:
            base64_content: Base64-encoded image bytes

        Returns:
            Resized image bytes if valid, None otherwise
        """
        try:
            # Decode base64 to binary
            image_bytes = base64.b64decode(base64_content)

            # Open and validate image
            image = Image.open(io.BytesIO(image_bytes))
            image.load()  # Force validation

            # Get original dimensions
            orig_width, orig_height = image.size
            self.logger.info(f"Image loaded: {orig_width}x{orig_height} pixels")

            # Resize to printer width (respecting hardware limits)
            target_width_pixels = self.target_width_pixels

            # Calculate target height maintaining aspect ratio
            target_height_pixels = int(target_width_pixels * orig_height / orig_width)

            self.logger.info(
                f"Resizing image to {target_width_pixels}x{target_height_pixels} pixels"
            )

            # Resize image using high-quality resampling
            resized = image.resize(
                (target_width_pixels, target_height_pixels),
                Image.Resampling.LANCZOS
            )

            # Convert to bytes for saving
            output = io.BytesIO()
            resized.save(output, format='GIF')
            return output.getvalue()

        except base64.binascii.Error as e:
            self.logger.error(f"Invalid base64 encoding: {e}")
            return None
        except (OSError, ValueError) as e:
            self.logger.error(f"Failed to load image: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error processing image: {e}")
            return None

    def _text_to_image(self, text: str, font_size: int = 20) -> Image.Image:
        """Convert text to an image with word wrapping.

        Args:
            text: The text to render
            font_size: Font size in pixels

        Returns:
            PIL Image containing the rendered text
        """
        # Use the target width that respects hardware limits
        target_width_pixels = self.target_width_pixels

        # Load font from config or use default
        font = None
        if self.font_path:
            try:
                font = ImageFont.truetype(self.font_path, font_size)
            except (OSError, IOError) as e:
                self.logger.warning(f"Failed to load configured font '{self.font_path}': {e}")

        # Fall back to default font if not configured or failed to load
        if font is None:
            font = ImageFont.load_default()
            if self.font_path:
                self.logger.warning("Using default font as fallback")

        # Create a temporary drawing context to measure text
        temp_img = Image.new('RGB', (1, 1), 'white')
        temp_draw = ImageDraw.Draw(temp_img)

        # Word wrap the text
        lines = []
        paragraphs = text.split('\n')

        for paragraph in paragraphs:
            if not paragraph:
                lines.append('')
                continue

            words = paragraph.split(' ')
            current_line = []

            for word in words:
                test_line = ' '.join(current_line + [word])
                bbox = temp_draw.textbbox((0, 0), test_line, font=font)
                line_width = bbox[2] - bbox[0]

                if line_width <= target_width_pixels - 20:  # 10px padding on each side
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                    else:
                        # Word is too long, add it anyway
                        lines.append(word)

            if current_line:
                lines.append(' '.join(current_line))

        # Calculate image height
        line_height = font_size + 4  # Add some line spacing
        height = len(lines) * line_height + 20  # 10px padding top and bottom

        # Create the actual image
        img = Image.new('RGB', (target_width_pixels, height), 'white')
        draw = ImageDraw.Draw(img)

        # Draw each line
        y = 10  # Top padding
        for line in lines:
            draw.text((10, y), line, fill='black', font=font)
            y += line_height

        return img

    def _concatenate_images_vertically(self, images: list[Image.Image]) -> Image.Image:
        """Concatenate multiple images vertically.

        Args:
            images: List of PIL Images to concatenate

        Returns:
            Single concatenated PIL Image
        """
        if not images:
            raise ValueError("No images to concatenate")

        # All images should have the same width (printer width)
        width = images[0].width
        total_height = sum(img.height for img in images)

        # Create the output image
        result = Image.new('RGB', (width, total_height), 'white')

        # Paste each image
        y_offset = 0
        for img in images:
            result.paste(img, (0, y_offset))
            y_offset += img.height

        return result

    def _create_spacer(self, height_pixels: int = 20) -> Image.Image:
        """Create a white spacer image.

        Args:
            height_pixels: Height of the spacer in pixels

        Returns:
            PIL Image containing white space
        """
        return Image.new('RGB', (self.target_width_pixels, height_pixels), 'white')

    def _create_line(self, thickness_pixels: int = 2) -> Image.Image:
        """Create a black horizontal line separator.

        Args:
            thickness_pixels: Thickness of the line in pixels

        Returns:
            PIL Image containing a black horizontal line
        """
        return Image.new('RGB', (self.target_width_pixels, thickness_pixels), 'black')

    def _initialize_printer(self) -> bool:
        """Initialize connection to ESC/POS printer via USB.

        Returns:
            True if printer initialized successfully, False otherwise
        """
        if not self.printer_profile or not self.printer_vendor_id or not self.printer_product_id:
            self.logger.warning("Printer profile not configured. Skipping initialization.")
            return False

        try:
            self.printer = Usb(
                self.printer_vendor_id,
                self.printer_product_id,
                in_ep=self.printer_in_ep,
                out_ep=self.printer_out_ep,
                profile=self.printer_profile
            )
            self.logger.info(
                f"Printer initialized (vendor: 0x{self.printer_vendor_id:04x}, "
                f"product: 0x{self.printer_product_id:04x}, profile: {self.printer_profile}, "
                f"in_ep: 0x{self.printer_in_ep:02x}, out_ep: 0x{self.printer_out_ep:02x})"
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize printer: {e}")
            self.logger.warning("Tip: Check USB vendor and product IDs with: lsusb")
            self.printer = None
            return False

    async def print_job(self, job_id: Optional[int], message_content: Optional[str],
                       image_content: Optional[str],
                       from_name: Optional[str] = None, date_str: Optional[str] = None) -> bool:
        """Print a job to the ESC/POS printer (or simulate if not available).

        Creates a single image containing header, optional message, optional user image,
        and footer, then prints it.

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
            images_to_concat = []

            # 1. Create header with from + date
            if from_name and date_str:
                try:
                    dt = datetime.fromisoformat(date_str)
                    readable_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    readable_date = date_str

                # Top thick separator
                images_to_concat.append(self._create_line(thickness_pixels=4))

                # Header text
                header_text = f"From: {from_name}\nDate: {readable_date}"
                header_img = self._text_to_image(header_text)
                images_to_concat.append(header_img)

                # Thin separator after header
                images_to_concat.append(self._create_line(thickness_pixels=1))

            # 2. Add message content if provided
            if message_content:
                message_img = self._text_to_image(message_content)
                images_to_concat.append(message_img)

            # 3. Add user image if provided
            if image_content:
                # Add spacer if we have both message and image
                if message_content:
                    images_to_concat.append(self._create_spacer(height_pixels=5))

                # Validate and process the image
                image_bytes = self._validate_and_process_image(image_content)
                if image_bytes is None:
                    raise ValueError("Image validation or processing failed")

                # Load the processed image
                user_image = Image.open(io.BytesIO(image_bytes))
                images_to_concat.append(user_image)

                images_to_concat.append(self._create_spacer(height_pixels=5))

            # 4. Add bottom thick separator
            images_to_concat.append(self._create_line(thickness_pixels=4))

            # 5. Concatenate all images
            if not images_to_concat:
                raise ValueError("No content to print")

            final_image = self._concatenate_images_vertically(images_to_concat)

            # 6. Save the final image for debugging
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            debug_path = self.debug_print_dir / f"{timestamp}.gif"
            final_image.save(debug_path, format='GIF')
            self.logger.info(f"Final image saved to {debug_path}")

            # 7. Print to actual device if available
            if self.printer:
                await asyncio.sleep(0.1)  # Brief delay for I/O
                self.printer.image(str(debug_path))
                self.printer.cut()
            else:
                # Simulate printing without device
                await asyncio.sleep(0.5)

        except Exception as e:
            self.failure_count += 1
            self.logger.error(f"Print failed ({self.success_count} / {self.failure_count}): {e}")
            return False

        self.success_count += 1
        self.logger.info(f"Success! ({self.success_count} / {self.failure_count})")
        return True

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

    def test_print(self):
        """Print a test message to verify printer is working."""
        if not self.printer:
            self.logger.error("Printer not initialized. Check USB vendor and product IDs in config.")
            return False

        try:
            self.logger.info("Printing test message...")
            separator = "=" * 40
            test_message = f"""{separator}
PRINTER TEST
{separator}

Printomat Printer Client

Test: OK
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{separator}
"""
            self.printer.text(test_message)
            self.printer.cut()
            self.logger.info("Test print completed successfully")
            return True
        except Exception as e:
            self.logger.error(f"Test print failed: {e}")
            return False
        finally:
            self.cleanup()

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
    parser = argparse.ArgumentParser(
        description="Printomat Printer Client - connects to server and prints jobs"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run a test print and exit (verifies printer is working)"
    )
    args = parser.parse_args()

    # Load configuration (look for config.toml in the client directory)
    config_path = Path(__file__).parent / "config.toml"
    config = Config(str(config_path))

    # Create client
    client = PrinterClient(
        server_url=config.get_server_url(),
        auth_token=config.get_auth_token(),
        printer_vendor_id=config.get_printer_vendor_id(),
        printer_product_id=config.get_printer_product_id(),
        printer_width_mm=config.get_printer_width_mm(),
        printer_dpi=config.get_printer_dpi(),
        printer_profile=config.get_printer_profile(),
        printer_in_ep=config.get_printer_in_ep(),
        printer_out_ep=config.get_printer_out_ep(),
        printer_max_width_pixels=config.get_printer_max_width_pixels(),
        font_path=config.get_font_path()
    )

    # Run in test mode or normal mode
    if args.test:
        success = client.test_print()
        sys.exit(0 if success else 1)
    else:
        # Run with signal handler for graceful shutdown
        try:
            asyncio.run(client.run_with_signal_handler())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
