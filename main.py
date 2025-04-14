import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
import time # Import time module
import signal
import argparse  # Import for command line args

# Adjust path to import from patri_reports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Removed unused import: from patri_reports.utils.config import check_environment_variables
from patri_reports.utils.log_setup import setup_logging
from patri_reports.state_manager import StateManager, AppState
from patri_reports.case_manager import CaseManager
from patri_reports.workflow_manager import WorkflowManager
from patri_reports.telegram_client import TelegramClient

# Global client reference for cleanup
client = None

def signal_handler(sig, frame):
    """Handle interrupt signals to gracefully shutdown the application."""
    logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
    if client:
        logger.info("Cleaning up TelegramClient resources...")
        client.cleanup()
    logger.info("Shutdown complete. Exiting.")
    # Force exit to ensure all processes terminate
    os._exit(0)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Patri Reports Telegram Assistant')
    parser.add_argument('--admin-id', type=int, help='Telegram admin ID for notifications')
    parser.add_argument('--reset-state', action='store_true', help='Reset application state to IDLE before starting')
    parser.add_argument('--no-api', action='store_true', help='Use dummy responses instead of real API calls')
    return parser.parse_args()

def main():
    """Main entry point for the Patri Reports Assistant."""
    global client
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting Patri Reports Assistant...")
    
    # Environment variables are checked implicitly when config is imported by other modules
    # Removed call: if not check_environment_variables(): ...

    try:
        # Initialize components
        state_manager = StateManager(state_file=os.getenv("STATE_FILE_PATH", "app_state.json"))
        
        # Reset state if requested
        if args.reset_state:
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
            use_dummy_apis=args.no_api
        )
        
        # Pass workflow_manager to TelegramClient
        client = TelegramClient(
            workflow_manager=workflow_manager,
            admin_chat_id=args.admin_id  # Pass admin_id directly to constructor
        )
        
        # Pass telegram_client back to workflow_manager
        workflow_manager.set_telegram_client(client)

        # Print current state and active case
        logger.info(f"Bot starting with state: {state_manager.get_state()}, active case: {state_manager.get_active_case_id()}")

        # Add startup message for evidence collection mode
        if state_manager.get_state() == AppState.EVIDENCE_COLLECTION and state_manager.get_active_case_id():
            active_case_id = state_manager.get_active_case_id()
            logger.info(f"System is starting in evidence collection mode for case: {active_case_id}")
            
            # Schedule a task to send a specific message about resuming the case
            async def send_resume_notification():
                try:
                    await asyncio.sleep(10)  # Give the bot some time to initialize
                    user_ids = client.allowed_users if client and client.allowed_users else []
                    for user_id in user_ids:
                        try:
                            # Send the resumption notification
                            await client.send_message(
                                user_id, 
                                f"📋 *System Restart Notification*\n\nThe system has been restarted and is continuing evidence collection for case:\n*{active_case_id}*",
                                parse_mode="Markdown"
                            )
                            
                            # Show the evidence collection prompt
                            try:
                                from patri_reports.workflow.workflow_evidence import send_evidence_prompt
                                await send_evidence_prompt(workflow_manager, user_id, active_case_id)
                            except ImportError as ie:
                                logger.error(f"Could not import send_evidence_prompt: {ie}")
                            except Exception as e:
                                logger.error(f"Failed to send evidence prompt: {e}")
                                
                        except Exception as user_e:
                            logger.error(f"Failed to send resume notification to user {user_id}: {user_e}")
                except Exception as e:
                    logger.error(f"Failed to send resume notification: {e}")
            
            # Create and start the notification task
            loop = asyncio.get_event_loop()
            loop.create_task(send_resume_notification())

        # Start the bot
        client.run()

        # Startup notification is now moved to run() method in TelegramClient

    except ValueError as e:
        # This will catch ValueErrors raised from config.py if env vars are missing
        logger.critical(f"Configuration or Initialization Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down gracefully...")
        if client:
            client.cleanup()
        logger.info("Cleanup complete. Exiting.")
    except Exception as e:
        logger.critical(f"An unexpected error occurred during startup: {e}", exc_info=True)
        if client:
            try:
                client.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")
        sys.exit(1)

if __name__ == "__main__":
    # Load environment variables from .env file
    load_dotenv()

    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    main() 