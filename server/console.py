#!/usr/bin/env python3
"""Interactive console for printomat server administration."""

import cmd
import secrets
from typing import Optional
from tabulate import tabulate
from .config import Config
from .models import PrintRequest


class PrintomatConsole(cmd.Cmd):
    """Interactive console for managing the printer server."""

    intro = """
Receipt Printer Server - Administration Console

Type 'help' to see available commands.
Type 'help <command>' for detailed command help.
Type 'quit' to exit.
"""

    prompt = "printomat> "

    def __init__(self, config: Config, session_local, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.SessionLocal = session_local

    # Token Management Commands

    def do_add_token(self, arg):
        """Add a new friendship token.

        Interactive: prompts for name and message.
        Label and token are auto-generated from name.
        """
        print("\n--- Add New Friendship Token ---")

        try:
            name = input("Name: ").strip()
            if not name:
                print("ERROR: Name cannot be empty")
                return

            message = input("Message: ").strip()
            if not message:
                print("ERROR: Message cannot be empty")
                return

            # Auto-generate token and label
            token = secrets.token_hex(4)
            label = self.config.generate_label_from_name(name)

            # Add to config via config class
            try:
                self.config.add_friendship_token(name, message, token)
                print("Token added successfully!")
                print(f"   Name: {name}")
                print(f"   Label (auto-generated): {label}")
                print(f"   Token: {token}")
            except ValueError as e:
                print(f"ERROR: {e}")

        except KeyboardInterrupt:
            print("\nCancelled")

    def do_edit_token(self, arg):
        """Edit an existing friendship token.

        Usage: edit_token <name>
        Allows editing message and token. Name change will update the label.
        """
        if not arg:
            print("ERROR: Please specify a name to edit")
            return

        search_name = arg.strip()
        tokens = self.config.get_friendship_tokens()

        # Find the token data by matching the name field
        target_label = None
        target_data = None
        for token_data in tokens:
            if token_data.get("name") == search_name:
                target_label = token_data.get("label")
                target_data = token_data
                break

        if not target_data:
            print(f"ERROR: Token not found: {search_name}")
            return

        print(f"\n--- Edit Friendship Token: {search_name} ---")

        try:
            # Pre-fill with existing values
            name = input(f"Name [{target_data.get('name')}]: ").strip() or target_data.get('name')
            message = input(f"Message [{target_data.get('message')}]: ").strip() or target_data.get('message')

            if not name or not message:
                print("ERROR: Fields cannot be empty")
                return

            # Keep existing token or generate new one
            keep_token = input(f"Keep existing token [{target_data.get('token')}]? (y/n): ").strip().lower()
            if keep_token == 'y' or keep_token == '':
                token = target_data.get('token')
            else:
                token = secrets.token_hex(4)

            # Generate new label from updated name
            new_label = self.config.generate_label_from_name(name)

            # If name changed, label will be different
            if new_label != target_label:
                # Check if new label already exists
                for existing_token in tokens:
                    if existing_token.get("label") == new_label and existing_token.get("label") != target_label:
                        print(f"ERROR: Token with name '{name}' (label: {new_label}) already exists")
                        return

            # Remove old token and add new one
            try:
                self.config.remove_friendship_token(target_label)
                self.config.add_friendship_token(name, message, token)
                print("Token updated successfully!")
                print(f"   Name: {name}")
                print(f"   Label (auto-generated): {new_label}")
                print(f"   Token: {token}")
            except ValueError as e:
                print(f"ERROR: {e}")

        except KeyboardInterrupt:
            print("\nCancelled")

    def do_list_tokens(self, arg):
        """List all friendship tokens."""
        tokens = self.config.get_friendship_tokens()

        if not tokens:
            print("\nNo friendship tokens configured.")
            return

        rows = []
        for token_data in tokens:
            name = token_data.get("name", "N/A")
            label = token_data.get("label", "N/A")
            token_val = token_data.get("token", "N/A")
            message = token_data.get("message", "")[:40]
            rows.append([name, label, token_val[:8], message])

        print("\n" + tabulate(rows, headers=["Name", "Label (auto-generated)", "Token", "Message"], tablefmt="grid"))

    def do_remove_token(self, arg):
        """Remove a friendship token by name.

        Usage: remove_token <name>
        """
        if not arg:
            print("ERROR: Please specify a name to remove")
            return

        search_name = arg.strip()
        tokens = self.config.get_friendship_tokens()

        # Find the token data by matching the name field
        target_label = None
        target_name = None
        for token_data in tokens:
            if token_data.get("name") == search_name:
                target_label = token_data.get("label")
                target_name = token_data.get("name", "N/A")
                break

        if not target_label:
            print(f"ERROR: Token not found: {search_name}")
            return

        # Confirm deletion
        confirm = input(f"Remove token '{target_name}' ({target_label})? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Cancelled")
            return

        # Remove from config via config class
        try:
            self.config.remove_friendship_token(target_label)
            print(f"Token removed: {target_name}")
        except ValueError as e:
            print(f"ERROR: {e}")

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
                print("\nQueue is empty")
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
