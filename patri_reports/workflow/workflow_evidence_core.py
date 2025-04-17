import logging
import datetime
import asyncio
from typing import Optional, TYPE_CHECKING, Dict, Any, Tuple, List, Union, Callable

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from telegram.ext import ContextTypes

from ..state_manager import AppState
from ..utils.error_handler import NetworkError, TimeoutError, DataError
from .workflow_status import update_case_status_message, create_case_status_message
from ..models.case import CaseInfo, TextEvidence
from .workflow_evidence_utils import print_debug, send_evidence_prompt, count_evidence_by_type, _safe_update_message, ongoing_media_groups, media_group_summaries_sent, media_group_timers, get_evidence_summary_message
from .workflow_evidence_photo import process_photo_batch, process_photo_evidence, handle_photo_message
from .workflow_evidence_location import handle_location_message
from .workflow_evidence_audio import handle_photo_description, handle_voice_message

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager
    from ..models.user import UserInfo

logger = logging.getLogger(__name__)

async def finish_collection_workflow(workflow_manager: 'WorkflowManager', user_id: int, case_id: str):
    """Finish the evidence collection workflow and return to idle state."""
    # Cancel any pending media group timers
    media_group_id = workflow_manager.state_manager.get_metadata().get("current_media_group_id")
    if media_group_id and media_group_id in media_group_timers:
        # Cancel the timer task
        if media_group_timers[media_group_id] and not media_group_timers[media_group_id].done():
            media_group_timers[media_group_id].cancel()
        # Clean up
        media_group_timers.pop(media_group_id, None)
        ongoing_media_groups.pop(media_group_id, None)
        media_group_summaries_sent.pop(media_group_id, None)
    
    # Update case info to mark collection finished
    case_info = workflow_manager.case_manager.load_case(case_id)
    if case_info:
        # Set timestamp for collection finished
        if hasattr(case_info, 'timestamps') and case_info.timestamps:
            case_info.timestamps.collection_finished = datetime.datetime.now()
            workflow_manager.case_manager.save_case(case_info)
    
    # Update case status
    workflow_manager.case_manager.update_llm_data(case_id, "collection_complete")
    
    # Update status message
    await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
    
    # Send completion message
    await workflow_manager.telegram_client.send_message(
        user_id,
        "✅ Evidence collection complete. Your evidence has been saved.\n\nTo start a new case, use the button below."
    )
    
    # Transition to IDLE state
    workflow_manager.state_manager.set_state(AppState.IDLE)
    
    # Show only the button without welcome message
    keyboard = [
        [InlineKeyboardButton("➕ Start New Case", callback_data="start_new_case")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await workflow_manager.telegram_client.send_message(
        user_id, 
        "Ready for the next case when you are.", 
        reply_markup=reply_markup
    )

async def cancel_collection_workflow(workflow_manager: 'WorkflowManager', user_id: int, case_id: str):
    """Cancel the evidence collection workflow."""
    # Cancel any pending media group timers
    media_group_id = workflow_manager.state_manager.get_metadata().get("current_media_group_id")
    if media_group_id and media_group_id in media_group_timers:
        # Cancel the timer task
        if media_group_timers[media_group_id] and not media_group_timers[media_group_id].done():
            media_group_timers[media_group_id].cancel()
        # Clean up
        media_group_timers.pop(media_group_id, None)
        ongoing_media_groups.pop(media_group_id, None)
        media_group_summaries_sent.pop(media_group_id, None)
    
    # Update case status 
    workflow_manager.case_manager.update_llm_data(case_id, "canceled")
    
    # Physically delete the case data
    deleted = workflow_manager.case_manager.delete_case(case_id)
    if deleted:
        print_debug(f"Successfully deleted case directory for canceled case {case_id}")
    else:
        logger.warning(f"Failed to delete case directory for canceled case {case_id}")
    
    # Send cancellation message
    await workflow_manager.telegram_client.send_message(
        user_id,
        "❌ Evidence collection canceled. Your case has been discarded."
    )
    
    # Transition to IDLE state
    workflow_manager.state_manager.set_state(AppState.IDLE)
    
    # Show only the button without welcome message
    keyboard = [
        [InlineKeyboardButton("➕ Start New Case", callback_data="start_new_case")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await workflow_manager.telegram_client.send_message(
        user_id, 
        "Ready for the next case when you are.", 
        reply_markup=reply_markup
    )

async def handle_evidence_collection_state(workflow_manager: 'WorkflowManager', update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, case_id: str):
    """Handle user interactions in the EVIDENCE_COLLECTION state."""
    print_debug(f"ENTER handle_evidence_collection_state for case {case_id}, user {user_id}")
    if not workflow_manager.telegram_client:
        print_debug(f"EXIT handle_evidence_collection_state - No telegram_client")
        return
        
    # Extract telegram objects
    message = update.message
    query = update.callback_query
    
    # Handle callback queries (button clicks)
    if query:
        # Answer the callback query to clear the loading state
        await query.answer()
        
        # Handle different callback types based on data
        if query.data.startswith("photo_batch_fingerprint_yes_"):
            # User confirmed these are fingerprint photos
            batch_id = query.data.replace("photo_batch_fingerprint_yes_", "")
            from .workflow_evidence_photo import handle_photo_batch_fingerprint_response
            await handle_photo_batch_fingerprint_response(workflow_manager, user_id, case_id, batch_id, True)
            
        elif query.data.startswith("photo_batch_fingerprint_no_"):
            # User said these are not fingerprint photos
            batch_id = query.data.replace("photo_batch_fingerprint_no_", "")
            from .workflow_evidence_photo import handle_photo_batch_fingerprint_response
            await handle_photo_batch_fingerprint_response(workflow_manager, user_id, case_id, batch_id, False)
            
        # Handle new shortened fingerprint callback formats
        elif query.data.startswith("fp_y_"):
            # User confirmed these are fingerprint photos (shortened format)
            short_batch_id = query.data.replace("fp_y_", "")
            # Get the full batch_id from the mapping
            batch_id = getattr(workflow_manager, 'short_to_full_batch_ids', {}).get(short_batch_id, short_batch_id)
            from .workflow_evidence_photo import handle_photo_batch_fingerprint_response
            await handle_photo_batch_fingerprint_response(workflow_manager, user_id, case_id, batch_id, True)
            
        elif query.data.startswith("fp_n_"):
            # User said these are not fingerprint photos (shortened format)
            short_batch_id = query.data.replace("fp_n_", "")
            # Get the full batch_id from the mapping
            batch_id = getattr(workflow_manager, 'short_to_full_batch_ids', {}).get(short_batch_id, short_batch_id)
            from .workflow_evidence_photo import handle_photo_batch_fingerprint_response
            await handle_photo_batch_fingerprint_response(workflow_manager, user_id, case_id, batch_id, False)
            
        elif query.data.startswith("del_p_"):
            # User wants to delete a photo during description phase
            # Format: del_p_<evidence_id_prefix>_<index>
            parts = query.data.replace("del_p_", "").split("_")
            if len(parts) == 2:
                evidence_id_prefix, index_str = parts
                try:
                    index = int(index_str)
                    # Find the full evidence ID from the prefix
                    metadata = workflow_manager.state_manager.get_metadata()
                    batch_id = metadata.get("photo_description_batch_id")
                    if batch_id and batch_id in workflow_manager.photo_batch_evidence_ids:
                        # Look through evidence IDs to find the one that starts with the prefix
                        for full_id in workflow_manager.photo_batch_evidence_ids[batch_id]:
                            if full_id.startswith(evidence_id_prefix):
                                evidence_id = full_id
                                from .workflow_evidence_photo import handle_delete_photo
                                await handle_delete_photo(workflow_manager, user_id, case_id, evidence_id, batch_id, index)
                                break
                        else:
                            logger.error(f"Could not find evidence ID starting with prefix {evidence_id_prefix}")
                            await workflow_manager.telegram_client.send_message(
                                user_id,
                                "❌ Error: Could not find the photo to delete. Please try again."
                            )
                    else:
                        logger.error(f"Missing batch_id in metadata when handling photo delete")
                        await workflow_manager.telegram_client.send_message(
                            user_id,
                            "❌ Error: Photo delete operation failed. Please try again."
                        )
                except ValueError:
                    logger.error(f"Invalid index in delete_photo callback: {index_str}")
                    await workflow_manager.telegram_client.send_message(
                        user_id, 
                        "❌ Error: Invalid photo index. Please try again."
                    )
            else:
                logger.error(f"Invalid delete_photo callback data: {query.data}")
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    "❌ Error: Invalid delete command format. Please try again."
                )
            
        elif query.data == "finish_evidence_collection" or query.data == "finish_collection":
            print_debug(f"Processing finish_evidence_collection callback for case {case_id}")
            # Ask for confirmation before finishing
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, finish collection", callback_data="confirm_finish"),
                    InlineKeyboardButton("❌ No, continue collecting", callback_data="abort_finish")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await workflow_manager.telegram_client.send_message(
                user_id,
                "⚠️ *Finish evidence collection?* You won't be able to add more evidence to this case.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
        elif query.data == "confirm_finish":
            print_debug(f"User confirmed finish for case {case_id}")
            await finish_collection_workflow(workflow_manager, user_id, case_id)
            
        elif query.data == "abort_finish":
            print_debug(f"User aborted finish for case {case_id}")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "✅ Finish aborted. You can continue collecting evidence."
            )
            
        elif query.data == "cancel_evidence_collection":
            print_debug(f"Processing cancel_evidence_collection callback for case {case_id}")
            # Ask for confirmation before actually cancelling
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, discard everything", callback_data="confirm_cancel"),
                    InlineKeyboardButton("❌ No, continue collecting", callback_data="abort_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await workflow_manager.telegram_client.send_message(
                user_id,
                "⚠️ *Are you sure?* This will discard all evidence you've collected so far.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
        elif query.data == "confirm_cancel":
            print_debug(f"User confirmed cancellation for case {case_id}")
            await cancel_collection_workflow(workflow_manager, user_id, case_id)
            
        elif query.data == "abort_cancel":
            print_debug(f"User aborted cancellation for case {case_id}")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "✅ Cancellation aborted. Your evidence collection continues."
            )
            
        elif query.data == "show_evidence_help":
            print_debug(f"Processing show_evidence_help callback for case {case_id}")
            # Show help for evidence collection
            help_text = (
                "📋 *Evidence Collection Help*\n\n"
                "You can add evidence in the following ways:\n\n"
                "📝 *Text Notes*: Just type any text message\n\n"
                "🖼 *Photos*: Send photos individually or as a group\n\n"
                "🎤 *Voice Notes*: Record and send voice messages\n\n"
                "📍 *Location*: Share your current location\n\n"
                "When you've collected all needed evidence, type /finish or use the menu."
            )
            await workflow_manager.telegram_client.send_message(
                user_id,
                help_text,
                parse_mode="Markdown"
            )
        
        else:
            await query.answer("Unknown option")
            logger.warning(f"Received unexpected callback data in EVIDENCE_COLLECTION state: {query.data}")
        
        print_debug(f"EXIT handle_evidence_collection_state after query {query.data}")
        return
        
    # Rest of the method handling text, photo, voice messages, etc.
    if message and message.text is not None:
        print_debug(f"Handling text message for {case_id}")
        
        # Check for commands
        if message.text.strip().lower() == "/finish":
            print_debug(f"Processing /finish command for case {case_id}")
            # Ask for confirmation before finishing
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, finish collection", callback_data="confirm_finish"),
                    InlineKeyboardButton("❌ No, continue collecting", callback_data="abort_finish")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await workflow_manager.telegram_client.send_message(
                user_id,
                "⚠️ *Finish evidence collection?* You won't be able to add more evidence to this case.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return
            
        elif message.text.strip().lower() == "/cancel":
            print_debug(f"Processing /cancel command for case {case_id}")
            # Ask for confirmation before actually cancelling
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, discard everything", callback_data="confirm_cancel"),
                    InlineKeyboardButton("❌ No, continue collecting", callback_data="abort_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await workflow_manager.telegram_client.send_message(
                user_id,
                "⚠️ *Are you sure?* This will discard all evidence you've collected so far.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return
        
        elif message.text.strip().lower() == "/help":
            print_debug(f"Processing /help command for case {case_id}")
            # Show help for evidence collection
            help_text = (
                "📋 *Evidence Collection Help*\n\n"
                "You can add evidence in the following ways:\n\n"
                "📝 *Text Notes*: Just type any text message\n\n"
                "🖼 *Photos*: Send photos individually or as a group\n\n"
                "🎤 *Voice Notes*: Record and send voice messages\n\n"
                "📍 *Location*: Share your current location\n\n"
                "When you've collected all needed evidence, type /finish or use the menu."
            )
            await workflow_manager.telegram_client.send_message(
                user_id,
                help_text,
                parse_mode="Markdown"
            )
            return
            
        # Check if we're waiting for a photo description
        metadata = workflow_manager.state_manager.get_metadata()
        if metadata.get("awaiting_photo_description"):
            # This is a description for a photo
            await handle_photo_description(
                workflow_manager, 
                user_id, 
                case_id, 
                message.text,
                is_audio=False
            )
            return
        
        # Otherwise, treat as a text evidence
        print_debug(f"Adding text evidence for case {case_id}")
        evidence_id = workflow_manager.case_manager.add_text_evidence(case_id, message.text)
        
        if evidence_id:
            # Reload case info and update the status message
            case_info = workflow_manager.case_manager.load_case(case_id)
            await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
            
            # Send confirmation with evidence summary
            summary_message = await get_evidence_summary_message(case_info)
            confirmation_message = f"✅ Text note added.\n\n{summary_message}"
            
            await workflow_manager.telegram_client.send_message(
                user_id, 
                confirmation_message
            )
        else:
            await workflow_manager.telegram_client.send_message(
                user_id,
                "❌ Failed to save text note. Please try again."
            )
            
        print_debug(f"EXIT handle_evidence_collection_state after text message")
        return
            
    elif message and message.photo:
        print_debug(f"Handling photo message for {case_id}")
        
        # Check if we're waiting for a photo description
        metadata = workflow_manager.state_manager.get_metadata()
        if metadata.get("awaiting_photo_description"):
            # User sent a photo instead of a description
            await workflow_manager.telegram_client.send_message(
                user_id,
                "❌ Please provide a text or voice description for the photo, not another photo."
            )
            return
        
        # Import here to avoid circular imports
        from .workflow_evidence_photo import handle_photo_message
        await handle_photo_message(workflow_manager, user_id, case_id, message)
        print_debug(f"EXIT handle_evidence_collection_state after photo")
        return
            
    elif message and message.voice:
        print_debug(f"Handling voice message for {case_id}")
        
        # Import here to avoid circular imports
        from .workflow_evidence_audio import handle_voice_message
        await handle_voice_message(workflow_manager, user_id, case_id, message)
        print_debug(f"EXIT handle_evidence_collection_state after voice")
        return

    elif message and message.location:
        print_debug(f"Handling location message for {case_id}")
        # Process location as evidence
        await handle_location_message(workflow_manager, user_id, case_id, message.location)
        
        print_debug(f"EXIT handle_evidence_collection_state after location")
        return

    # If we got here, we didn't handle the message
    if message:
        # Try to log all available message types for debugging
        available_attrs = []
        for attr in ['animation', 'audio', 'contact', 'dice', 'document', 'game', 'location', 'photo', 'poll', 
                    'sticker', 'successful_payment', 'text', 'venue', 'video', 'video_note', 'voice', 'caption', 'media_group_id']:
            if hasattr(message, attr) and getattr(message, attr) is not None:
                available_attrs.append(attr)
        
        logger.warning(f"Unhandled message type in EVIDENCE_COLLECTION state from user {user_id}: {available_attrs}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Sorry, I can't process this type of message as evidence. Please send text, photos, voice messages, or location."
        )
        
    print_debug(f"EXIT handle_evidence_collection_state - Unhandled message") 