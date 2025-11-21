#!/usr/bin/env python3
"""Echo service for Printomat - echoes messages back as print requests."""

import asyncio

from base import BaseService


class EchoService(BaseService):
    """Simple echo service that sends received messages back to the printer.
    """

    async def receive(self, message: dict) -> None:
        """Handle a message received from the server.

        Echo the message back as a print request.

        Args:
            message: JSON message from the server (e.g., {"message": "hello"})
        """
        self.logger.info(f"Received message: {message}")

        # Extract the message content
        message_text = message.get("message", "")

        if message_text:
            # Echo it back as a print request
            await self.send_print_request(message=message_text)
            self.logger.info(f"Echoed message: {message_text}")
        else:
            self.logger.warning("Received empty message, nothing to echo")

    async def loop(self) -> None:
        """Service-specific loop.

        Reads from stdin and sends any input as a print request.
        """
        self.logger.info("Echo service loop started - type messages to send to printer")
        print("Type messages to send to printer (Ctrl+C to quit):")

        loop = asyncio.get_event_loop()

        while True:
            try:
                # Read from stdin asynchronously
                user_input = await loop.run_in_executor(None, input, "> ")

                if user_input.strip():
                    # Send the input as a print request
                    await self.send_print_request(message=user_input.strip())
                    self.logger.info(f"Sent user input to printer: {user_input.strip()}")

            except EOFError:
                # Handle EOF (e.g., when stdin is closed)
                self.logger.info("Stdin closed, stopping input loop")
                break
            except Exception as e:
                self.logger.error(f"Error reading input: {e}")
                await asyncio.sleep(1)


def main():
    """Run the echo service."""
    EchoService.run_from_config()


if __name__ == "__main__":
    main()
