import tomli
import tomli_w
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

    def reload(self) -> None:
        """Reload configuration from file (for hot-reloading tokens)."""
        self.load()

    def _save(self) -> None:
        """Save configuration to file."""
        with open(self.config_path, "w") as f:
            f.write(tomli_w.dumps(self._config))

    def get_database_url(self) -> str:
        """Build SQLite connection URL from config."""
        db_config = self._config.get("database", {})
        db_path = db_config.get("path", "receipt_printer.db")

        return f"sqlite:///{db_path}"

    def get_printer_token(self) -> str:
        """Get the printer client authentication token."""
        return self._config.get("printer", {}).get("auth_token", "")

    def get_friendship_tokens(self) -> Dict[str, Dict[str, str]]:
        """Get all configured friendship tokens."""
        return self._config.get("friendship_tokens", {})

    def get_friendship_token_by_value(self, token_value: str) -> Optional[Dict[str, str]]:
        """Find a friendship token by its token value."""
        tokens = self.get_friendship_tokens()
        for key, token_data in tokens.items():
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
    def add_friendship_token(self, label: str, name: str, message: str, token: str) -> None:
        """Add a new friendship token to the configuration."""
        if "friendship_tokens" not in self._config:
            self._config["friendship_tokens"] = {}

        if label in self._config["friendship_tokens"]:
            raise ValueError(f"Token with label '{label}' already exists")

        self._config["friendship_tokens"][label] = {
            "name": name,
            "label": label,
            "message": message,
            "token": token
        }
        self._save()
        self.reload()

    def remove_friendship_token(self, label: str) -> None:
        """Remove a friendship token from the configuration."""
        if "friendship_tokens" not in self._config:
            return

        if label not in self._config["friendship_tokens"]:
            raise ValueError(f"Token with label '{label}' not found")

        del self._config["friendship_tokens"][label]
        self._save()
        self.reload()
