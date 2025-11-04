# Printer Client

Standalone WebSocket client that connects to the receipt printer server and processes print jobs.

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
python printer_client.py
```

This connects to `ws://localhost:8000/ws` with the default token.

## Usage

```bash
# Basic usage
python printer_client.py

# Save printed jobs to disk
python printer_client.py --output-dir ./printed-jobs

# Remote server connection
python printer_client.py --server ws://192.168.1.100:8000/ws --token my-token

# Quiet mode (errors only)
python printer_client.py --quiet
```

## Command-Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--server` | `ws://localhost:8000/ws` | WebSocket server URL |
| `--token` | `secret-printer-token-here` | Printer authentication token |
| `--output-dir` | None | Directory to save printed jobs (optional) |
| `--quiet` | False | Only show errors (no info messages) |

## How It Works

1. Connects to server via WebSocket with authentication token
2. Receives print jobs: `{"id": <int>, "content": <string>, "type": <string>}`
3. Processes each job (simulates or performs real printing)
4. Sends acknowledgment: `{"status": "success"|"failed", "error_message": optional}`
5. Automatically reconnects if connection is lost

## Integrating with Real Printers

Modify the `print_job()` method in `printer_client.py` to use actual printer libraries:

```python
# Example: thermal printer with python-escpos
from escpos.printer import Usb
p = Usb(0x04b8, 0x0202)
p.text(content)
p.cut()
p.close()
```

## Troubleshooting

- **"Authentication failed"**: Check printer token matches server config
- **"Connection refused"**: Ensure server is running
- **No jobs processed**: Check server queue with `list_queue` in server console

---

**Status**: Production Ready
