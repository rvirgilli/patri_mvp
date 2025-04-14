import logging
import os
import sys
import argparse
import asyncio
from datetime import datetime

# Load environment variables first
from dotenv import load_dotenv
load_dotenv() # Load from .env file if it exists

# Setup logging using our custom module
from patri_reports.utils.log_setup import setup_logging
logger = setup_logging()

# Import components
from patri_reports.telegram_client import TelegramClient
from patri_reports.state_manager import StateManager, AppState
from patri_reports.workflow_manager import WorkflowManager
from patri_reports.case_manager import CaseManager
# Import config if needed elsewhere (TelegramClient handles its own needs internally now)
# from utils import config

def check_environment_variables():
    """Check and log critical environment variable status."""
    critical_vars = ["TELEGRAM_BOT_TOKEN"]
    warning_vars = ["ALLOWED_TELEGRAM_USERS", "CASE_DATA_DIR", "STATE_FILE_PATH"]
    
    missing_critical = []
    missing_warning = []
    
    for var in critical_vars:
        if not os.getenv(var):
            missing_critical.append(var)
            
    for var in warning_vars:
        if not os.getenv(var):
            missing_warning.append(var)
    
    # Log results
    if missing_critical:
        logger.critical(f"Missing critical environment variables: {', '.join(missing_critical)}")
        return False
        
    if missing_warning:
        logger.warning(f"Missing recommended environment variables: {', '.join(missing_warning)}")
    
    return True

async def cleanup_old_cases(days: int = 30):
    """Utility function to clean up old completed cases."""
    logger.info(f"Starting cleanup of cases older than {days} days")
    
    try:
        data_dir = os.getenv("CASE_DATA_DIR", "data")
        case_manager = CaseManager(data_dir=data_dir)
        
        # Run the cleanup
        result = case_manager.cleanup_old_cases(max_age_days=days)
        
        logger.info(f"Cleanup completed: {result['processed']} cases processed, {result['removed']} cases removed")
        print(f"Cleanup completed: {result['processed']} cases processed, {result['removed']} cases removed")
        
    except Exception as e:
        logger.exception(f"Error during case cleanup: {e}")
        print(f"Error during cleanup: {e}")

def main():
    """Main entry point for the Patri Reports Assistant."""
    logger.info("Starting Patri Reports Assistant...")
    
    # Check environment variables
    if not check_environment_variables():
        logger.critical("Critical environment variables missing. Exiting.")
        sys.exit(1)

    try:
        # Initialize components
        state_manager = StateManager(state_file=os.getenv("STATE_FILE_PATH", "app_state.json"))
        
        # Initialize the case manager
        data_dir = os.getenv("CASE_DATA_DIR", "data")
        case_manager = CaseManager(data_dir=data_dir)
        
        # Log startup info
        logger.info(f"Using data directory: {data_dir}")
        logger.info(f"Using state file: {state_manager.state_file}")
        
        # Initialize workflow manager with both state_manager and case_manager
        workflow_manager = WorkflowManager(
            state_manager=state_manager,
            case_manager=case_manager
        )
        
        # Pass workflow_manager to TelegramClient
        client = TelegramClient(workflow_manager=workflow_manager)

        # Pass telegram_client back to workflow_manager
        workflow_manager.set_telegram_client(client)

        # Log bot startup info
        current_state = state_manager.get_state()
        active_case = state_manager.get_active_case_id()
        logger.info(f"Bot starting with state: {current_state}, active case: {active_case}")
        
        # Check if there's a possible inconsistent state (EVIDENCE_COLLECTION without case_id)
        if current_state == AppState.EVIDENCE_COLLECTION and not active_case:
            logger.warning("Inconsistent state detected: EVIDENCE_COLLECTION without active case ID. Resetting to IDLE.")
            state_manager.set_state(AppState.IDLE)

        # Start the bot
        client.run()

    except ValueError as e:
        logger.critical(f"Configuration or Initialization Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt.")
    except Exception as e:
        logger.exception("An unexpected error occurred during bot execution.")
        sys.exit(1)
    finally:
        logger.info("Patri Reports Assistant stopped.")

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Patri Reports Assistant")
    
    # Add subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Add 'run' command (default)
    run_parser = subparsers.add_parser("run", help="Run the Telegram bot")
    
    # Add 'cleanup' command
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up old completed cases")
    cleanup_parser.add_argument("--days", type=int, default=30, 
                               help="Remove completed cases older than this many days")
    
    args = parser.parse_args()
    
    # Execute the selected command
    if args.command == "cleanup":
        asyncio.run(cleanup_old_cases(args.days))
    else:
        # Default to running the bot
        main() 