# Patri Reports Telegram Assistant

This application processes case reports and evidence collection via a Telegram bot interface.

## Getting Started

1. Set up your `.env` file with the required API keys and configuration.
2. Run the application with `python -m patri_reports.main`

## Using the Logger

```python
# Method 1: Get pre-configured logger (recommended)
from utils import get_logger
logger = get_logger(__name__)

logger.info("This is an informational message")
logger.warning("This is a warning")
logger.error("This is an error")

# Method 2: Set up logging with custom options
from utils import setup_logging
logger = setup_logging(log_level_name="DEBUG", log_file="app.log")

logger.debug("This message will go to both console and file")
```

## Architecture

The application is structured into several components:

- **workflow_manager.py**: Core orchestration logic
- **telegram_client.py**: Telegram bot interface
- **case_manager.py**: Case data management 
- **state_manager.py**: Application state handling
- **utils/**: Utility functions and helpers
- **api/**: API integrations for external services
- **models/**: Data models and structures 