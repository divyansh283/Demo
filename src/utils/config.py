import configparser
from pathlib import Path
from src.utils.constants import CONFIG_FILE

def load_config(config_path: str = CONFIG_FILE) -> configparser.ConfigParser:
    if not Path(config_path).exists():
        raise FileNotFoundError(
            f"Configuration file '{config_path}' not found. "
            "Place config.ini next to the executable and restart."
        )
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    return cfg
