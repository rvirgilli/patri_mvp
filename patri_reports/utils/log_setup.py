import logging
import sys
import os

def setup_logging(log_level_name=None, log_file=None):
    """Configures the root logger based on the LOG_LEVEL environment variable.
    
    Args:
        log_level_name: Override for the log level (default: uses LOG_LEVEL env var)
        log_file: Optional file path to write logs to (in addition to stdout)
    """
    # Get log level from parameter or environment
    if log_level_name is None:
        log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Convert to logging level constant
    log_level = getattr(logging, log_level_name, logging.INFO)
    
    # Configure handlers
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # Add file handler if requested
    if log_file:
        # Ensure the directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    # Configure the root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    
    # Return the root logger for convenience
    return logging.getLogger()

def get_logger(name):
    """Returns a logger configured according to the root settings.
    
    Args:
        name: The name for the logger, typically __name__
        
    Returns:
        A configured logger instance
    """
    # Ensure setup has happened (or call it here if not done on import)
    if not logging.root.handlers:
        setup_logging()
    return logging.getLogger(name) 