# sockat
WebSocket server for Scratch cloud variables, focused on ease of use and security.

## Features

- Supports multiple database backends (PostgreSQL, SQLite)
- JSON file fallback for development
- TLS/SSL support for secure connections
- AsyncIO with uvloop integration for better performance
- Pydantic validation for WebSocket messages
- Automatic data persistence using orjson
- Pub/Sub style broadcasting between clients in the same project

## Prerequisites

Before running, ensure you have:

1. Python 3.7+ installed
2. PostgreSQL (optional but recommended) with asyncpg driver
OR
SQLite3 installed
OR
Python development environment with write permissions

## Installation

```bash
git clone https://github.com/yourusername/sockat.git
cd sockat
pip install -r requirements.txt
```

## Quick Start

### Running the Server

1. Create a configuration file (optional):
```python
export POSTGRES_USER="your_db_user"
export POSTGRES_PASSWORD="your_db_password"
export POSTGRES_DB="sockat Database"
export POSTGRES_HOST="localhost"  # or IP address of your PostgreSQL server
```

OR for SQLite:

```bash
touch sockat.db
```

2. Start the server:
```bash
python src/main.py
```

### Configuration Options

The following environment variables can be set to configure the server:

| Variable Name           | Default Value        | Description |
|-------------------------|---------------------|-------------|
| WS_HOST                 | "127.0.0.1"          | Host address to bind |
| WS_PORT                | 8765                | Port number for WebSocket connections |
| POSTGRES_USER          | "postgres"          | PostgreSQL username |
| POSTGRES_PASSWORD      | "password"          | PostgreSQL password |
| POSTGRES_DB            | "sockat"            | PostgreSQL database name |
| POSTGRES_HOST          | "127.0.0.1"         | PostgreSQL server address |
| POSTGRES_PORT          | 5432                | PostgreSQL port number |

## Security Note

- Never expose this server to the public internet without proper security measures
- Always use HTTPS with a valid certificate when exposing to the internet
- Regularly backup your database
- Keep dependencies updated

## Project Structure

The repository contains:

```
src/
  main.py              # Main WebSocket server implementation
  db/                  # Database related code
    base_db.py         # Abstract database layer
    postgres_db.py     # PostgreSQL implementation
    sqlite_db.py       # SQLite implementation
    json_db.py         # JSON file fallback
  models.py            # Pydantic models for message validation
  server.py            # WebSocket server class

tests/
  # Integration tests and other test files

README.md               # This documentation file
LICENSE                 # MIT License
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit changes
4. Push to the branch
5. Create a Pull Request

Please ensure your contributions follow PEP8 style guidelines.

## License

MIT License
```