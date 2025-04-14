import logging
import asyncio
from typing import Dict, Set, Optional, Callable, Awaitable, Any, Tuple, TYPE_CHECKING

import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from ..models.case import CaseInfo
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

# Shared state for tracking media groups
ongoing_media_groups = {}  # media_group_id -> list of message_ids
media_group_summaries_sent = set()  # set of media_group_ids for which summaries were sent
media_group_timers = {}  # media_group_id -> task

def print_debug(message: str):
    """Print a debug message with timestamp."""
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{timestamp}] {message}")

def count_evidence_by_type(case_info) -> Tuple[int, int, int, int]:
    """
    Count evidence items by type.
    
    Args:
        case_info: The case information containing evidence
        
    Returns:
        Tuple of (text_count, photo_count, audio_count, note_count)
    """
    text_count = 0
    photo_count = 0
    audio_count = 0
    note_count = 0
    
    for item in case_info.evidence:
        item_type = getattr(item, "type", None)
        if item_type == "text":
            text_count += 1
        elif item_type == "photo":
            photo_count += 1
        elif item_type == "audio":
            audio_count += 1
        elif item_type == "note":
            note_count += 1
    
    return text_count, photo_count, audio_count, note_count

async def get_evidence_summary_message(case_info: Dict[str, Any]) -> str:
    """
    Generate a message summarizing all evidence collected so far
    
    Args:
        case_info: The case information dictionary
        
    Returns:
        A formatted message string with evidence counts
    """
    text_count, photo_count, audio_count, note_count = count_evidence_by_type(case_info)
    
    summary = "✅ Evidence added successfully!\n\n"
    summary += "Current evidence summary:\n"
    summary += f"📝 Text notes: {text_count}\n"
    summary += f"📷 Photos: {photo_count}\n"
    summary += f"🎤 Audio/Voice: {audio_count}\n"
    
    # Check if location is provided
    has_location = hasattr(case_info, 'attendance_location') and case_info.attendance_location is not None
    if has_location:
        summary += f"📍 Location: Included\n"
    else:
        summary += f"📍 Location: Not provided\n"
    
    if note_count > 0:
        summary += f"📌 Other notes: {note_count}\n"
    
    summary += "\nType /finish when you've completed your evidence collection or /cancel to discard."
    
    return summary

async def send_evidence_prompt(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, case_info=None) -> None:
    """
    Send the evidence collection prompt with menu to the user.
    
    Args:
        workflow_manager: The workflow manager instance
        user_id: The user's Telegram ID
        case_id: The case ID
        case_info: Optional pre-loaded case info
    """
    print_debug(f"Sending evidence collection prompt for case {case_id}")
    
    # Load case info if not provided
    if not case_info:
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Failed to load case {case_id} for evidence prompt")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "❌ Error: Could not load case information. Please try again."
            )
            return
    
    # Create the evidence collection menu
    keyboard = [
        [
            InlineKeyboardButton("✅ Finish Collection", callback_data="finish_collection"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_evidence_collection")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="show_evidence_help")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Build the evidence collection message
    message = (
        "📋 *Evidence Collection*\n\n"
        "Please submit evidence for this case:\n\n"
        "• Send text messages for notes\n"
        "• Send photos for visual evidence\n"
        "• Send voice messages for audio records\n"
        "• Share your location to record site coordinates\n\n"
        "When finished, click the 'Finish Collection' button or type /finish."
    )
    
    # Send the message with the menu
    await workflow_manager.telegram_client.send_message(
        user_id,
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def _safe_update_message(workflow_manager: 'WorkflowManager', chat_id: int, message_id: int, text: str) -> bool:
    """
    Safely update a message, catching any exceptions.
    
    Args:
        workflow_manager: The workflow manager instance.
        chat_id: The chat ID to update the message in.
        message_id: The message ID to update.
        text: The new text for the message.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        if workflow_manager.telegram_client:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text
            )
            return True
        else:
            logger.error("Cannot update message: No telegram_client in workflow_manager")
            return False
    except Exception as e:
        logger.error(f"Failed to update message {message_id} in chat {chat_id}: {e}")
        return False 