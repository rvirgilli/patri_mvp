import logging
import asyncio
from typing import Optional, TYPE_CHECKING

from ..utils.error_handler import NetworkError, TimeoutError, DataError

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

async def _safe_update_message(workflow_manager: 'WorkflowManager', user_id: int, message_id: Optional[int], text: str) -> Optional[int]:
    """Safely updates a message by ID or sends a new one if the message ID is invalid.
    
    Args:
        workflow_manager: The WorkflowManager instance
        user_id: The user to send the message to
        message_id: The message ID to edit, or None to send a new message
        text: The text to send
        
    Returns:
        The new message ID if a new message was sent, or the original message_id if edited successfully
    """
    if not workflow_manager.telegram_client:
        logger.error("TelegramClient not set in _safe_update_message")
        return None
        
    if message_id:
        try:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text
            )
            return message_id
        except Exception as e:
            logger.warning(f"Failed to edit message {message_id}: {e}. Sending new message instead.")
            # Fall through to send_message
            
    # Either no message_id provided or edit failed
    try:
        new_message = await workflow_manager.telegram_client.send_message(user_id, text)
        if new_message:
            return new_message.message_id
    except Exception as e:
        logger.error(f"Failed to send message to user {user_id}: {e}")
        
    return None

async def handle_transient_error(workflow_manager: 'WorkflowManager', error: Exception, user_id: int, message_id: Optional[int] = None, max_retries: int = 3, retry_delay: float = 1.0):
    """Handle transient errors with retries.
    
    Args:
        workflow_manager: The WorkflowManager instance
        error: The error that occurred
        user_id: The user's Telegram ID
        message_id: Optional message ID to update
        max_retries: Maximum number of retries
        retry_delay: Delay between retries in seconds
        
    Returns:
        True if the operation should be retried, False otherwise
    """
    if isinstance(error, NetworkError):
        if max_retries > 0:
            error_msg = f"Network error occurred: {str(error)}. Retrying..."
            if message_id:
                await workflow_manager.telegram_client.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=f"⚠️ {error_msg}"
                )
            else:
                await workflow_manager.telegram_client.send_message(user_id, f"⚠️ {error_msg}")
            
            await asyncio.sleep(retry_delay)
            return True
        else:
            error_msg = f"Operation failed after multiple retries: {str(error)}"
            if message_id:
                await workflow_manager.telegram_client.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=f"❌ {error_msg}"
                )
            else:
                await workflow_manager.telegram_client.send_message(user_id, f"❌ {error_msg}")
            return False
    elif isinstance(error, TimeoutError):
        error_msg = "Operation timed out. Please try again."
        if message_id:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"⏱️ {error_msg}"
            )
        else:
            await workflow_manager.telegram_client.send_message(user_id, f"⏱️ {error_msg}")
        return False
    elif isinstance(error, DataError):
        error_msg = f"Data error occurred: {str(error)}"
        if message_id:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"❌ {error_msg}"
            )
        else:
            await workflow_manager.telegram_client.send_message(user_id, f"❌ {error_msg}")
        return False
    else:
        # For unknown errors, log and notify but don't retry
        logger.exception(f"Unexpected error: {error}")
        error_msg = "An unexpected error occurred. Please try again later."
        if message_id:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"❌ {error_msg}"
            )
        else:
            await workflow_manager.telegram_client.send_message(user_id, f"❌ {error_msg}")
        return False 