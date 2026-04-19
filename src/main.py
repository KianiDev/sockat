# This is a WebSocket server that handles incoming messages from Scratch cloud variables, validates them using pydantic, persists data to disk using orjson, and sends updates back to the client. It also supports caching and pub/sub using aioredis.
"""
All WebSocket messages are JSON strings; the server may send multiple JSON objects separated by a newline character, but the client may not do that back.

When the client first connects to the server, Scratch sends a "handshake" message, which I think lets the server know which project it is on so the server can then send a series of "set" messages to initialize the client's cloud variables.

// client -> server
{ "method": "handshake", "project_id": "104" }

// server -> client
{ "method": "set", "name": "☁ cool cloud variable", "value": "45643563456" }
{ "method": "set", "name": "☁ epic cloud variable", "value": "10239489031" }
{ "method": "set", "name": "☁ newish variable", "value": "0" }
After that the client can send a "set" message (same structure) to the server, which will broadcast it to the other clients on the project.
"""
import logging
import argparse
import websockets 
import asyncio
from typing import Any, Dict, Optional, Union
import orjson
from pydantic import BaseModel, ValidationError
import os
from cachetools import TTLCache  # Cache for project data with a time-to-live (TTL)
from db import get_db
from config import load_config

class HandshakeMessage(BaseModel):
    """Handshake message from client to server."""
    method: str
    project_id: str


class SetMessage(BaseModel):
    """Variable set message from client to server."""
    method: str
    name: str
    value: Any


class CloudVariableServer:
    """
    WebSocket server for Scratch cloud variables.
    
    Handles handshakes from clients, synchronizes variable state across multiple clients
    in the same project, and persists variables to disk using JSONDB.
    """
    
    def __init__(self, db):
        """
        Initialize the server.
        
        Args:
            db: A database instance implementing BaseDB interface.
        """
        self.db = db
        self.project_connections: Dict[str, set] = {}  # project_id -> set of websocket connections
        self.projects_data: Dict[str, Dict[str, Any]] = {}  # project_id -> {var_name: var_value}
        
        # Initialize cache with TTL of 60 seconds (adjust as needed)
        self.cache = TTLCache(maxsize=1000, ttl=60)  

    async def _get_cached_data(self, project_id: str) -> Dict[str, Any]:
        """
        Retrieve data for a project with caching.
        Returns the cached data if available, otherwise fetches from DB and caches it.
        
        Args:
            project_id: The ID of the project to retrieve data for.
            
        Returns:
            Dictionary containing variable names and values.
        """
        if project_id in self.cache:
            logging.debug(f"Cache hit for project {project_id}")
            return self.cache[project_id]
            
        # If not in cache, get fresh data from DB
        data = await self.db.get(project_id, {})
        
        # Cache the new data
        self.cache[project_id] = data
        
        return data

    async def handle_connection(self, ws: websockets.WebSocketServerProtocol): # type: ignore
        """
        Handle a new WebSocket connection from a client.
        
        Args:
            ws: The WebSocket connection object.
        """
        project_id = None

        try:
            async for raw_message in ws:
                logging.info(f"Received message from client: {raw_message}")
                if not raw_message.strip():  
                    logging.info("Empty message received — ignoring")
                    continue

                try:
                    msg = orjson.loads(raw_message)
                except orjson.JSONDecodeError:
                    logging.debug("Invalid JSON received — ignoring")
                    continue

                method = msg.get("method")

                if method == "handshake":
                    # Client initiates connection and identifies its project
                    try:
                        handshake = HandshakeMessage(**msg)
                        project_id = handshake.project_id
                        logging.info("Got handshake message from client")
                        logging.info(f"Client identified as {project_id}")
                    except ValidationError as e:
                        logging.debug(f"Handshake validation failed: {e}")
                        await ws.close()
                        return

                    logging.info(f"Client joined project {project_id}")

                    # Register this connection for the project
                    self.project_connections.setdefault(project_id, set()).add(ws)

                    # Load persisted data for this project from cache or DB
                    current_vars = await self._get_cached_data(project_id)
                    
                    logging.debug(f"Loaded data (cached: {'yes' if project_id in self.cache else 'no'}) for {project_id}: {current_vars}")

                    # Sync in-memory copy
                    self.projects_data[project_id] = current_vars.copy()

                    # Send initial state — one "set" message per variable
                    for name, value in current_vars.items():
                        await ws.send(orjson.dumps({
                            "method": "set",
                            "name": name,
                            "value": value  
                        }).decode())
                        logging.info(f"Sent initial state for project {project_id}: {name}={value}")

                elif method == "set":
                    # Client sends a variable update
                    if not project_id:
                        logging.debug("set received before handshake — ignoring")
                        continue

                    try:
                        set_msg = SetMessage(**msg)
                        name = set_msg.name
                        value = set_msg.value
                    except ValidationError as e:
                        logging.debug(f"Set message validation failed: {e}")
                        continue

                    value_str = str(value)  

                    # Skip broadcast if value didn't change (optimization)
                    old_value = self.projects_data[project_id].get(name)
                    if old_value == value_str:
                        continue
                    logging.debug(f"Updating project {project_id} variable {name}: {old_value} -> {value}")

                    # Update in-memory state
                    self.projects_data[project_id][name] = value_str

                    # Persist to database and invalidate cache
                    await self.db.set(project_id, self.projects_data[project_id])
                    self._invalidate_cache(project_id)

                    # Broadcast to all clients in this project (including sender)
                    broadcast_msg = orjson.dumps({
                        "method": "set",
                        "name": name,
                        "value": value_str
                    }).decode()
                    logging.info(f"Broadcasting message to project {project_id}: {broadcast_msg}")

                    dead = set()
                    for client in self.project_connections[project_id]:
                        try:
                            await client.send(broadcast_msg)
                        except websockets.ConnectionClosed:
                            dead.add(client)
                        except Exception as exc:
                            logging.debug(f"Failed sending to client: {exc}")
                            dead.add(client)

                    # Clean up dead connections
                    for d in dead:
                        self.project_connections[project_id].discard(d)
                else:
                    logging.debug(f"Unknown method {method!r} — ignoring")

        except websockets.exceptions.ConnectionClosedOK:
            pass
        except Exception as exc:
            logging.exception("Unexpected error in websocket handler")
        finally:
            # Cleanup: unregister client from project and invalidate cache if necessary
            if project_id and project_id in self.project_connections:
                self.project_connections[project_id].discard(ws)
                remaining = len(self.project_connections[project_id])
                logging.debug(f"Client left project {project_id} — {remaining} remaining")
                
                if not self.project_connections[project_id]:
                    # Clean up empty project from memory and cache
                    del self.project_connections[project_id]
                    self.projects_data.pop(project_id, None)
                    self._invalidate_cache(project_id)

    def _invalidate_cache(self, project_id: str) -> None:
        """
        Invalidate the cache entry for a specific project ID.
        
        Args:
            project_id: The ID of the project to invalidate the cache for.
        """
        if project_id in self.cache:
            del self.cache[project_id]
            logging.debug(f"Invalidate cache for project {project_id}")


async def main():
    # Get database arguments from environment variables
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='./sockat.conf')
    args = parser.parse_args()
    
    # Get database arguments from config file

    cfg = load_config(args.config)
    
    # Get database
    database = await get_db(user, password, database, host, port)
    
    # Configuration
    host = os.getenv('WS_HOST', '127.0.0.1')
    port = int(os.getenv('WS_PORT', 8765))
    
    # Create server instance
    server = CloudVariableServer(database)
    
    logging.info(f"Starting WebSocket server on {host}:{port}")
    
    async with websockets.serve(server.handle_connection, host, port):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped by user")
