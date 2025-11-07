import tomli
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """Load and manage configuration from .toml file."""

    def __init__(self, config_path: str = "config.toml"):
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from .toml file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "rb") as f:
            self._config = tomli.load(f)

    def get_server_url(self) -> str:
        """Get the WebSocket server URL."""
        return self._config.get("server", {}).get("url", "ws://localhost:8000/ws")

    def get_auth_token(self) -> str:
        """Get the printer authentication token."""
        return self._config.get("server", {}).get("auth_token", "secret-printer-token-here")

    def get_printer_vendor_id(self) -> Optional[int]:
        """Get the USB vendor ID for the printer (or None if not configured)."""
        vendor = self._config.get("printer", {}).get("vendor_id")
        if vendor is None:
            return None
        # Support both hex and decimal strings
        if isinstance(vendor, str):
            return int(vendor, 0)
        return vendor

    def get_printer_product_id(self) -> Optional[int]:
        """Get the USB product ID for the printer (or None if not configured)."""
        product = self._config.get("printer", {}).get("product_id")
        if product is None:
            return None
        # Support both hex and decimal strings
        if isinstance(product, str):
            return int(product, 0)
        return product
