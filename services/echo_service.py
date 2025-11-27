#!/usr/bin/env python3
"""Echo service for Printomat - reads from stdin and sends to printer."""

import asyncio

from base import BaseService


class EchoService(BaseService):
    """Simple echo service that reads from stdin and sends to the printer."""

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
