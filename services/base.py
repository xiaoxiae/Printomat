"""Base class for Printomat services."""

import argparse
import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Optional
import aiohttp

from config import ServiceConfig


class BaseService(ABC):
    """Base class for services that connect to the Printomat server.

    Services can:
    - Run periodic tasks via the loop() method
    - Send print requests to the server via HTTP POST
    """

    def __init__(self, server_url: str, service_name: str, service_token: str, print_on_start: bool = False):
        """Initialize the service.

        Args:
            server_url: HTTP URL of the server (e.g., "http://localhost:8000")
            service_name: Name to identify this service
            service_token: Authentication token for services
            print_on_start: Whether to print immediately on startup (default: False)
        """
        self.server_url = server_url
        self.service_name = service_name
        self.service_token = service_token
        self.print_on_start = print_on_start
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
        if not message and not image:
            self.logger.error("Cannot send print request: at least message or image must be provided")
            return

        data = {"token": self.service_token}
        if message:
            data["message"] = message
        if image:
            data["image"] = image

        try:
            submit_url = f"{self.server_url}/submit"
            async with aiohttp.ClientSession() as session:
                async with session.post(submit_url, json=data) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        self.logger.info(f"Print request queued successfully (message={bool(message)}, image={bool(image)})")
                    else:
                        response_text = await response.text()
                        self.logger.error(f"Failed to send print request: HTTP {response.status} - {response_text}")
        except Exception as e:
            self.logger.error(f"Failed to send print request: {e}")

    async def run(self) -> None:
        """Run the service.

        This method runs the service's loop method.
        """
        self.logger.info(f"Starting '{self.service_name}' service...")

        try:
            self._running = True
            await self.loop()
        except Exception as e:
            self.logger.error(f"Error in service loop: {e}", exc_info=True)
        finally:
            self._running = False
            self.logger.info("Service stopped")

    @classmethod
    def run_from_config(cls) -> None:
        """Run the service from configuration file.

        This method loads configuration from config.toml, creates an instance
        of the service, and runs it. The service name is automatically derived
        from the class name.
        """
        # Parse command-line arguments
        parser = argparse.ArgumentParser(description=f"Run {cls.__name__}")
        parser.add_argument(
            '--print',
            action='store_true',
            help='Print immediately on startup'
        )
        args = parser.parse_args()

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

        # Determine print_on_start: command-line flag takes precedence over config
        print_on_start = args.print or service_config.get("print_on_start", False)

        # Create service instance with config
        service = cls.from_config(
            server_url=server_url,
            service_name=service_name,
            service_token=service_token,
            print_on_start=print_on_start,
            config=config
        )

        print(f"Starting {service_name} service...")
        print(f"Server: {server_url}")
        if print_on_start:
            print(f"Print on startup: enabled")

        try:
            asyncio.run(service.run())
        except KeyboardInterrupt:
            print(f"\n{service_name.title()} service stopped by user")

    @classmethod
    def from_config(cls, server_url: str, service_name: str, service_token: str, print_on_start: bool, config):
        """Create a service instance from configuration.

        Subclasses can override this to extract service-specific settings.

        Args:
            server_url: HTTP URL of the server
            service_name: Name of the service
            service_token: Authentication token
            print_on_start: Whether to print immediately on startup
            config: ServiceConfig instance

        Returns:
            Service instance
        """
        return cls(
            server_url=server_url,
            service_name=service_name,
            service_token=service_token,
            print_on_start=print_on_start
        )
