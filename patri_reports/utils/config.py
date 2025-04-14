import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def clean_env_value(value, default=None):
    """
    Cleans an environment variable value by removing comments and extra whitespace.
    
    Args:
        value: The environment variable value to clean
        default: Default value to return if value is None
        
    Returns:
        Cleaned value with comments removed and whitespace trimmed
    """
    if value is None:
        return default
    
    # Remove comments (everything after #) and trim whitespace
    if '#' in value:
        value = value.split('#')[0]
    return value.strip()

# Required variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_TELEGRAM_USERS_STR = os.getenv("ALLOWED_TELEGRAM_USERS")

# Optional variables with defaults
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CASE_ID_PREFIX = clean_env_value(os.getenv("CASE_ID_PREFIX"), "SEPPATRI")

# Type conversions and validation
ALLOWED_TELEGRAM_USERS = []
if ALLOWED_TELEGRAM_USERS_STR:
    try:
        ALLOWED_TELEGRAM_USERS = [int(user_id.strip()) for user_id in ALLOWED_TELEGRAM_USERS_STR.split(',')]
    except ValueError:
        print("Error: ALLOWED_TELEGRAM_USERS contains non-integer values.")
        # Optionally raise an error or exit
        # raise ValueError("Invalid user ID found in ALLOWED_TELEGRAM_USERS")

# Check for missing required variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
if not ALLOWED_TELEGRAM_USERS:
    # This covers both missing variable and empty list after parsing
    raise ValueError("Missing or invalid required environment variable: ALLOWED_TELEGRAM_USERS") 