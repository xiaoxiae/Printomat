#!/usr/bin/env python3
"""Chess puzzle service for Printomat - sends daily chess puzzles as print requests."""

import asyncio
import base64
import sys
from datetime import datetime
from typing import Optional

import chess
import chess.svg
import requests
from cairosvg import svg2png

from base import BaseService


class ChessPuzzleService(BaseService):
    """Chess puzzle service that fetches daily puzzle from Lichess and sends it to the printer.

    Fetches the daily puzzle from Lichess API, renders the position as a PNG,
    and sends it as a print request.
    """

    def __init__(self, server_url: str, service_name: str, service_token: str,
                 print_hour: int = 8, print_minute: int = 0):
        """Initialize the chess puzzle service.

        Args:
            server_url: WebSocket URL of the server
            service_name: Name to identify this service
            service_token: Authentication token for services
            print_hour: Hour of day to print (0-23, default: 8 for 8 AM)
            print_minute: Minute of hour to print (0-59, default: 0)
        """
        super().__init__(server_url, service_name, service_token)
        self.print_hour = print_hour
        self.print_minute = print_minute

    async def receive(self, message: dict) -> None:
        """Handle a message received from the server.

        Args:
            message: JSON message from the server
        """
        self.logger.info(f"Received message: {message}")
        # Print puzzle when any message is received
        await self._print_puzzle()

    def _fetch_puzzle_data(self) -> Optional[dict]:
        """Fetch daily puzzle from Lichess API.

        Returns:
            Puzzle data dict or None if request failed
        """
        url = "https://lichess.org/api/puzzle/daily"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to fetch puzzle data: {e}")
            return None

    def _create_puzzle_image(self, data: dict) -> Optional[str]:
        """Create puzzle board image and return as base64-encoded PNG.

        Args:
            data: Puzzle data from Lichess API

        Returns:
            Base64-encoded PNG image or None if creation failed
        """
        try:
            puzzle = data.get("puzzle", {})
            game = data.get("game", {})

            # Get puzzle details
            puzzle_id = puzzle.get("id", "unknown")
            rating = puzzle.get("rating", "?")
            themes = puzzle.get("themes", [])
            solution = puzzle.get("solution", [])

            # Parse the PGN to get to the puzzle position
            pgn = game.get("pgn", "")
            initial_ply = puzzle.get("initialPly", 0)

            # Create board and apply moves
            board = chess.Board()
            moves = pgn.split()

            # Apply moves up to the puzzle position
            for i, move in enumerate(moves):
                if i >= initial_ply:
                    break
                try:
                    board.push_san(move)
                except Exception as e:
                    self.logger.warning(f"Failed to parse move '{move}': {e}")
                    break

            # Determine orientation (show from side to move)
            orientation = board.turn

            # Get first move of solution for highlighting
            last_move = None
            if initial_ply > 0 and moves:
                try:
                    # Create a temporary board to parse the last move
                    temp_board = chess.Board()
                    for i, move in enumerate(moves[:initial_ply]):
                        temp_board.push_san(move)
                    last_move = temp_board.peek()
                except:
                    pass

            # Create SVG with larger size for better printing
            svg_data = chess.svg.board(
                board,
                orientation=orientation,
                lastmove=last_move,
                size=800,
                coordinates=True
            )

            # Convert SVG to PNG
            png_data = svg2png(bytestring=svg_data.encode('utf-8'), output_width=800)

            # Encode to base64
            image_base64 = base64.b64encode(png_data).decode('utf-8')

            return image_base64

        except Exception as e:
            self.logger.error(f"Failed to create puzzle image: {e}", exc_info=True)
            return None

    async def _print_puzzle(self) -> None:
        """Fetch puzzle data and send it to the printer."""
        try:
            self.logger.info("Fetching daily chess puzzle...")
            data = self._fetch_puzzle_data()

            if data:
                # Create puzzle image
                image_base64 = self._create_puzzle_image(data)

                if image_base64:
                    # Send only the image, no text message
                    await self.send_print_request(
                        image=image_base64
                    )
                    self.logger.info("Chess puzzle sent to printer")
                else:
                    self.logger.warning("Failed to create puzzle image, skipping this update")
            else:
                self.logger.warning("Failed to fetch puzzle data, skipping this update")

        except Exception as e:
            self.logger.error(f"Error printing puzzle: {e}", exc_info=True)

    def _calculate_seconds_until_next_print(self) -> float:
        """Calculate seconds until the next scheduled print time.

        Returns:
            Number of seconds to wait
        """
        now = datetime.now()
        target = now.replace(hour=self.print_hour, minute=self.print_minute, second=0, microsecond=0)

        # If target time has passed today, schedule for tomorrow
        if target <= now:
            target = target.replace(day=target.day + 1)

        return (target - now).total_seconds()

    async def loop(self) -> None:
        """Service loop that fetches and sends chess puzzle once per day at specified time."""
        self.logger.info(
            f"Chess puzzle service started (print time={self.print_hour:02d}:{self.print_minute:02d})"
        )

        while True:
            # Calculate time until next print
            seconds_until_print = self._calculate_seconds_until_next_print()
            self.logger.info(f"Next puzzle print in {seconds_until_print/3600:.1f} hours")

            # Sleep until print time
            await asyncio.sleep(seconds_until_print)

            # Print puzzle at scheduled time
            self.logger.info("Print time reached")
            await self._print_puzzle()


    @classmethod
    def from_config(cls, server_url: str, service_name: str, service_token: str, config):
        """Create a ChessPuzzleService instance from configuration.

        Args:
            server_url: WebSocket URL of the server
            service_name: Name of the service
            service_token: Authentication token
            config: ServiceConfig instance

        Returns:
            ChessPuzzleService instance
        """
        # Get puzzle-specific settings from config
        service_config = config.get_service_config(service_name)

        print_hour = service_config.get("print_hour", 8)
        print_minute = service_config.get("print_minute", 0)

        return cls(
            server_url=server_url,
            service_name=service_name,
            service_token=service_token,
            print_hour=print_hour,
            print_minute=print_minute
        )


def main():
    """Run the chess puzzle service."""
    ChessPuzzleService.run_from_config()


if __name__ == "__main__":
    main()
