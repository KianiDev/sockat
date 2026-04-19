import os
import configparser

def load_config(path='./sockat.conf'):
    config = configparser.ConfigParser()
    if not os.path.exists(path):
        raise ValueError(f"Config file not found at {path}")
    config.read(path)
    loglevel = config.get('logging', 'logLevel', fallback="INFO").upper()
    dbtype = config.get('database', 'type').lower() == "postgresql"
    if dbtype == "postgresql":
        host = config.get("database", "postgres_host", fallback="127.0.0.1")
        port = config.getint("database", "postgres_port", fallback="5432")
        user = config.get("database", "postgres_user")
        password = config.get("database", "postgres_password")
        database = config.get("database", "postgres_database")
    else:
        host = ""
        port = ""
        user = ""
        password = ""
        database = ""
