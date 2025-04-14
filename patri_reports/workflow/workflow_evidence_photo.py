import logging
import os
import time
import asyncio
from typing import Optional, List, Dict, TYPE_CHECKING
from collections import defaultdict
from pathlib import Path
import datetime

from telegram import PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..models.case import CaseInfo, PhotoEvidence
from ..utils.error_handler import NetworkError, TimeoutError, DataError
from .workflow_status import update_case_status_message
from .workflow_evidence_utils import print_debug, media_group_summaries_sent, media_group_timers, get_evidence_summary_message

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

async def handle_photo_message(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, message: Message):
    """Handles a photo message, including media groups."""
    print_debug(f"Handling photo message for case {case_id}")
    
    # Track photos based on media_group_id or time proximity
    if message.media_group_id:
        # Part of a photo group/album
        is_batch = True
        batch_id = message.media_group_id
        
        # Initialize batch tracking if this is the first photo
        if batch_id not in workflow_manager.photo_batch_evidence_ids:
            workflow_manager.photo_batch_evidence_ids[batch_id] = []
            
        # Set up a timer that will trigger batch fingerprint question
        async def summarize_batch():
            # Wait for a short time to ensure all photos are received
            await asyncio.sleep(3)
            
            # Check if we have photos in this batch
            if batch_id in workflow_manager.photo_batch_evidence_ids and workflow_manager.photo_batch_evidence_ids[batch_id]:
                # Only send summary if it hasn't been sent already
                if batch_id not in media_group_summaries_sent:
                    media_group_summaries_sent.add(batch_id)
                    await process_photo_batch(workflow_manager, user_id, case_id, batch_id)
        
        # Cancel any existing timer for this batch
        if batch_id in media_group_timers:
            media_group_timers[batch_id].cancel()
            
        # Create a new timer
        media_group_timers[batch_id] = asyncio.create_task(summarize_batch())
    else:
        # Check if this could be part of a time-based batch
        current_time = time.time()
        if user_id in workflow_manager.last_photo_time:
            time_since_last_photo = current_time - workflow_manager.last_photo_time[user_id]
            if time_since_last_photo < 10:  # 10 seconds threshold for same batch
                # Treat as part of a batch, create a batch ID if none exists
                is_batch = True
                batch_id = f"time_batch_{user_id}_{int(current_time / 10)}"  # Group by 10-second intervals
                
                # Initialize batch tracking if this is the first photo with this ID
                if batch_id not in workflow_manager.photo_batch_evidence_ids:
                    workflow_manager.photo_batch_evidence_ids[batch_id] = []
                    
                # Set up a timer that will trigger batch questions
                async def summarize_batch():
                    # Wait for a longer time than media_group_id batches since timing is less reliable
                    await asyncio.sleep(5)
                    
                    if batch_id in workflow_manager.photo_batch_evidence_ids and workflow_manager.photo_batch_evidence_ids[batch_id]:
                        if batch_id not in media_group_summaries_sent:
                            media_group_summaries_sent.add(batch_id)
                            await process_photo_batch(workflow_manager, user_id, case_id, batch_id)
            
                # Cancel any existing timer for this batch
                if batch_id in media_group_timers:
                    media_group_timers[batch_id].cancel()
                    
                # Create a new timer
                media_group_timers[batch_id] = asyncio.create_task(summarize_batch())
            else:
                # This is a standalone photo - handle as a single photo
                batch_id = None
                is_batch = False
        else:
            # This is a standalone photo - handle as a single photo
            batch_id = None
            is_batch = False
                
        # Update last photo time
        workflow_manager.last_photo_time[user_id] = current_time
    
    # Process the photo evidence
    try:
        evidence_id = await process_photo_evidence(workflow_manager, user_id, case_id, message.photo, batch_id)
        if evidence_id:
            # Track evidence ID if part of a batch
            if is_batch and batch_id:
                workflow_manager.photo_batch_evidence_ids[batch_id].append(evidence_id)
                # Update the status message but don't send individual confirmations
                # for photos in a batch
                case_info = workflow_manager.case_manager.load_case(case_id)
                await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
            else:
                # This is a standalone photo, send direct confirmation and start asking for info
                case_info = workflow_manager.case_manager.load_case(case_id)
                await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
                
                # Create a one-photo batch and start the description flow
                batch_id = f"single_photo_{evidence_id}"
                workflow_manager.photo_batch_evidence_ids[batch_id] = [evidence_id]
                await process_photo_batch(workflow_manager, user_id, case_id, batch_id)
        else:
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Failed to save photo. Please try again."
            )
    except (NetworkError, DataError, TimeoutError) as e:
        # Network errors are handled by WorkflowManager.handle_error
        logger.error(f"Error processing photo for case {case_id}: {e}")
        raise

async def process_photo_evidence(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, photo_list: List[PhotoSize], batch_id: Optional[str] = None) -> Optional[str]:
    """Process a photo evidence submission without immediate description request."""
    print_debug(f"ENTER process_photo_evidence for case {case_id}, user {user_id}")
    
    if not photo_list:
        print_debug(f"EXIT process_photo_evidence - No photos provided")
        return None
        
    # Get the largest photo (last in the list)
    photo = photo_list[-1]
    
    # Only send processing message for standalone photos (not in a batch)
    if not batch_id:
        try:
            logger.info(f"Sending 'Processing photo...' message for case {case_id}")
            await workflow_manager.telegram_client.send_message(user_id, "Processing photo...")
        except Exception as e:
            logger.warning(f"Failed to send 'Processing photo...' message for case {case_id}: {e}")
    
    try:
        # Download photo
        print_debug(f"Downloading photo {photo.file_id} for case {case_id}")
        photo_data, error_message = await workflow_manager.telegram_client.download_file(photo.file_id)
        
        if error_message or not photo_data:
            error_text = f"❌ Failed to download photo: {error_message or 'Unknown error'}. Please try again."
            await workflow_manager.telegram_client.send_message(user_id, error_text)
            print_debug(f"EXIT process_photo_evidence - Download failed")
            return None
            
        # Save photo evidence - initially with default naming, we'll rename later
        print_debug(f"Calling add_photo_evidence for case {case_id}")
        evidence_id = workflow_manager.case_manager.add_photo_evidence(case_id, photo_data)
        
        if evidence_id:
            print_debug(f"EXIT process_photo_evidence - Success (ID: {evidence_id})")
            return evidence_id
        else:
            error_text = "❌ Failed to save photo evidence. Please try again."
            await workflow_manager.telegram_client.send_message(user_id, error_text)
            print_debug(f"EXIT process_photo_evidence - Save failed")
            return None
            
    except (NetworkError, DataError) as e:
        # Propagate these specific errors to caller
        logger.error(f"Error in photo evidence processing: {e}")
        error_text = f"❌ Error processing photo: {e}. Please try again."
        await workflow_manager.telegram_client.send_message(user_id, error_text)
        print_debug(f"EXIT process_photo_evidence - Network/Data error")
        raise
        
    except Exception as e:
        # Handle other exceptions here but don't propagate them
        logger.exception(f"Unexpected error processing photo evidence: {e}")
        error_text = "❌ Failed to save photo evidence. Please try again."
        await workflow_manager.telegram_client.send_message(user_id, error_text)
        print_debug(f"EXIT process_photo_evidence - Unexpected error")
        return None

async def process_photo_batch(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, batch_id: str):
    """
    Process a batch of photos, asking if they are fingerprints and collecting descriptions.
    
    This function is called after a batch of photos has been received and saved.
    It will:
    1. Ask if the photos are fingerprints
    2. For each photo, show it and ask for a description
    3. Rename the files to photo001.jpg, photo002.jpg, etc.
    4. Update the metadata in the case info
    """
    print_debug(f"ENTER process_photo_batch for case {case_id}, batch {batch_id}")
    
    # Check if the batch ID exists
    if batch_id not in workflow_manager.photo_batch_evidence_ids:
        logger.error(f"Cannot process photo batch: Batch {batch_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: Photo batch information was lost. Please try uploading the photos again."
        )
        return
    
    # Get all evidence IDs for this batch
    evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
    if not evidence_ids:
        logger.error(f"Cannot process photo batch: No photos found in batch {batch_id}")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: No photos were found in this batch. Please try uploading the photos again."
        )
        return
    
    # Load the case info
    case_info = workflow_manager.case_manager.load_case(case_id)
    if not case_info:
        logger.error(f"Cannot process photo batch: Case {case_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: Case information not found. Please try again later."
        )
        return
    
    # First, ask if these photos are fingerprints
    keyboard = [
        [
            InlineKeyboardButton("Yes, fingerprints", callback_data=f"photo_batch_fingerprint_yes_{batch_id}"),
            InlineKeyboardButton("No, regular photos", callback_data=f"photo_batch_fingerprint_no_{batch_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await workflow_manager.telegram_client.send_message(
        user_id,
        "🖐 Are these photos of fingerprints?",
        reply_markup=reply_markup
    )
    
    # The rest of the process will be handled by the callback query handler

async def handle_photo_batch_fingerprint_response(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, 
                                                 batch_id: str, is_fingerprint: bool):
    """
    Handle the response to the fingerprint question and start collecting descriptions.
    """
    print_debug(f"ENTER handle_photo_batch_fingerprint_response: fingerprints={is_fingerprint}")
    
    # Get all evidence IDs for this batch
    evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
    
    # Load the case info to get actual evidence items
    case_info = workflow_manager.case_manager.load_case(case_id)
    if not case_info:
        logger.error(f"Cannot process fingerprint response: Case {case_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: Case information not found. Please try again later."
        )
        return
    
    # Update all photos in this batch to mark as fingerprints
    for evidence_id in evidence_ids:
        workflow_manager.case_manager.update_evidence_metadata(
            case_id, 
            evidence_id, 
            {"is_fingerprint": is_fingerprint}
        )
    
    # If they are fingerprints, we don't need descriptions, so we can rename and finish
    if is_fingerprint:
        await workflow_manager.telegram_client.send_message(
            user_id,
            "✅ Photos marked as fingerprints. No further descriptions needed."
        )
        await rename_photo_batch(workflow_manager, user_id, case_id, batch_id)
    else:
        # Start collecting descriptions for each photo
        await workflow_manager.telegram_client.send_message(
            user_id,
            "Please provide a description for each photo. You can send text or voice messages."
        )
        
        # Start with the first photo
        await request_photo_description(workflow_manager, user_id, case_id, batch_id, 0)

async def request_photo_description(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, 
                                   batch_id: str, index: int):
    """
    Request description for a specific photo in the batch.
    """
    print_debug(f"ENTER request_photo_description for index {index}")
    
    # Get all evidence IDs for this batch
    evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
    
    # Check if we've reached the end of the batch
    if index >= len(evidence_ids):
        # We've collected all descriptions, so rename the files and finish
        await workflow_manager.telegram_client.send_message(
            user_id,
            "✅ All photo descriptions collected. Processing..."
        )
        await rename_photo_batch(workflow_manager, user_id, case_id, batch_id)
        return
    
    # Get the current evidence ID
    evidence_id = evidence_ids[index]
    
    # Load the case info to get the actual evidence item
    case_info = workflow_manager.case_manager.load_case(case_id)
    if not case_info:
        logger.error(f"Cannot request photo description: Case {case_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: Case information not found. Please try again later."
        )
        return

    # Find the photo evidence
    photo_evidence = None
    for evidence in case_info.evidence:
        if evidence.evidence_id == evidence_id and evidence.type == "photo":
            photo_evidence = evidence
            break
    
    if not photo_evidence:
        logger.error(f"Cannot request photo description: Photo evidence {evidence_id} not found")
        # Skip this photo and move to the next one
        await request_photo_description(workflow_manager, user_id, case_id, batch_id, index + 1)
        return
    
    # Create a keyboard with a delete button
    keyboard = [
        [
            InlineKeyboardButton("🗑️ Delete this photo", callback_data=f"del_p_{evidence_id[:8]}_{index}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send the photo to the user
    try:
        # Check if file exists and is readable
        if not os.path.exists(photo_evidence.file_path) or not os.path.isfile(photo_evidence.file_path):
            logger.error(f"Photo file does not exist: {photo_evidence.file_path}")
            raise FileNotFoundError(f"Photo file not found: {photo_evidence.file_path}")
            
        file_size = os.path.getsize(photo_evidence.file_path)
        if file_size == 0:
            logger.error(f"Photo file is empty (0 bytes): {photo_evidence.file_path}")
            raise ValueError(f"Photo file is empty: {photo_evidence.file_path}")
            
        logger.debug(f"Sending photo {photo_evidence.file_path} ({file_size} bytes)")
        
        # Try to reuse a telegram file_id if available
        telegram_file_id = getattr(photo_evidence, 'telegram_file_id', None)
        if telegram_file_id:
            # Use the cached Telegram file_id (most reliable)
            logger.debug(f"Using existing Telegram file_id for photo")
            await workflow_manager.telegram_client.send_photo(
                user_id,
                telegram_file_id,
                caption=f"Photo {index + 1}/{len(evidence_ids)}: Please provide a description for this photo.",
                reply_markup=reply_markup
            )
        else:
            # Fall back to opening the file from disk
            with open(photo_evidence.file_path, "rb") as photo_file:
                sent_message = await workflow_manager.telegram_client.send_photo(
                    user_id,
                    photo_file,
                    caption=f"Photo {index + 1}/{len(evidence_ids)}: Please provide a description for this photo.",
                    reply_markup=reply_markup
                )
                
                # Store the file_id for future use
                if sent_message and sent_message.photo:
                    # Get the largest photo (last in the list)
                    new_file_id = sent_message.photo[-1].file_id if sent_message.photo else None
                    if new_file_id:
                        # Save the telegram_file_id for future use
                        workflow_manager.case_manager.update_evidence_metadata(
                            case_id,
                            evidence_id,
                            {"telegram_file_id": new_file_id}
                        )
                        logger.debug(f"Saved Telegram file_id for photo {evidence_id}")
    except FileNotFoundError as e:
        logger.error(f"Failed to send photo for description request (file not found): {e}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            f"❌ Error showing photo {index + 1}. Skipping to next photo."
        )
        # Skip to the next photo
        await request_photo_description(workflow_manager, user_id, case_id, batch_id, index + 1)
        return
    except Exception as e:
        logger.exception(f"Error showing photo: {e}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            f"❌ Error showing photo {index + 1}. Skipping to next photo."
        )
        # Skip to the next photo
        await request_photo_description(workflow_manager, user_id, case_id, batch_id, index + 1)
        return
    
    # Store the current state - waiting for description for this photo
    workflow_manager.state_manager.set_metadata({
        "awaiting_photo_description": True,
        "photo_description_batch_id": batch_id,
        "photo_description_index": index,
        "photo_description_evidence_id": evidence_id
    })

async def handle_delete_photo(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, 
                             evidence_id: str, batch_id: str, index: int):
    """
    Handle a request to delete a photo during the description phase.
    """
    print_debug(f"ENTER handle_delete_photo for evidence {evidence_id}")
    
    # Load the case info
    case_info = workflow_manager.case_manager.load_case(case_id)
    if not case_info:
        logger.error(f"Cannot delete photo: Case {case_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: Case information not found. Please try again later."
        )
        return
    
    # Find the photo evidence to get the file path
    file_path = None
    for evidence in case_info.evidence:
        if evidence.evidence_id == evidence_id and evidence.type == "photo":
            file_path = evidence.file_path
            break
    
    # Remove the evidence from the case
    case_info.evidence = [e for e in case_info.evidence if e.evidence_id != evidence_id]
    
    # Save the updated case
    if workflow_manager.case_manager.save_case(case_info):
        # Remove the evidence ID from the batch
        if batch_id in workflow_manager.photo_batch_evidence_ids:
            workflow_manager.photo_batch_evidence_ids[batch_id] = [
                eid for eid in workflow_manager.photo_batch_evidence_ids[batch_id] if eid != evidence_id
            ]
        
        # Delete the file if we found the path
        if file_path:
            try:
                os.remove(file_path)
                logger.info(f"Deleted photo file at {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete photo file at {file_path}: {e}")
        
        await workflow_manager.telegram_client.send_message(
            user_id,
            "✅ Photo deleted successfully."
        )
        
        # Clear any awaiting_photo_description state
        workflow_manager.state_manager.set_metadata({
            "awaiting_photo_description": False,
            "photo_description_batch_id": None,
            "photo_description_index": None,
            "photo_description_evidence_id": None
        })
        
        # Check if we still have photos in this batch
        if batch_id in workflow_manager.photo_batch_evidence_ids and workflow_manager.photo_batch_evidence_ids[batch_id]:
            # Continue with the next photo (using the same index since we've removed one)
            await request_photo_description(workflow_manager, user_id, case_id, batch_id, index)
        else:
            # No more photos in this batch
            await workflow_manager.telegram_client.send_message(
                user_id,
                "No more photos remaining in this batch."
            )
            # Update the case status message
            await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
    else:
        logger.error(f"Failed to save case after deleting photo evidence {evidence_id}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Failed to delete photo. Please try again."
        )

async def rename_photo_batch(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, batch_id: str):
    """
    Rename all photos in a batch to photo001.jpg, photo002.jpg, etc.
    """
    print_debug(f"ENTER rename_photo_batch for batch {batch_id}")
    
    # Get all evidence IDs for this batch
    if batch_id not in workflow_manager.photo_batch_evidence_ids:
        logger.error(f"Cannot rename photo batch: Batch {batch_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Error: Photo batch information was lost. Please try again."
        )
        return

    evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
    if not evidence_ids:
        logger.error(f"Cannot rename photo batch: No photos found in batch {batch_id}")
        await workflow_manager.telegram_client.send_message(
            user_id, 
            "❌ Error: No photos were found in this batch."
        )
        return
    
    # Load the case info
    case_info = workflow_manager.case_manager.load_case(case_id)
    if not case_info:
        logger.error(f"Cannot rename photo batch: Case {case_id} not found")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Error: Case information not found. Please try again later."
        )
        return
    
    # Get the total number of photos in the case
    photo_count = sum(1 for e in case_info.evidence if e.type == "photo")
    
    # Starting index for this batch
    start_index = photo_count - len(evidence_ids) + 1
    
    # Process each photo
    renamed_count = 0
    for i, evidence_id in enumerate(evidence_ids):
        # Find the photo evidence
        photo_evidence = None
        for evidence in case_info.evidence:
            if evidence.evidence_id == evidence_id and evidence.type == "photo":
                photo_evidence = evidence
                break
        
        if not photo_evidence:
            logger.error(f"Cannot rename photo: Evidence {evidence_id} not found or not a photo")
            continue
        
        # Calculate the new photo number
        photo_number = start_index + i
        
        # Generate the new filename
        new_filename = f"photo{photo_number:03d}.jpg"
        
        # Get the old file path and create the new file path
        old_path = Path(photo_evidence.file_path)
        new_path = old_path.parent / new_filename
        
        # Rename the file
        try:
            os.rename(old_path, new_path)
            
            # Update the evidence with the new file path and display order
            workflow_manager.case_manager.update_evidence_metadata(
                case_id, 
                evidence_id, 
                {
                    "file_path": str(new_path),
                    "display_order": photo_number
                }
            )
            
            renamed_count += 1
        except Exception as e:
            logger.error(f"Failed to rename photo {old_path} to {new_path}: {e}")
    
    # Save the case info after all renames
    if workflow_manager.case_manager.save_case(case_info):
        logger.info(f"Successfully renamed {renamed_count}/{len(evidence_ids)} photos in batch {batch_id}")
    
    # Clean up the batch tracking
    if batch_id in workflow_manager.photo_batch_evidence_ids:
        del workflow_manager.photo_batch_evidence_ids[batch_id]
    
    # Show confirmation message with evidence summary
    summary_message = await get_evidence_summary_message(case_info)
    await workflow_manager.telegram_client.send_message(
        user_id,
        f"✅ Successfully processed {renamed_count} photos.\n\n{summary_message}"
    )
    
    # Update the case status message
    await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)

async def _send_batch_summary(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, batch_id: str):
    """Send a batch summary message and start the fingerprint/description collection workflow."""
    # Get total photos in this batch
    evidence_ids = workflow_manager.photo_batch_evidence_ids.get(batch_id, [])
    if not evidence_ids:
        logger.warning(f"No photos found in batch {batch_id} when trying to send summary")
        return

    # Get latest case info
    case_info = workflow_manager.case_manager.load_case(case_id)
    
    # Update the status message with new evidence
    await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
    
    # Create confirmation message
    success_text = f"📷 {len(evidence_ids)} photos added to case. Preparing for description collection..."
    await workflow_manager.telegram_client.send_message(user_id, success_text)
    
    # Start the fingerprint question and description collection process
    await process_photo_batch(workflow_manager, user_id, case_id, batch_id) 