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

    def get_printer_width_mm(self) -> float:
        """Get the printer's printing area width in millimeters."""
        return self._config.get("printer", {}).get("width_mm", 58)

    def get_printer_dpi(self) -> int:
        """Get the printer's DPI (dots per inch)."""
        return self._config.get("printer", {}).get("dpi", 203)

    def get_printer_profile(self) -> Optional[str]:
        """Get the printer profile for ESC/POS (e.g., 'TM-T88III')."""
        return self._config.get("printer", {}).get("profile")

    def get_printer_in_ep(self) -> Optional[int]:
        """Get the USB IN endpoint address for the printer (e.g., 0x82)."""
        ep = self._config.get("printer", {}).get("in_ep")
        if ep is None:
            return None
        # Support both hex and decimal strings
        if isinstance(ep, str):
            return int(ep, 0)
        return ep

    def get_printer_out_ep(self) -> Optional[int]:
        """Get the USB OUT endpoint address for the printer (e.g., 0x04)."""
        ep = self._config.get("printer", {}).get("out_ep")
        if ep is None:
            return None
        # Support both hex and decimal strings
        if isinstance(ep, str):
            return int(ep, 0)
        return ep

    def get_printer_max_width_pixels(self) -> Optional[int]:
        """Get the maximum image width in pixels the printer can handle."""
        return self._config.get("printer", {}).get("max_width_pixels")

    def get_font_path(self) -> Optional[str]:
        """Get the path to the font file for text rendering."""
        return self._config.get("printer", {}).get("font_path")
