"""Entry point for running the server module."""

import uvicorn
from .app import app
from .config import Config

if __name__ == "__main__":
    config = Config()
    host = config.get_server_host()
    port = config.get_server_port()

    # Set max WebSocket message size to 10MB to handle large base64-encoded images
    uvicorn.run(app, host=host, port=port, ws_max_size=10_000_000)
