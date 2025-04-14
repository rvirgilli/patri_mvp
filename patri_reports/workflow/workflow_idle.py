import logging
from typing import TYPE_CHECKING

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..state_manager import AppState

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

async def show_idle_menu(workflow_manager: 'WorkflowManager', user_id: int):
    """Sends the main menu message and button for the IDLE state."""
    if not workflow_manager.telegram_client:
         logger.error("Cannot show IDLE menu, TelegramClient not set.")
         return
    
    welcome_text = "Welcome to Patri Reports Assistant"  # Changed to be different from button text
    buttons = [[InlineKeyboardButton("➕ Start New Case", callback_data="start_new_case")]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await workflow_manager.telegram_client.send_message(user_id, welcome_text, reply_markup=reply_markup)

async def handle_idle_state(workflow_manager: 'WorkflowManager', update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Handles updates when the application is in the IDLE state."""
    logger.debug(f"Handling IDLE state for user {user_id}")
    query = update.callback_query
    message = update.message

    if query:
        await query.answer() # Acknowledge button press
        if query.data == "start_new_case":
            logger.info(f"User {user_id} clicked 'Start New Case' button.")
            
            # Send admin notification
            user_name = update.effective_user.username or f"ID: {user_id}"
            await workflow_manager.telegram_client.send_admin_notification(
                f"🔔 *New Case Started*\nUser: @{user_name}\nTime: {workflow_manager.get_formatted_timestamp()}",
                parse_mode="Markdown"
            )
            
            from .workflow_pdf import start_new_case_workflow
            await start_new_case_workflow(workflow_manager, user_id, query.message.message_id)
        else:
            logger.warning(f"Received unexpected callback data in IDLE state: {query.data}")
            await workflow_manager.telegram_client.send_message(user_id, "Invalid action.")

    elif message and message.text == "/start":
        logger.info(f"User {user_id} used /start command.")
        # Existing case check from MVP doc (Step 2)
        active_case_id = workflow_manager.state_manager.get_active_case_id() # Need this method
        if active_case_id:
             # Transition should happen based on loaded state, not here
             # This logic belongs in the initial state loading/check phase
             logger.warning(f"/start received but active case {active_case_id} exists (should have resumed?). Showing IDLE menu.")
             await show_idle_menu(workflow_manager, user_id)
        else:
             await show_idle_menu(workflow_manager, user_id)
             
    elif message and message.text == "/help":
        logger.info(f"User {user_id} used /help command.")
        help_text = (
            "🤖 *Patri Reports Assistant Help*\n\n"
            "*Available Commands:*\n"
            "- /start - Initialize or restart the bot\n"
            "- /help - Show this help message\n\n"
            "*How to use:*\n"
            "1. Click '➕ Start New Case' to begin a new case\n"
            "2. Upload a PDF of the occurrence report\n"
            "3. Follow the prompts to collect evidence for the case\n"
            "4. When finished, select 'Complete Evidence Collection'\n\n"
            "If you need further assistance, please contact support."
        )
        await workflow_manager.telegram_client.send_message(
            user_id, 
            help_text, 
            parse_mode="Markdown"
        )
        # Show the menu after help
        await show_idle_menu(workflow_manager, user_id)

    elif message:
        # Ignore other text messages in IDLE state, maybe provide help
        logger.debug(f"Received unexpected message from user {user_id} in IDLE state: {message.text[:50]}...")
        await workflow_manager.telegram_client.send_message(user_id, "Use the button to start a new case, or /help.")
        # Show the menu after a generic message
        await show_idle_menu(workflow_manager, user_id) 