#!/usr/bin/env python3
"""Interactive console for printomat server administration."""

import cmd
import sys
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import tomli_w
from tabulate import tabulate
from config import Config
from models import get_session_local, get_database_engine, PrintRequest


class PrintomatConsole(cmd.Cmd):
    """Interactive console for managing the printer server."""

    intro = """
╔══════════════════════════════════════════════════════════════╗
║         Receipt Printer Server - Administration Console      ║
╚══════════════════════════════════════════════════════════════╝

Type 'help' to see available commands.
Type 'help <command>' for detailed command help.
Type 'quit' to exit.
"""

    prompt = "printomat> "

    def __init__(self, config: Config, session_local, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.SessionLocal = session_local
        self.config_path = Path("config.toml")

    # Token Management Commands

    def do_add_token(self, arg):
        """Add a new friendship token.

        Interactive: prompts for name, label, and message.
        Token is auto-generated.
        """
        print("\n--- Add New Friendship Token ---")

        try:
            name = input("Name: ").strip()
            if not name:
                print("❌ Name cannot be empty")
                return

            label = input("Label (e.g., alice_token): ").strip()
            if not label:
                print("❌ Label cannot be empty")
                return

            message = input("Message (printed with receipt): ").strip()
            if not message:
                print("❌ Message cannot be empty")
                return

            # Check if label already exists
            existing_tokens = self.config.get_friendship_tokens()
            if label in existing_tokens:
                print(f"❌ Token with label '{label}' already exists")
                return

            # Auto-generate token
            token = secrets.token_urlsafe(32)

            # Add to config
            self.config.reload()  # Ensure we have latest config
            config_dict = dict(self.config._config)

            if "friendship_tokens" not in config_dict:
                config_dict["friendship_tokens"] = {}

            config_dict["friendship_tokens"][label] = {
                "name": name,
                "label": label,
                "message": message,
                "token": token
            }

            # Write back to file
            with open(self.config_path, "w") as f:
                f.write(tomli_w.dumps(config_dict))

            self.config.reload()
            print(f"✅ Token added successfully!")
            print(f"   Name: {name}")
            print(f"   Label: {label}")
            print(f"   Token: {token}")

        except KeyboardInterrupt:
            print("\n❌ Cancelled")

    def do_list_tokens(self, arg):
        """List all friendship tokens."""
        tokens = self.config.get_friendship_tokens()

        if not tokens:
            print("\nNo friendship tokens configured.")
            return

        rows = []
        for key, token_data in tokens.items():
            label = token_data.get("label", key)
            name = token_data.get("name", "N/A")
            token_val = token_data.get("token", "N/A")
            # Show first 10 chars of token for security
            token_display = token_val[:10] + "..." if len(token_val) > 10 else token_val
            rows.append([label, name, token_display])

        print("\n" + tabulate(rows, headers=["Label", "Name", "Token"], tablefmt="grid"))

    def do_remove_token(self, arg):
        """Remove a friendship token by label.

        Usage: remove_token <label>
        """
        if not arg:
            print("❌ Please specify a label to remove")
            return

        search_label = arg.strip()
        tokens = self.config.get_friendship_tokens()

        # Find the token key by matching the label field
        target_key = None
        for key, token_data in tokens.items():
            if token_data.get("label") == search_label:
                target_key = key
                break

        if not target_key:
            print(f"❌ Token not found: {search_label}")
            return

        # Confirm deletion
        name = tokens[target_key].get("name", "N/A")
        confirm = input(f"Remove token '{name}' ({search_label})? (y/n): ").strip().lower()
        if confirm != 'y':
            print("❌ Cancelled")
            return

        # Remove from config
        self.config.reload()
        config_dict = dict(self.config._config)

        if "friendship_tokens" in config_dict:
            del config_dict["friendship_tokens"][target_key]

        # Write back to file
        with open(self.config_path, "w") as f:
            f.write(tomli_w.dumps(config_dict))

        self.config.reload()
        print(f"✅ Token removed: {name}")

    # Queue Commands

    def do_list_queue(self, arg):
        """List current print queue."""
        session = self.SessionLocal()
        try:
            # Get all queued messages
            queued = session.query(PrintRequest).filter(
                PrintRequest.status == "queued"
            ).order_by(
                PrintRequest.is_priority.desc(),
                PrintRequest.created_at.asc()
            ).all()

            if not queued:
                print("\nQueue is empty ✓")
                return

            rows = []
            for idx, req in enumerate(queued, 1):
                priority = "YES" if req.is_priority else "NO"
                created = req.created_at.strftime("%Y-%m-%d %H:%M:%S")
                # Show first 40 chars of content
                preview = req.content[:40].replace("\n", " ")
                rows.append([idx, req.id, req.type, priority, created, preview])

            print("\n" + tabulate(rows, headers=["Pos", "ID", "Type", "Priority", "Created", "Preview"], tablefmt="grid"))

        finally:
            session.close()

    # History & Stats Commands

    def do_history(self, arg):
        """View print request history.

        Usage: history [filter]
        Filters: 'printed', 'failed', 'queued', 'printing', or a number (show last N requests)
        """
        session = self.SessionLocal()
        try:
            query = session.query(PrintRequest)

            # Parse filter argument
            limit = 20  # Default limit
            status_filter = None

            if arg:
                arg = arg.strip().lower()
                if arg in ["printed", "failed", "queued", "printing"]:
                    status_filter = arg
                elif arg.isdigit():
                    limit = int(arg)
                else:
                    print(f"❌ Unknown filter: {arg}")
                    return

            # Apply filters
            if status_filter:
                query = query.filter(PrintRequest.status == status_filter)

            results = query.order_by(PrintRequest.created_at.desc()).limit(limit).all()

            if not results:
                print(f"\nNo requests found")
                return

            rows = []
            for req in results:
                status = req.status
                # Add emoji for status
                if status == "printed":
                    status = "✅ printed"
                elif status == "failed":
                    status = "❌ failed"
                elif status == "queued":
                    status = "⏳ queued"
                elif status == "printing":
                    status = "🖨️  printing"

                created = req.created_at.strftime("%Y-%m-%d %H:%M:%S")
                preview = req.content[:30].replace("\n", " ")
                rows.append([req.id, status, req.type, req.submitter_ip, created, preview])

            print("\n" + tabulate(rows, headers=["ID", "Status", "Type", "IP", "Created", "Preview"], tablefmt="grid"))

        finally:
            session.close()

    def do_clear(self, arg):
        """Clear the screen."""
        import os
        os.system('clear' if os.name == 'posix' else 'cls')

    def do_quit(self, arg):
        """Exit the console."""
        print("\nGoodbye!")
        return True

    def emptyline(self):
        """Handle empty input - do nothing instead of repeating last command."""
        pass

    def default(self, line):
        """Handle unknown commands."""
        if line.startswith('?'):
            self.onecmd(f'help {line[1:]}')
        else:
            print(f"Unknown command: '{line}'. Type 'help' for available commands.")


def run_console(config: Config, session_local):
    """Run the interactive console."""
    console = PrintomatConsole(config, session_local)
    console.cmdloop()
