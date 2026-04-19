"""
Database abstraction layer for the WebSocket server.

Handles connections to different database backends and provides a unified interface.
"""

import logging
from typing import Any, Dict, Optional
import os
import ssl
import orjson
from pathlib import Path

# Add required imports
import asyncpg  # async PostgreSQL client
import aiosqlite  # async SQLite client
from pydantic import BaseModel, ValidationError

# Database Abstraction Layer
class BaseDB:
    """Abstract base class for database backends."""
    async def get(self, project_id: str, default=None):
        raise NotImplementedError
    
    async def set(self, project_id: str, data: Dict[str, Any]):
        raise NotImplementedError


class JSONDBWrapper(BaseDB):
    """Wrapper for JSONDB to match BaseDB interface."""
    def __init__(self, jsondb: "JSONDB"):
        self.jsondb = jsondb
    
    async def get(self, project_id: str, default=None):
        return await self.jsondb.get(project_id, default)
    
    async def set(self, project_id: str, data: Dict[str, Any]):
        await self.jsondb.set(project_id, data)


class PostgresDB(BaseDB):
    """PostgreSQL database backend."""
    
    def __init__(self, pool):
        self.pool = pool
    
    async def get(self, project_id: str, default=None):
        # Fetch variable data for the given project from PostgreSQL
        query = "SELECT name, value FROM vars WHERE project_id = $1"
        try:
            records = await self.pool.fetch(query, project_id)
            if not records:
                return default
            
            result = {record['name']: record['value'] for record in records}
            logging.info(f"Retrieved data for project {project_id}: {result}")
            return result
        
        except Exception as e:
            logging.error(f"Failed to fetch data from PostgreSQL: {e}")
            return default
    
    async def set(self, project_id: str, data: Dict[str, Any]):
        # Insert or update variable data in PostgreSQL
        query = "INSERT INTO vars (project_id, name, value) VALUES ($1, $2, $3) ON CONFLICT (project_id, name) DO UPDATE SET value = EXCLUDED.value"
        
        try:
            for name, value in data.items():
                await self.pool.execute(query, project_id, name, value)
            
            logging.info(f"Updated data for project {project_id}: {data}")
        
        except Exception as e:
            logging.error(f"Failed to update data in PostgreSQL: {e}")


class SQLiteDB(BaseDB):
    """SQLite database backend."""
    
    def __init__(self, conn):
        self.conn = conn
    
    async def get(self, project_id: str, default=None):
        # Fetch variable data for the given project from SQLite
        query = "SELECT name, value FROM vars WHERE project_id = ?"
        try:
            async with self.conn.execute(query, (project_id,)) as cursor:
                records = await cursor.fetchall()
                if not records:
                    return default
            
            result = {record[0]: record[1] for record in records}
            logging.info(f"Retrieved data for project {project_id}: {result}")
            return result
        
        except Exception as e:
            logging.error(f"Failed to fetch data from SQLite: {e}")
            return default
    
    async def set(self, project_id: str, data: Dict[str, Any]):
        # Insert or update variable data in SQLite
        query = "INSERT INTO vars (project_id, name, value) VALUES (?, ?, ?) ON CONFLICT (project_id, name) DO UPDATE SET value = excluded.value"
        
        try:
            async with self.conn.execute(query, (project_id,) * len(data), *data.values()):
                await self.conn.commit()
            
            logging.info(f"Updated data for project {project_id}: {data}")
        
        except Exception as e:
            logging.error(f"Failed to update data in SQLite: {e}")


async def _POSTGRES_CONNECT(user: str, password: str, database: str, host: str = '127.0.0.1', port: int = 5432):
    """
    Attempt to authenticate with a PostgreSQL database using asyncpg.
    Returns the connection pool if successful, raises an exception if failed.
    """
    try:
        pool = await asyncpg.create_pool(
            user=user,
            password=password,
            database=database,
            host=host,
            port=port,
            min_size=1,
            max_size=10
        )
        # Test the connection
        async with pool.acquire() as conn:
            await conn.execute('SELECT 1') 
        logging.info(f"Successfully authenticated with PostgreSQL")
        return pool
    except Exception as e:
        logging.error(f"Failed to authenticate with PostgreSQL: {e}") 
        raise e


async def _SQLITE_CONNECT(db_path: str = "cloud_vars.db") -> aiosqlite.Connection:
    """
    Authenticate / connect to an SQLite database using aiosqlite.
    Returns an aiosqlite Connection object.
    Raises exceptions on failure.
    """
    try:
        conn = await aiosqlite.connect(db_path)
        # Optional: enable WAL mode for better concurrency
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.commit()
        logging.info(f"Successfully connected to SQLite database at '{db_path}'")
        return conn
    except Exception:
        logging.exception(f"Failed to connect to SQLite database at '{db_path}'")
        raise


async def get_db(user: str, password: str, database: str, host: str = '127.0.0.1', port: int = 5432, dbtype: str = 'json') -> BaseDB:
    """
    Authenticate / connect to a database (user-specified).
    Returns a DB instance implementing BaseDB interface.
    
    Supported DB types: JSON, SQLite, PostgreSQL. (default = JSON)

    Configuration for PostgreSQL: (configure values in the config file)
        POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT
        SQLITE_PATH: path to SQLite database file
        JSON_DB_PATH: path to JSON database file
    """
    
    dbtype = dbtype.lower()
    
    if dbtype in ["json", "postgres", "postgresql"]:
        if dbtype == "postgresql":
            try:
                # Try PostgreSQL
                pool = await _POSTGRES_CONNECT(
                    user=user,
                    password=password,
                    database=database,
                    host=host,
                    port=port
                )
                logging.info("Using PostgreSQL database")
                return PostgresDB(pool)
            except Exception as e:
                logging.error(f"PostgreSQL unavailable: {e}")
                raise RuntimeError("Specified database PostgreSQL not found or not accessible")

        elif dbtype == "sqlite":
            try:
                # Try SQLite
                conn = await _SQLITE_CONNECT(os.getenv('SQLITE_PATH', 'cloud_vars.db'))
                logging.info("Using SQLite database")
                return SQLiteDB(conn)
            except Exception as e:
                logging.error(f"SQLite unavailable: {e}")
                raise RuntimeError("Specified database SQLite not found or not accessible")

        elif dbtype == "json":
            try:
                # Fallback to JSON
                logging.info("Using JSON database (fallback)")
                db = JSONDB(filepath=os.getenv('JSON_DB_PATH', 'cloud_vars.json'))
                await db.load()
                return JSONDBWrapper(db)
            except Exception as e:
                logging.warning(f"JSON unavailable: {e}")
                raise RuntimeError("Specified database JSON not found or not accessible")

    else:
        raise ValueError(f'Invalid database type "{dbtype}"')
