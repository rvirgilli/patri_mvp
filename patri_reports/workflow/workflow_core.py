import logging
import os
import random
import time
from datetime import datetime
from typing import Optional

from telegram import Update, User
from telegram.ext import ContextTypes

from ..state_manager import StateManager, AppState
from ..api.whisper import WhisperAPI
from ..api.llm import LLMAPI
from ..api.anthropic import AnthropicAPI
from ..utils.error_handler import NetworkError, TimeoutError, DataError

logger = logging.getLogger(__name__)

class WorkflowManager:
    """
    Orchestrates the application flow based on user interactions and state.
    This is the core class that delegates to specialized handlers.
    """

    def __init__(
        self,
        state_manager: 'StateManager',
        case_manager: 'CaseManager',
        use_dummy_apis: bool = False,
        # telegram_client will be set later to avoid circular import
    ):
        """
        Initializes the WorkflowManager.

        Args:
            state_manager: An instance of the StateManager.
            case_manager: An instance of the CaseManager.
            use_dummy_apis: If True, API clients will return dummy responses
                           instead of calling real APIs (for testing).
        """
        self.state_manager = state_manager
        self.case_manager = case_manager
        self.telegram_client: Optional['TelegramClient'] = None # Type hint
        self.use_dummy_apis = use_dummy_apis
        
        if use_dummy_apis:
            logger.info("Using dummy API responses (--no-api flag enabled)")
        
        # Initialize external APIs
        self.whisper_api = WhisperAPI(use_dummy_responses=use_dummy_apis)
        
        # Set up LLM providers based on available API keys
        self.llm_api = LLMAPI(use_dummy_responses=use_dummy_apis)
        self.anthropic_api = AnthropicAPI(use_dummy_responses=use_dummy_apis)
        
        # Determine the primary LLM provider based on available API keys and config
        self.use_anthropic = os.environ.get("USE_ANTHROPIC", "false").lower() == "true"
        
        # If USE_ANTHROPIC is set to true but no key is available, log a warning
        if self.use_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
            logger.warning("USE_ANTHROPIC is true but ANTHROPIC_API_KEY is not set. Falling back to OpenAI.")
            self.use_anthropic = False
            
        logger.info(f"LLM Provider: {'Anthropic Claude' if self.use_anthropic else 'OpenAI'}")
        
        # Track pinned message IDs
        self.pinned_message_ids = {}
        
        # Track photo batches for batch fingerprint classification
        self.photo_batches = {}  # Maps batch_id -> count of photos
        self.last_photo_time = {}  # Maps user_id -> timestamp of last photo
        self.photo_batch_evidence_ids = {}  # Maps batch_id -> list of evidence IDs
        
        logger.info("WorkflowManager initialized (awaiting TelegramClient).")

    def set_telegram_client(self, telegram_client: 'TelegramClient'):
        """Sets the TelegramClient instance after initialization."""
        self.telegram_client = telegram_client
        
        # Set allowed users from telegram client
        self.allowed_users = telegram_client.allowed_users if hasattr(telegram_client, 'allowed_users') else []
        logger.info(f"TelegramClient set for WorkflowManager. Allowed users: {self.allowed_users}")

    def _generate_case_id(self) -> str:
        """
        Generate a temporary case ID to be replaced once PDF data is extracted.
        This is only used as a placeholder before we have real case data.
        
        Returns:
            A string with a temporary ID format
        """
        # Use timestamp for unique temporary ID
        timestamp = int(time.time())
        return f"TEMP_{timestamp}"

    async def handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Main entry point for processing incoming Telegram updates.
        Determines the appropriate action based on the current state and update type.
        This method will be called by TelegramClient handlers.
        """
        if not self.telegram_client:
            logger.error("WorkflowManager.handle_update called before TelegramClient was set.")
            return

        # Extract user_id consistently
        user = update.effective_user
        if not user:
            logger.warning("Received update without user information.")
            return
        user_id = user.id

        # Get current state and active case ID
        current_app_state = self.state_manager.get_state()
        active_case_id = self.state_manager.get_active_case_id() # Get case_id regardless of state
        logger.debug(f"Handling update for user {user_id} in state: {current_app_state} (Case: {active_case_id})")

        try:
            # Using conditional imports to avoid circular references
            if current_app_state == AppState.IDLE:
                from .workflow_idle import handle_idle_state
                await handle_idle_state(self, update, context, user_id)
            elif current_app_state == AppState.WAITING_FOR_PDF:
                from .workflow_pdf import handle_waiting_for_pdf_state
                await handle_waiting_for_pdf_state(self, update, context, user_id)
            elif current_app_state == AppState.EVIDENCE_COLLECTION:
                if active_case_id:
                    from .workflow_evidence import handle_evidence_collection_state
                    await handle_evidence_collection_state(self, update, context, user_id, active_case_id)
                else:
                    logger.error(f"In EVIDENCE_COLLECTION state but no active_case_id found for user {user_id}. Resetting to IDLE.")
                    self.state_manager.set_state(AppState.IDLE) # Automatically clears case_id
                    await self.telegram_client.send_message(user_id, "Error: Lost active case context. Returning to main menu.")
                    from .workflow_idle import show_idle_menu
                    await show_idle_menu(self, user_id)
            elif current_app_state == AppState.REPORT_GENERATION:
                if active_case_id:
                    from .workflow_llm import handle_report_generation_state
                    await handle_report_generation_state(self, update, context, user_id, active_case_id)
                else:
                    logger.error(f"In REPORT_GENERATION state but no active_case_id found for user {user_id}. Resetting to IDLE.")
                    self.state_manager.set_state(AppState.IDLE)
                    await self.telegram_client.send_message(user_id, "Error: Lost active case context. Returning to main menu.")
                    from .workflow_idle import show_idle_menu
                    await show_idle_menu(self, user_id)
            else:
                logger.warning(f"Unhandled state: {current_app_state} for user {user_id}")
                # Optionally send a generic error message

        except Exception as e:
            logger.exception(f"Error handling update for user {user_id} in state {current_app_state}: {e}")
            # Attempt to notify user and recover
            await self.handle_error(update, str(e), recover=True)

    async def handle_error(self, update: Update, error_message: str, recover: bool = False):
        """
        Handles errors that occur during update processing and attempts recovery.
        
        Args:
            update: The Telegram update that triggered the error
            error_message: Description of the error that occurred
            recover: Whether to attempt state recovery
        """
        if not update.effective_user:
            logger.error("Cannot handle error: No user in update")
            return
        
        user_id = update.effective_user.id
        
        # First log the error with context
        current_state = self.state_manager.get_state()
        active_case_id = self.state_manager.get_active_case_id()
        logger.error(f"Error for user {user_id} in state {current_state} (Case: {active_case_id}): {error_message}")
        
        # Attempt to notify user with an appropriate message
        try:
            user_message = self._get_friendly_error_message(error_message)
            await self.telegram_client.send_message(
                user_id, 
                user_message
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {user_id}: {e}")
        
        # Attempt state recovery if requested
        if recover:
            try:
                # Check if we're in a potentially inconsistent state
                if current_state == AppState.WAITING_FOR_PDF:
                    # Simple reset to IDLE for waiting state
                    logger.info(f"Recovering from error in WAITING_FOR_PDF state for user {user_id}")
                    if self.state_manager.set_state(AppState.IDLE):
                        await self.telegram_client.send_message(
                            user_id,
                            "Returning to main menu due to an error."
                        )
                        from .workflow_idle import show_idle_menu
                        await show_idle_menu(self, user_id)
                
                elif current_state == AppState.EVIDENCE_COLLECTION and active_case_id:
                    # For evidence collection, we check if the case exists and is valid
                    logger.info(f"Attempting to recover case {active_case_id} after error for user {user_id}")
                    
                    # Check if case exists and is loaded properly
                    case_info = self.case_manager.load_case(active_case_id)
                    if not case_info:
                        logger.warning(f"Case {active_case_id} no longer valid during recovery. Resetting to IDLE.")
                        if self.state_manager.set_state(AppState.IDLE):
                            await self.telegram_client.send_message(
                                user_id,
                                "Case information is no longer available. Returning to main menu."
                            )
                            from .workflow_idle import show_idle_menu
                            await show_idle_menu(self, user_id)
                    else:
                        # Case is still valid, try to resend evidence prompt
                        logger.info(f"Case {active_case_id} still valid. Attempting to resume evidence collection.")
                        try:
                            from .workflow_evidence import send_evidence_prompt
                            await send_evidence_prompt(self, user_id, active_case_id)
                        except Exception as e:
                            logger.error(f"Failed to resume evidence collection for case {active_case_id}: {e}")
                            # Last resort - reset to IDLE
                            if self.state_manager.set_state(AppState.IDLE):
                                await self.telegram_client.send_message(
                                    user_id,
                                    "Unable to resume your case. Returning to main menu."
                                )
                                from .workflow_idle import show_idle_menu
                                await show_idle_menu(self, user_id)
                
            except Exception as recovery_error:
                logger.exception(f"Error during state recovery for user {user_id}: {recovery_error}")
                # If recovery also fails, reset to IDLE state as last resort
                try:
                    if self.state_manager.set_state(AppState.IDLE):
                        await self.telegram_client.send_message(
                            user_id,
                            "Unable to recover from error. Returning to main menu."
                        )
                        from .workflow_idle import show_idle_menu
                        await show_idle_menu(self, user_id)
                except Exception:
                    # At this point, we can't do much more
                    logger.critical(f"Critical failure: Unable to reset state for user {user_id} after error")

    def _get_friendly_error_message(self, error_message: str) -> str:
        """
        Convert technical error message to user-friendly version.
        
        Args:
            error_message: The original error message
            
        Returns:
            A more friendly message suitable for end users
        """
        if "NetworkError" in error_message or "TimeoutError" in error_message:
            return "❌ Network connection issue. Please check your connection and try again."
        elif "Permission" in error_message:
            return "❌ File permission error. Bot doesn't have access to necessary files."
        elif "PDF" in error_message and any(x in error_message for x in ["corrupt", "invalid", "read"]):
            return "❌ The PDF file appears to be invalid or corrupted. Please upload a different file."
        else:
            return "❌ An error occurred. Our team has been notified."
    
    async def handle_current_state(self, user_id: int):
        """
        Create a minimal update object and process it based on the current state.
        This is used when transitioning states programmatically rather than from a user action.
        
        Args:
            user_id: The Telegram user ID to handle the current state for
        """
        from telegram import Update, User
        import asyncio
        
        # Create a minimal Update object with just enough information
        dummy_user = User(id=user_id, is_bot=False, first_name="User")
        dummy_update = Update(update_id=0)
        dummy_update._effective_user = dummy_user
        
        # Create a minimal context
        class DummyContext:
            def __init__(self):
                self.args = []
                self.bot_data = {}
                self.chat_data = {}
                self.user_data = {}
        
        dummy_context = DummyContext()
        
        # Process the current state
        logger.info(f"Handling current state for user {user_id} via handle_current_state")
        await self.handle_update(dummy_update, dummy_context)
        
    def get_formatted_timestamp(self) -> str:
        """Get a formatted timestamp string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S") 