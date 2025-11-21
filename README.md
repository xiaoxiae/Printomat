# Printomat

[Send me a message that will get printed on my home receipt printer.](https://slama.dev/printomat/) No, I'm not kidding.

| Printing images | with text | and some bugs |
|---|---|---|
| ![Printer showcase 1](assets/printer-1.webp) | ![Printer showcase 2](assets/printer-2.webp) | ![Printer showcase 3](assets/printer-3.webp) |

## What is this?

Printomat lets you submit text and images to get printed on a receipt printer sitting at my desk.

Yes, I'm aware that FAX exists, but this is more fun.

## Why is this?

N/A

## Overview

- [`server`](server/): collects and manages incoming messages and images
  - uses [FastAPI](https://github.com/fastapi/fastapi)
  - implements IP-based timeouts so the printer doesn't die
  - supports **friendship tokens**, which can be given to users to skip time-outs
  - communicates with the printer and services via websockets
- [`client`](client/): connects to the server and prints things
  - handles the printing via [Python-ESC/POS](https://github.com/python-escpos/python-escpos)
  - prints images created via [Pillow](https://pillow.readthedocs.io/en/latest/)
- [`services`](services/): custom scripts to print custom things
  - [`services/echo_service.py`](services/echo_service.py) -- echo messages from server
  - [`services/weather_service.py`](services/weather_service.py) -- periodically prints daily forecast

To run, use

```
cp server/config.example.toml server/config.toml
uv run python -m server
```

and

```
cp client/config.example.toml client/config.toml
uv run python -m client
```
