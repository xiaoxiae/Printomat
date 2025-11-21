#!/usr/bin/env python3
"""Interactive console for printomat server administration."""

import cmd
import secrets
import os
import json
import asyncio
from typing import Optional, Dict, Any
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

    def __init__(self, config: Config, session_local, connected_services: Dict[str, Any], event_loop=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.SessionLocal = session_local
        self.connected_services = connected_services
        self.event_loop = event_loop

    # Printer Configuration Commands

    def do_get_sleeping_message(self, arg):
        """Get the current printer sleeping message."""
        message = self.config.get_printer_sleeping_message()
        print(f"\nCurrent printer sleeping message:")
        print(f"  {message}")

    def do_set_sleeping_message(self, arg):
        """Set the printer sleeping message.

        Usage: set_sleeping_message <message>
        The message is displayed when the printer is disconnected.
        """
        if not arg:
            print("ERROR: Please provide a message")
            return

        message = arg.strip()
        if not message:
            print("ERROR: Message cannot be empty")
            return

        # Update config
        if "printer" not in self.config._config:
            self.config._config["printer"] = {}

        self.config._config["printer"]["sleeping_message"] = message
        self.config._save()
        print(f"Printer sleeping message updated:")
        print(f"  {message}")

    # Token Management Commands

    def do_add_token(self, arg):
        """Add a new friendship token.

        Interactive: prompts for name and message.
        Token is auto-generated.
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

            # Auto-generate token
            token = secrets.token_hex(4)

            # Add to config via config class
            try:
                self.config.add_friendship_token(name, message, token)
                print("Token added successfully!")
                print(f"   Name: {name}")
                print(f"   Token: {token}")
            except ValueError as e:
                print(f"ERROR: {e}")

        except KeyboardInterrupt:
            print("\nCancelled")

    def do_edit_token(self, arg):
        """Edit an existing friendship token.

        Usage: edit_token <name>
        Allows editing message and token. Changing name creates a new token.
        """
        if not arg:
            print("ERROR: Please specify a name to edit")
            return

        search_name = arg.strip()
        tokens = self.config.get_friendship_tokens()

        # Find the token data by matching the name field
        target_data = None
        for token_data in tokens:
            if token_data.get("name") == search_name:
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

            # If name changed, check if new name already exists
            if name != search_name:
                for existing_token in tokens:
                    if existing_token.get("name") == name:
                        print(f"ERROR: Token with name '{name}' already exists")
                        return

            # Remove old token and add new one
            try:
                self.config.remove_friendship_token(search_name)
                self.config.add_friendship_token(name, message, token)
                print("Token updated successfully!")
                print(f"   Name: {name}")
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

        session = self.SessionLocal()
        try:
            rows = []
            for token_data in sorted(tokens, key=lambda t: t.get("name", "").lower()):
                name = token_data.get("name", "N/A")
                token_val = token_data.get("token", "N/A")
                message = token_data.get("message", "")[:40]

                # Count prints for this token
                print_count = session.query(PrintRequest).filter(
                    PrintRequest.friendship_token_name == name
                ).count()

                rows.append([name, token_val, message, print_count])

            print("\n" + tabulate(rows, headers=["Name", "Token", "Message", "Prints"], tablefmt="grid"))
        finally:
            session.close()

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
        target_data = None
        for token_data in tokens:
            if token_data.get("name") == search_name:
                target_data = token_data
                break

        if not target_data:
            print(f"ERROR: Token not found: {search_name}")
            return

        # Confirm deletion
        confirm = input(f"Remove token '{search_name}'? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Cancelled")
            return

        # Remove from config via config class
        try:
            self.config.remove_friendship_token(search_name)
            print(f"Token removed: {search_name}")
        except ValueError as e:
            print(f"ERROR: {e}")

    # Service Management Commands

    def do_list_services(self, arg):
        """List all connected services."""
        if not self.connected_services:
            print("\nNo services connected.")
            return

        rows = []
        for service_name, websocket in self.connected_services.items():
            # Get client info if available
            client_info = f"{websocket.client}" if websocket.client else "unknown"
            rows.append([service_name, client_info])

        print("\n" + tabulate(rows, headers=["Service Name", "Client"], tablefmt="grid"))

    def do_send_to_service(self, arg):
        """Send a message to a connected service.

        Usage: send_to_service <service_name> <message>
        Example: send_to_service echo "hello world"
        """
        if not arg:
            print("ERROR: Please specify service name and message")
            print("Usage: send_to_service <service_name> <message>")
            return

        # Parse service name and message
        parts = arg.split(None, 1)
        if len(parts) < 2:
            print("ERROR: Please specify both service name and message")
            print("Usage: send_to_service <service_name> <message>")
            return

        service_name = parts[0]
        message = parts[1].strip()

        # Remove surrounding quotes if present
        if message.startswith('"') and message.endswith('"'):
            message = message[1:-1]
        elif message.startswith("'") and message.endswith("'"):
            message = message[1:-1]

        # Check if service is connected
        if service_name not in self.connected_services:
            print(f"ERROR: Service '{service_name}' is not connected")
            print("\nConnected services:")
            if self.connected_services:
                for name in self.connected_services.keys():
                    print(f"  - {name}")
            else:
                print("  (none)")
            return

        # Send message to service
        websocket = self.connected_services[service_name]
        message_data = {"message": message}

        if not self.event_loop:
            print("ERROR: Event loop not available. Cannot send message to service.")
            return

        try:
            # Schedule the coroutine to run in the main event loop
            future = asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps(message_data)),
                self.event_loop
            )
            # Wait for completion with timeout
            future.result(timeout=5.0)
            print(f"Message sent to service '{service_name}': {message}")
        except TimeoutError:
            print(f"ERROR: Timeout while sending message to service '{service_name}'")
        except Exception as e:
            print(f"ERROR: Failed to send message to service '{service_name}': {e}")

    # Print Management Commands

    def do_retry(self, arg):
        """Retry a failed or printed request.

        Usage: retry <request_id>
        Creates a new print request with the same content.
        """
        if not arg:
            print("ERROR: Please specify a request ID to retry")
            return

        try:
            request_id = int(arg.strip())
        except ValueError:
            print("ERROR: Request ID must be a number")
            return

        session = self.SessionLocal()
        try:
            # Find the original request
            original = session.query(PrintRequest).filter(
                PrintRequest.id == request_id
            ).first()

            if not original:
                print(f"ERROR: Request not found: {request_id}")
                return

            print(f"\n--- Retry Request {request_id} ---")
            print(f"Type: {original.type}")
            print(f"Status: {original.status}")
            print(f"Priority: {'Yes' if original.is_priority else 'No'}")
            print(f"Created: {original.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

            # Show preview of content
            if original.message_content:
                preview = original.message_content[:50].replace("\n", " ")
                print(f"Message: {preview}{'...' if len(original.message_content) > 50 else ''}")
            if original.image_content:
                preview = original.image_content[:50] + "..."
                print(f"Image: {preview}")

            # Confirm retry
            confirm = input(f"\nRetry this request? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Cancelled")
                return

            # Create new print request with same content
            try:
                new_request = PrintRequest(
                    type=original.type,
                    message_content=original.message_content,
                    image_content=original.image_content,
                    submitter_ip=original.submitter_ip,
                    source_type=original.source_type,
                    is_priority=original.is_priority,
                    friendship_token_name=original.friendship_token_name,
                    status="queued"
                )

                session.add(new_request)
                session.commit()
                session.refresh(new_request)

                print(f"\nRetry request created successfully!")
                print(f"   New Request ID: {new_request.id}")
                print(f"   Status: queued")
                print(f"   Priority: {'Yes' if new_request.is_priority else 'No'}")

            except Exception as e:
                print(f"ERROR: Failed to create retry request: {e}")

        finally:
            session.close()

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
                source = req.source_type.upper() if req.source_type else "USER"
                created = req.created_at.strftime("%Y-%m-%d %H:%M:%S")
                # Show first 40 chars of message or image indicator
                content = req.message_content or f"[{req.type.upper()}]"
                preview = content[:40].replace("\n", " ")
                # Show token name if present, otherwise IP
                identifier = req.friendship_token_name or req.submitter_ip
                rows.append([idx, req.id, req.type, source, priority, created, identifier, preview])

            print("\n" + tabulate(rows, headers=["Pos", "ID", "Type", "Source", "Priority", "Created", "Name/IP", "Preview"], tablefmt="grid"))

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

            results = query.order_by(PrintRequest.created_at.asc()).limit(limit).all()

            if not results:
                print(f"\nNo requests found")
                return

            rows = []
            for req in results:
                status = req.status
                source = req.source_type.upper() if req.source_type else "USER"
                created = req.created_at.strftime("%Y-%m-%d %H:%M:%S")
                content = req.message_content or f"[{req.type.upper()}]"
                preview = content[:30].replace("\n", " ")
                # Show token name if present, otherwise IP
                identifier = req.friendship_token_name or req.submitter_ip
                rows.append([req.id, status, req.type, source, identifier, created, preview])

            print("\n" + tabulate(rows, headers=["ID", "Status", "Type", "Source", "Name/IP", "Created", "Preview"], tablefmt="grid"))

        finally:
            session.close()

    def do_clear(self, arg):
        """Clear the screen."""
        import os
        os.system('clear' if os.name == 'posix' else 'cls')

    def do_quit(self, arg):
        """Exit the console and shut down the server."""
        print("Shutting down server...")
        os.kill(os.getpid(), 15)  # SIGTERM

    def emptyline(self):
        """Handle empty input - do nothing instead of repeating last command."""
        pass

    def default(self, line):
        """Handle unknown commands."""
        if line.startswith('?'):
            self.onecmd(f'help {line[1:]}')
        else:
            print(f"Unknown command: '{line}'. Type 'help' for available commands.")


def run_console(config: Config, session_local, connected_services: Dict[str, Any], event_loop=None):
    """Run the interactive console."""
    console = PrintomatConsole(config, session_local, connected_services, event_loop)
    try:
        console.cmdloop()
    except KeyboardInterrupt:
        # Gracefully handle Ctrl+C - just exit the console thread
        print("\nConsole interrupted. Exiting...")
    except Exception as e:
        print(f"Error in console: {e}")
