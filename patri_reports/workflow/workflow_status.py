import logging
import asyncio
import datetime
from typing import Dict, Optional, Any, TYPE_CHECKING
from datetime import timezone

from telegram.error import BadRequest, TelegramError
from telegram.constants import ParseMode

from ..state_manager import AppState
from ..utils.error_handler import DataError
from ..models.case import CaseInfo

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager
    from .telegram_client import TelegramClient
    from .case_manager import CaseManager

logger = logging.getLogger(__name__)

async def format_case_status_message(case_id: str, case_manager: "CaseManager") -> Optional[str]:
    """Format the case status message based on case information."""
    try:
        # DEBUG: Add detailed logging of function entry and parameters
        logger.debug(f"Entering format_case_status_message for case {case_id}")
        
        # Load the case info
        case_info = case_manager.load_case(case_id)
        if not case_info:
            logger.warning(f"Could not load case info for case {case_id}")
            return None
        
        # DEBUG: Log available attributes and their types
        logger.debug(f"CaseInfo object attributes: {dir(case_info)}")
        logger.debug(f"CaseInfo type: {type(case_info)}")
        
        # Format creation date if available
        creation_date = "N/A"
        if hasattr(case_info, 'timestamps') and case_info.timestamps:
            logger.debug(f"timestamps attribute found: {case_info.timestamps}")
            if case_info.timestamps.case_received:
                creation_date = case_info.timestamps.case_received.strftime("%Y-%m-%d %H:%M UTC")
                logger.debug(f"Formatted creation date: {creation_date}")
        else:
            logger.debug("No timestamps attribute found")
        
        # Count evidence files - check if evidence attribute exists
        evidence_count = 0
        if hasattr(case_info, 'evidence') and case_info.evidence:
            evidence_count = len(case_info.evidence)
            logger.debug(f"Found {evidence_count} evidence items")
        else:
            logger.debug("No evidence attribute found or evidence is empty")
        
        # Extract location information
        location_info = []
        if hasattr(case_info, 'address') and case_info.address:
            location_info.append(case_info.address)
            logger.debug(f"Added address to location info: {case_info.address}")
        if hasattr(case_info, 'city') and case_info.city:
            location_info.append(case_info.city)
            logger.debug(f"Added city to location info: {case_info.city}")
        
        # Format the message with HTML
        status_text = f"<b>📁 Case Status: {case_id}</b>\n\n"
        status_text += f"<b>Created:</b> {creation_date}\n"
        status_text += f"<b>Evidence Files:</b> {evidence_count}\n"
        
        if location_info:
            status_text += "\n<b>Location:</b>\n"
            for i, location in enumerate(location_info, 1):
                status_text += f"  {i}. {location}\n"
        
        logger.debug(f"Formatted status text: {status_text}")
        return status_text
    except Exception as e:
        logger.error(f"Error formatting status message for case {case_id}: {e}", exc_info=True)
        return None

async def create_case_status_message(workflow_manager: 'WorkflowManager', user_id: int, case_id: str) -> Optional[int]:
    """Create a simple status message for a case and pin it.
    
    Args:
        workflow_manager: The workflow manager instance
        user_id: The user ID to send the message to
        case_id: The case ID to create a status message for
        
    Returns:
        The message ID of the created message if successful, None otherwise
    """
    # DEBUG: Add detailed logging
    logger.debug(f"Entering create_case_status_message for case {case_id}, user {user_id}")
    
    telegram_client = workflow_manager.telegram_client
    case_manager = workflow_manager.case_manager
    
    if not telegram_client:
        logger.error(f"No telegram client available for creating status message for case {case_id}")
        return None
    
    try:
        # Load the case info to get the display_id
        case_info = case_manager.load_case(case_id)
        if not case_info:
            logger.warning(f"Could not load case info for case {case_id} in create_case_status_message")
            return None
        
        logger.info(f"Creating status message for case {case_id}")
        
        # Use the case's display ID if available, otherwise use the raw case_id
        if hasattr(case_info, 'get_display_id'):
            display_id = case_info.get_display_id()
        else:
            display_id = case_id
            
        # Create a simple status message containing just the case ID, without any additional text
        status_text = f"<b>{display_id}</b>"
        
        # Check if we already have a pinned message ID for this user
        if hasattr(workflow_manager, 'pinned_message_ids') and user_id in workflow_manager.pinned_message_ids:
            logger.info(f"Already have a pinned message for user {user_id}, skipping creation")
            return workflow_manager.pinned_message_ids[user_id]
        
        # First, try to unpin all messages
        try:
            await telegram_client.unpin_all_messages(chat_id=user_id)
            logger.info(f"Unpinned all messages for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to unpin all messages for user {user_id}: {e}")
        
        # Send the message
        max_retries = 3
        retry_count = 0
        message = None
        
        while retry_count < max_retries and not message:
            try:
                message = await telegram_client.send_message(
                    chat_id=user_id,
                    text=status_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Successfully sent status message for case {case_id}")
            except Exception as e:
                retry_count += 1
                logger.warning(f"Attempt {retry_count} failed to send status message for case {case_id}: {e}")
                if retry_count < max_retries:
                    await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                else:
                    logger.error(f"Failed to send status message for case {case_id} after {max_retries} attempts")
                    return None
        
        # If we got a message object back, try to pin it
        if message:
            message_id = message.message_id
            try:
                await telegram_client.pin_message(
                    chat_id=user_id,
                    message_id=message_id
                )
                logger.info(f"Pinned status message {message_id} for case {case_id}")
            except Exception as e:
                logger.warning(f"Failed to pin status message for case {case_id}: {e}")
            
            # Store message ID in workflow_manager's pinned_message_ids if available
            if hasattr(workflow_manager, 'pinned_message_ids'):
                logger.debug(f"workflow_manager has pinned_message_ids attribute: {workflow_manager.pinned_message_ids}")
                workflow_manager.pinned_message_ids[user_id] = message_id
                logger.info(f"Stored status message ID {message_id} for case {case_id} in pinned_message_ids")
            else:
                logger.debug("workflow_manager does not have pinned_message_ids attribute")
                # Initialize it if it doesn't exist
                setattr(workflow_manager, 'pinned_message_ids', {})
                workflow_manager.pinned_message_ids[user_id] = message_id
                logger.info(f"Created pinned_message_ids attribute and stored message ID {message_id}")
            
            return message_id
        else:
            logger.warning(f"Received None message object for case {case_id}")
            return None
    except Exception as e:
        logger.error(f"Error creating status message for case {case_id}: {e}", exc_info=True)
        return None

async def update_case_status_message(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, case_info: Optional['CaseInfo'] = None) -> None:
    """
    Send a new status message for a case and pin it, replacing any existing pinned message.
    This will unpin any existing messages and pin the new one.
    
    Args:
        workflow_manager: The workflow manager instance
        user_id: The user ID to send/update the message to
        case_id: The case ID to update the status message for
        case_info: Optional case info to use (to avoid reloading)
    """
    # DEBUG: Add detailed logging
    logger.debug(f"Entering update_case_status_message for case {case_id}, user {user_id}")
    
    # Check if there's already a pinned message for this user
    if (hasattr(workflow_manager, 'pinned_message_ids') and 
        user_id in workflow_manager.pinned_message_ids):
        logger.info(f"Status message already exists for user {user_id}, skipping creation")
        return
    
    # Only create a new message if one doesn't exist
    await create_case_status_message(workflow_manager, user_id, case_id)

def _format_case_status(case_info) -> str:
    """Format case information for status display.
    
    Args:
        case_info: CaseInfo object or dictionary containing case data
        
    Returns:
        Formatted status string
    """
    status_parts = []
    
    # Handle both CaseInfo object and dictionary
    if isinstance(case_info, dict):
        # Dictionary case
        case_id = case_info.get("case_id", "Unknown")
        evidence_items = case_info.get("evidence", [])
        timestamp = case_info.get("timestamp", {})
        
        status_parts.append(f"📁 *CASE ID:* {case_id}")
        
        # Add timestamps if available
        if timestamp:
            if timestamp.get("case_received"):
                status_parts.append(f"🕒 *Opened:* {timestamp['case_received']}")
            if timestamp.get("attendance_started"):
                status_parts.append(f"🏁 *Collection started:* {timestamp['attendance_started']}")
            if timestamp.get("collection_finished"):
                status_parts.append(f"✅ *Collection finished:* {timestamp['collection_finished']}")
        
        # Evidence count
        status_parts.append(f"📊 *Evidence items:* {len(evidence_items)}")
        
        # Evidence counts by type
        text_count = sum(1 for item in evidence_items if item.get("type") == "text")
        photo_count = sum(1 for item in evidence_items if item.get("type") == "photo")
        audio_count = sum(1 for item in evidence_items if item.get("type") == "audio")
        note_count = sum(1 for item in evidence_items if item.get("type") == "note")
        
        evidence_breakdown = []
        if text_count > 0:
            evidence_breakdown.append(f"📝 Text: {text_count}")
        if photo_count > 0:
            evidence_breakdown.append(f"📷 Photos: {photo_count}")
        if audio_count > 0:
            evidence_breakdown.append(f"🎤 Audio: {audio_count}")
        if note_count > 0:
            evidence_breakdown.append(f"📌 Notes: {note_count}")
            
        if evidence_breakdown:
            status_parts.append("  - " + "\n  - ".join(evidence_breakdown))
    else:
        # CaseInfo object
        case_id_display = case_info.get_display_id()
        status_parts.append(f"📁 *CASE ID:* {case_id_display}")
        
        # Add timestamps if available
        if case_info.timestamps:
            if case_info.timestamps.case_received:
                status_parts.append(f"🕒 *Opened:* {case_info.timestamps.case_received.strftime('%Y-%m-%d %H:%M')}")
            if case_info.timestamps.attendance_started:
                status_parts.append(f"🏁 *Collection started:* {case_info.timestamps.attendance_started.strftime('%Y-%m-%d %H:%M')}")
            if case_info.timestamps.collection_finished:
                status_parts.append(f"✅ *Collection finished:* {case_info.timestamps.collection_finished.strftime('%Y-%m-%d %H:%M')}")
        
        # Evidence count
        status_parts.append(f"📊 *Evidence items:* {len(case_info.evidence)}")
        
        # Evidence counts by type
        text_count = 0
        photo_count = 0
        audio_count = 0
        note_count = 0

        for item in case_info.evidence:
            # Try both potential attribute names: evidence_type or type
            item_type = None
            if hasattr(item, 'evidence_type'):
                item_type = item.evidence_type
            elif hasattr(item, 'type'):
                item_type = item.type
            
            if item_type == "text":
                text_count += 1
            elif item_type == "photo":
                photo_count += 1
            elif item_type == "audio":
                audio_count += 1
            elif item_type == "note":
                note_count += 1
        
        evidence_breakdown = []
        if text_count > 0:
            evidence_breakdown.append(f"📝 Text: {text_count}")
        if photo_count > 0:
            evidence_breakdown.append(f"📷 Photos: {photo_count}")
        if audio_count > 0:
            evidence_breakdown.append(f"🎤 Audio: {audio_count}")
        if note_count > 0:
            evidence_breakdown.append(f"📌 Notes: {note_count}")
            
        if evidence_breakdown:
            status_parts.append("  - " + "\n  - ".join(evidence_breakdown))
    
    return "\n".join(status_parts) 