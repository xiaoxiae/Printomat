import tomli
import tomli_w
import unicodedata
import re
import secrets
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """Load and manage configuration from .toml file."""

    @staticmethod
    def generate_label_from_name(name: str) -> str:
        """Generate a label from a name using unicode normalization and snake_case.

        Example: "Kačka Sulková" -> "kacka_sulkova"
        """
        # Normalize unicode characters to ASCII equivalents
        normalized = unicodedata.normalize('NFKD', name)
        ascii_str = normalized.encode('ascii', 'ignore').decode('ascii')

        # Convert to lowercase
        lowercase = ascii_str.lower()

        # Replace spaces and hyphens with underscores
        underscored = re.sub(r'[\s\-]+', '_', lowercase)

        # Remove any remaining non-alphanumeric characters (except underscores)
        cleaned = re.sub(r'[^a-z0-9_]', '', underscored)

        # Remove consecutive underscores
        final = re.sub(r'_+', '_', cleaned)

        # Remove leading/trailing underscores
        return final.strip('_')

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

        # Ensure all friendship tokens have a token value
        self._ensure_tokens_have_values()

    def reload(self) -> None:
        """Reload configuration from file (for hot-reloading tokens)."""
        self.load()

    def _save(self) -> None:
        """Save configuration to file."""
        with open(self.config_path, "w") as f:
            f.write(tomli_w.dumps(self._config))

    def _ensure_tokens_have_values(self) -> None:
        """Ensure all friendship tokens have a token value. Auto-generate if missing."""
        if "friendship_tokens" not in self._config:
            return

        tokens_updated = False
        for token_data in self._config["friendship_tokens"]:
            if not token_data.get("token"):
                # Auto-generate token
                token_data["token"] = secrets.token_hex(4)
                tokens_updated = True
                print(f"Generated missing token for '{token_data.get('name', token_data.get('label', 'unknown'))}': {token_data['token']}")

        if tokens_updated:
            self._save()

    def get_database_url(self) -> str:
        """Build SQLite connection URL from config."""
        db_config = self._config.get("database", {})
        db_path = db_config.get("path", "receipt_printer.db")

        return f"sqlite:///{db_path}"

    def get_printer_token(self) -> str:
        """Get the printer client authentication token."""
        return self._config.get("printer", {}).get("auth_token", "")

    def get_friendship_tokens(self) -> list:
        """Get all configured friendship tokens."""
        return self._config.get("friendship_tokens", [])

    def get_friendship_token_by_value(self, token_value: str) -> Optional[Dict[str, str]]:
        """Find a friendship token by its token value."""
        tokens = self.get_friendship_tokens()
        for token_data in tokens:
            if token_data.get("token") == token_value:
                return token_data
        return None

    def get_queue_max_size(self) -> int:
        """Get maximum queue size."""
        return self._config.get("queue", {}).get("max_size", 1000)

    def get_queue_send_interval(self) -> int:
        """Get queue send interval in seconds."""
        return self._config.get("queue", {}).get("send_interval_seconds", 60)

    def get_rate_limit_cooldown_hours(self) -> int:
        """Get rate limit cooldown in hours."""
        return self._config.get("rate_limit", {}).get("user_cooldown_hours", 1)

    # Token management methods
    def add_friendship_token(self, name: str, message: str, token: str) -> str:
        """Add a new friendship token to the configuration.

        Generates label automatically from name.
        Returns the generated label.
        """
        if "friendship_tokens" not in self._config:
            self._config["friendship_tokens"] = []

        label = self.generate_label_from_name(name)

        # Check if label already exists
        for token_data in self._config["friendship_tokens"]:
            if token_data.get("label") == label:
                raise ValueError(f"Token with label '{label}' already exists")

        self._config["friendship_tokens"].append({
            "name": name,
            "label": label,
            "message": message,
            "token": token
        })
        self._save()
        self.reload()
        return label

    def remove_friendship_token(self, label: str) -> None:
        """Remove a friendship token from the configuration."""
        if "friendship_tokens" not in self._config:
            return

        # Find and remove token by label
        for idx, token_data in enumerate(self._config["friendship_tokens"]):
            if token_data.get("label") == label:
                self._config["friendship_tokens"].pop(idx)
                self._save()
                self.reload()
                return

        raise ValueError(f"Token with label '{label}' not found")
