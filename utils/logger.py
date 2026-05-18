import logging
import sys
from pathlib import Path
import yaml

def load_config(config_path: str = "config/config.yaml") -> dict:
    """Load configuration from a YAML file."""
    path = Path(config_path)
    if not path.exists():
        return {}
    
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def setup_logger(name: str) -> logging.Logger:
    """
    Setup and return a logger with configuration from config.yaml.
    """
    config = load_config()
    log_config = config.get("logging", {})
    
    level_str = log_config.get("level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    
    log_format = log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(console_handler)
        
        # File handler
        log_file = log_config.get("file")
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(log_format))
            logger.addHandler(file_handler)
            
    return logger
