"""Configuration management for Printomat services."""

import tomli
from pathlib import Path
from typing import Any, Dict, Optional


class ServiceConfig:
    """Load and manage service configuration from config.toml file."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the configuration.

        Args:
            config_path: Path to config.toml file. If None, looks for config.toml
                        in the services directory.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.toml"
        elif not Path(config_path).is_absolute():
            config_path = Path(__file__).parent / config_path

        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from .toml file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "rb") as f:
            self._config = tomli.load(f)

    def reload(self) -> None:
        """Reload configuration from file."""
        self.load()

    # Global settings
    def get_server_url(self) -> str:
        """Get the server WebSocket URL."""
        return self._config.get("global", {}).get("server_url", "ws://localhost:9900")

    def get_service_token(self) -> str:
        """Get the service authentication token."""
        return self._config.get("global", {}).get("service_token", "service_secret_token_12345")

    # Service-specific settings
    def get_service_config(self, service_name: str) -> Dict[str, Any]:
        """Get configuration for a specific service.

        Args:
            service_name: Name of the service (e.g., "echo", "weather")

        Returns:
            Dictionary of service-specific configuration
        """
        return self._config.get("services", {}).get(service_name, {})

    def is_service_enabled(self, service_name: str) -> bool:
        """Check if a service is enabled.

        Args:
            service_name: Name of the service

        Returns:
            True if enabled, False otherwise (default: False)
        """
        service_config = self.get_service_config(service_name)
        return service_config.get("enabled", False)
