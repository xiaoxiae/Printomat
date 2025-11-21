"""Base class for Printomat services."""

import asyncio
import json
import logging
import sys
from abc import ABC, abstractmethod
from typing import Optional
import websockets

from websockets.client import WebSocketClientProtocol

from config import ServiceConfig


class BaseService(ABC):
    """Base class for services that connect to the Printomat server.

    Services can:
    - Receive messages from the server via the receive() method
    - Run periodic tasks via the loop() method
    - Send print requests back to the server
    """

    def __init__(self, server_url: str, service_name: str, service_token: str):
        """Initialize the service.

        Args:
            server_url: WebSocket URL of the server (e.g., "ws://localhost:9900")
            service_name: Name to identify this service
            service_token: Authentication token for services
        """
        self.server_url = server_url
        self.service_name = service_name
        self.service_token = service_token
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.logger = self._setup_logger()
        self._running = False

    def _setup_logger(self) -> logging.Logger:
        """Create a dedicated logger for this service."""
        logger = logging.getLogger(f"Service.{self.service_name}")
        logger.setLevel(logging.INFO)

        # Remove any existing handlers
        logger.handlers.clear()

        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(console_handler)

        # Prevent propagation
        logger.propagate = False

        return logger

    @abstractmethod
    async def receive(self, message: dict) -> None:
        """Handle a message received from the server.

        Args:
            message: JSON message from the server (e.g., {"message": "hello"})
        """
        pass

    @abstractmethod
    async def loop(self) -> None:
        """Service-specific loop for periodic tasks.

        This method should run continuously and handle periodic tasks
        like fetching weather data, sending scheduled messages, etc.

        Use asyncio.sleep() to add delays between iterations.
        """
        pass

    async def send_print_request(self, message: Optional[str] = None, image: Optional[str] = None) -> None:
        """Send a print request to the server.

        Args:
            message: Text message to print
            image: Base64-encoded image to print
        """
        if not self.websocket:
            self.logger.error("Cannot send print request: not connected")
            return

        if not message and not image:
            self.logger.error("Cannot send print request: at least message or image must be provided")
            return

        data = {}
        if message:
            data["message"] = message
        if image:
            data["image"] = image

        try:
            await self.websocket.send(json.dumps(data))
            self.logger.info(f"Sent print request (message={bool(message)}, image={bool(image)})")
        except Exception as e:
            self.logger.error(f"Failed to send print request: {e}")

    async def _receive_handler(self) -> None:
        """Handle incoming messages from the server."""
        try:
            async for message_text in self.websocket:
                try:
                    message_data = json.loads(message_text)
                    self.logger.debug(f"Received message: {message_data}")
                    await self.receive(message_data)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse message JSON: {e}")
                except Exception as e:
                    self.logger.error(f"Error handling received message: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("Connection closed by server")
        except Exception as e:
            self.logger.error(f"Error in receive handler: {e}", exc_info=True)
        finally:
            self._running = False

    async def _loop_handler(self) -> None:
        """Run the service's loop method."""
        try:
            await self.loop()
        except Exception as e:
            self.logger.error(f"Error in service loop: {e}", exc_info=True)
        finally:
            self._running = False

    async def run(self) -> None:
        """Connect to the server and run the service.

        This method connects to the server WebSocket endpoint,
        authenticates, and runs both the receive handler and loop concurrently.
        """
        # Build WebSocket URL with authentication
        ws_url = f"{self.server_url}/ws/service?token={self.service_token}&name={self.service_name}"

        self.logger.info(f"Connecting to {self.server_url}...")

        try:
            async with websockets.connect(ws_url) as websocket:
                self.websocket = websocket
                self._running = True
                self.logger.info(f"Connected as '{self.service_name}'")

                # Run receive handler and loop concurrently
                receive_task = asyncio.create_task(self._receive_handler())
                loop_task = asyncio.create_task(self._loop_handler())

                # Wait for either task to complete (or fail)
                done, pending = await asyncio.wait(
                    [receive_task, loop_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel any pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                self.logger.info("Service stopped")

        except websockets.exceptions.InvalidStatusCode as e:
            if e.status_code == 1008:
                self.logger.error("Authentication failed: invalid or missing token")
            else:
                self.logger.error(f"Connection failed with status {e.status_code}")
        except Exception as e:
            self.logger.error(f"Connection error: {e}", exc_info=True)
        finally:
            self.websocket = None
            self._running = False

    @classmethod
    def run_from_config(cls) -> None:
        """Run the service from configuration file.

        This method loads configuration from config.toml, creates an instance
        of the service, and runs it. The service name is automatically derived
        from the class name.
        """
        # Derive service name from class name (e.g., EchoService -> echo)
        service_name = cls.__name__
        if service_name.endswith("Service"):
            service_name = service_name[:-7]  # Remove "Service" suffix
        service_name = service_name.lower()

        # Load configuration
        try:
            config = ServiceConfig()
        except FileNotFoundError as e:
            print(f"Error: {e}")
            print("Please create services/config.toml with the required configuration.")
            sys.exit(1)

        # Check if service is enabled
        if not config.is_service_enabled(service_name):
            print(f"Service '{service_name}' is not enabled in config.toml")
            print(f"Set [services.{service_name}].enabled = true to enable it.")
            sys.exit(1)

        # Get global settings
        server_url = config.get_server_url()
        service_token = config.get_service_token()

        # Get service-specific config
        service_config = config.get_service_config(service_name)

        # Create service instance with config
        service = cls.from_config(
            server_url=server_url,
            service_name=service_name,
            service_token=service_token,
            config=config
        )

        print(f"Starting {service_name} service...")
        print(f"Server: {server_url}")

        try:
            asyncio.run(service.run())
        except KeyboardInterrupt:
            print(f"\n{service_name.title()} service stopped by user")

    @classmethod
    def from_config(cls, server_url: str, service_name: str, service_token: str, config):
        """Create a service instance from configuration.

        Subclasses can override this to extract service-specific settings.

        Args:
            server_url: WebSocket URL of the server
            service_name: Name of the service
            service_token: Authentication token
            config: ServiceConfig instance

        Returns:
            Service instance
        """
        return cls(
            server_url=server_url,
            service_name=service_name,
            service_token=service_token
        )
