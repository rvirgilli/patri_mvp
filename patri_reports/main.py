from patri_reports.utils.log_setup import setup_logging
setup_logging()
import logging
logger = logging.getLogger(__name__)
import os
import sys
import argparse
import asyncio
import signal
from datetime import datetime

# Load environment variables first
from dotenv import load_dotenv
load_dotenv() # Load from .env file if it exists

# Import components
from patri_reports.telegram_client import TelegramClient
from patri_reports.state_manager import StateManager, AppState
from patri_reports.workflow_manager import WorkflowManager
from patri_reports.case_manager import CaseManager
# Import config if needed elsewhere (TelegramClient handles its own needs internally now)
# from utils import config

# Global client reference for signal handling
client = None

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

def signal_handler(sig, frame):
    """Handle interrupt signals to gracefully shutdown the application."""
    logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
    global client
    if client:
        logger.info("Cleaning up TelegramClient resources...")
        try:
            client.cleanup()
        except Exception as e:
            logger.error(f"Error during client cleanup: {e}")
    logger.info("Shutdown complete. Exiting.")
    os._exit(0)

def run_bot(args):
    """Run the Telegram bot with the given arguments."""
    global client
    logger.info("Starting Patri Reports Assistant...")
    
    # Check environment variables
    if not check_environment_variables():
        logger.critical("Critical environment variables missing. Exiting.")
        sys.exit(1)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize components
        state_manager = StateManager(state_file=os.getenv("STATE_FILE_PATH", "app_state.json"))
        
        # Reset state if requested
        if getattr(args, "reset_state", False):
            logger.info("Resetting application state to IDLE as requested")
            state_manager.set_state(AppState.IDLE)
        
        # Initialize the case manager
        data_dir = os.getenv("CASE_DATA_DIR", "data")
        case_manager = CaseManager(data_dir=data_dir)
        
        # Log startup info
        logger.info(f"Using data directory: {data_dir}")
        logger.info(f"Using state file: {state_manager.state_file}")
        
        # Initialize workflow manager with both state_manager and case_manager
        workflow_manager = WorkflowManager(
            state_manager=state_manager,
            case_manager=case_manager,
            use_dummy_apis=getattr(args, "no_api", False)
        )
        
        # Pass workflow_manager to TelegramClient
        client = TelegramClient(
            workflow_manager=workflow_manager,
            admin_chat_id=getattr(args, "admin_id", None)
        )

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

        # Evidence collection resume notification
        if current_state == AppState.EVIDENCE_COLLECTION and active_case:
            logger.info(f"System is starting in evidence collection mode for case: {active_case}")
            async def send_resume_notification():
                try:
                    await asyncio.sleep(10)  # Give the bot some time to initialize
                    user_ids = client.allowed_users if client and hasattr(client, 'allowed_users') and client.allowed_users else []
                    for user_id in user_ids:
                        try:
                            await client.send_message(
                                user_id,
                                f"📋 *System Restart Notification*\n\nThe system has been restarted and is continuing evidence collection for case:\n*{active_case}*",
                                parse_mode="Markdown"
                            )
                            try:
                                from patri_reports.workflow.workflow_evidence import send_evidence_prompt
                                await send_evidence_prompt(workflow_manager, user_id, active_case)
                            except ImportError as ie:
                                logger.error(f"Could not import send_evidence_prompt: {ie}")
                            except Exception as e:
                                logger.error(f"Failed to send evidence prompt: {e}")
                        except Exception as user_e:
                            logger.error(f"Failed to send resume notification to user {user_id}: {user_e}")
                except Exception as e:
                    logger.error(f"Failed to send resume notification: {e}")
            loop = asyncio.get_event_loop()
            loop.create_task(send_resume_notification())

        # Start the bot
        client.run()

    except ValueError as e:
        logger.critical(f"Configuration or Initialization Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt.")
        if client:
            try:
                client.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")
        logger.info("Cleanup complete. Exiting.")
    except Exception as e:
        logger.exception("An unexpected error occurred during bot execution.")
        if client:
            try:
                client.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")
        sys.exit(1)
    finally:
        logger.info("Patri Reports Assistant stopped.")

if __name__ == "__main__":
    print("[DEBUG] patri_reports/main.py is running and logging is set up.")
    parser = argparse.ArgumentParser(description="Patri Reports Assistant")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add 'run' command (default)
    run_parser = subparsers.add_parser("run", help="Run the Telegram bot")
    run_parser.add_argument('--admin-id', type=int, help='Telegram admin ID for notifications')
    run_parser.add_argument('--reset-state', action='store_true', help='Reset application state to IDLE before starting')
    run_parser.add_argument('--no-api', action='store_true', help='Use dummy responses instead of real API calls')

    # Add 'cleanup' command
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up old completed cases")
    cleanup_parser.add_argument("--days", type=int, default=30, 
                               help="Remove completed cases older than this many days")

    args = parser.parse_args()

    if args.command == "cleanup":
        asyncio.run(cleanup_old_cases(args.days))
    else:
        # Default to running the bot
        run_bot(args) 