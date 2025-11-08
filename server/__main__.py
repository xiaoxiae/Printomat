"""Entry point for running the server module."""

import uvicorn
from .app import app
from .config import Config

if __name__ == "__main__":
    config = Config()
    host = config.get_server_host()
    port = config.get_server_port()
    uvicorn.run(app, host=host, port=port)
