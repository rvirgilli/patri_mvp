import logging
import os
import time
import asyncio
from typing import Optional, List, Dict, TYPE_CHECKING
from collections import defaultdict
from pathlib import Path
import datetime
import uuid
import shutil

from telegram import PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..models.case import CaseInfo, PhotoEvidence
from ..utils.error_handler import NetworkError, TimeoutError, DataError
from .workflow_status import update_case_status_message
from .workflow_evidence_utils import print_debug, media_group_summaries_sent, media_group_timers, get_evidence_summary_message
from ..state_manager import AppState
from ..utils import file_ops

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

BATCH_TIMER_DELAY_SECONDS = 7 # Increased delay to allow more photos to arrive

async def _start_or_queue_batch_processing(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, batch_id: str):
    """Checks if another batch is processing, starts immediately or queues."""
    metadata = workflow_manager.state_manager.get_metadata()
    is_processing = metadata.get('is_processing_photos', False)
    
    if is_processing:
        # Queue this batch
        pending_queue = metadata.get('pending_photo_batch_queue', [])
        if batch_id not in pending_queue:
            pending_queue.append(batch_id)
            workflow_manager.state_manager.set_metadata({'pending_photo_batch_queue': pending_queue})
            print_debug(f"Queueing batch {batch_id} as another batch is processing. Queue size: {len(pending_queue)}")
        else:
            print_debug(f"Batch {batch_id} is already in the pending queue.")
    else:
        # Start processing this batch immediately
        print_debug(f"Starting immediate processing for batch {batch_id}")
        workflow_manager.state_manager.set_metadata({
            'is_processing_photos': True,
            'current_photo_batch_id': batch_id # Track which batch is active
        })
        # Use asyncio.create_task to avoid blocking the main handler
        asyncio.create_task(process_photo_batch(workflow_manager, user_id, case_id, batch_id))

async def handle_photo_message(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, message: Message):
    """Handles a photo message, including media groups and time-based batches."""
    print_debug(f"Handling photo message for case {case_id}")
    
    batch_id = None
    is_batch = False
    create_new_timer = False
    
    # Determine batch ID
    if message.media_group_id:
        batch_id = message.media_group_id
        is_batch = True
        print_debug(f"Photo is part of media group: {batch_id}")
    else:
        # Check for time-based batching
        current_time = time.time()
        last_photo_time = workflow_manager.last_photo_time.get(user_id)
        
        if last_photo_time and (current_time - last_photo_time < 10):
            # Part of an existing or new time-based batch
            is_batch = True
            # Try to find an active time-based batch ID for this user
            # We need a way to associate the current photo with the *ongoing* time batch
            # Let's store the active time batch ID in metadata
            metadata = workflow_manager.state_manager.get_metadata()
            active_time_batch_id = metadata.get(f"active_time_batch_{user_id}")
            
            if active_time_batch_id:
                batch_id = active_time_batch_id
                print_debug(f"Photo added to existing time batch: {batch_id}")
            else:
                # Create a new time batch ID based on the first photo's arrival
                batch_id = f"time_batch_{user_id}_{int(last_photo_time)}" # Use first photo time
                workflow_manager.state_manager.set_metadata({f"active_time_batch_{user_id}": batch_id})
                print_debug(f"Created new time batch: {batch_id}")
        else:
            # Standalone photo or start of a new potential time batch
            is_batch = False # Treat as standalone for now, processing logic will handle batch creation
            # Clear any old active time batch ID for this user
            workflow_manager.state_manager.set_metadata({f"active_time_batch_{user_id}": None})
            print_debug(f"Photo is standalone or starts potential new time batch")

        # Update last photo time regardless
        workflow_manager.last_photo_time[user_id] = current_time

    # --- Batch Timer Logic --- 
    if is_batch and batch_id:
        # Initialize batch tracking if this is the first photo for this ID
        if batch_id not in workflow_manager.photo_batch_evidence_ids:
            workflow_manager.photo_batch_evidence_ids[batch_id] = []
            create_new_timer = True # Need a timer for a new batch
            print_debug(f"Initialized tracking for batch {batch_id}")
        
        # Define the function to be called when the timer expires
        async def finalize_batch():
            finalize_batch_id = batch_id # Capture batch_id at time of definition
            print_debug(f"TIMER EXPIRED for batch {finalize_batch_id}. Finalizing...")
            # Clear the active time batch ID marker if this was a time batch
            if finalize_batch_id.startswith("time_batch_"):
                 workflow_manager.state_manager.set_metadata({f"active_time_batch_{user_id}": None})
                 print_debug(f"Cleared active time batch marker for user {user_id}")
                 
            # Check if batch still exists and has photos
            if finalize_batch_id in workflow_manager.photo_batch_evidence_ids and workflow_manager.photo_batch_evidence_ids[finalize_batch_id]:
                # Only process if the summary hasn't been sent yet
                if finalize_batch_id not in media_group_summaries_sent:
                    print_debug(f"Attempting to start/queue processing for batch {finalize_batch_id} after timer.")
                    media_group_summaries_sent.add(finalize_batch_id) # Mark as ready for processing
                    # Clean up timer reference before queueing/starting
                    media_group_timers.pop(finalize_batch_id, None)
                    # Call the new function to handle queueing or immediate start
                    await _start_or_queue_batch_processing(workflow_manager, user_id, case_id, finalize_batch_id)
                else:
                    print_debug(f"Batch {finalize_batch_id} already processed/queued, skipping finalize.")
            else:
                print_debug(f"Batch {finalize_batch_id} has no photos or was cleared, skipping finalize.")
                media_group_timers.pop(finalize_batch_id, None)
                
        # Cancel any existing timer for this batch ID
        if batch_id in media_group_timers:
            print_debug(f"Cancelling existing timer for batch {batch_id}")
            media_group_timers[batch_id].cancel()
        else:
            # If no existing timer, but batch exists, it means we are adding to it
            if not create_new_timer:
                 print_debug(f"Adding photo to existing batch {batch_id}, will reset timer.")

        # Create and store a NEW timer (resets the timeout)
        print_debug(f"Creating/Resetting timer ({BATCH_TIMER_DELAY_SECONDS}s) for batch {batch_id}")
        media_group_timers[batch_id] = asyncio.create_task(asyncio.sleep(BATCH_TIMER_DELAY_SECONDS), name=f"batch_timer_{batch_id}")
        # Add callback to run finalize_batch when the sleep task completes
        media_group_timers[batch_id].add_done_callback(lambda _: asyncio.create_task(finalize_batch()))

    # --- Process the individual photo --- 
    try:
        # Pass the determined batch_id (even if None)
        evidence_id = await process_photo_evidence(workflow_manager, user_id, case_id, message.photo, batch_id)
        
        if evidence_id:
            if is_batch and batch_id:
                # Add evidence ID to the batch list
                if batch_id in workflow_manager.photo_batch_evidence_ids:
                    workflow_manager.photo_batch_evidence_ids[batch_id].append(evidence_id)
                    print_debug(f"Added evidence {evidence_id} to batch {batch_id}")
                else:
                    # This case should ideally not happen if batch init logic is correct
                    logger.warning(f"Batch {batch_id} not initialized when adding evidence {evidence_id}. Creating now.")
                    workflow_manager.photo_batch_evidence_ids[batch_id] = [evidence_id]
            else:
                # Standalone photo processing
                print_debug(f"Processing standalone photo {evidence_id}")
                
                # Create a one-photo batch and start the description flow immediately
                short_evidence_id = evidence_id[:8]
                single_photo_batch_id = f"sp_{short_evidence_id}"
                workflow_manager.photo_batch_evidence_ids[single_photo_batch_id] = [evidence_id]
                print_debug(f"Created single-photo batch {single_photo_batch_id}")
                
                # Attempt to start/queue processing immediately for single photos
                if single_photo_batch_id not in media_group_summaries_sent:
                     media_group_summaries_sent.add(single_photo_batch_id)
                     await _start_or_queue_batch_processing(workflow_manager, user_id, case_id, single_photo_batch_id)
        else:
             # process_photo_evidence failed and sent a message
             logger.error(f"process_photo_evidence failed for case {case_id}, user {user_id}")
             # No batch timer needed if evidence failed to save

    except (NetworkError, DataError, TimeoutError) as e:
        # Network errors are handled by WorkflowManager.handle_error
        logger.error(f"Error processing photo message for case {case_id}: {e}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error handling photo message: {e}")
        await workflow_manager.telegram_client.send_message(user_id, "An unexpected error occurred while handling the photo.")
        # Consider raising or handling more gracefully

async def process_photo_evidence(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, photo_list: List[PhotoSize], batch_id: Optional[str] = None) -> Optional[str]:
    """Process a photo evidence submission, saving it to a temporary batch location."""
    print_debug(f"ENTER process_photo_evidence for case {case_id}, user {user_id}")
    
    if not photo_list:
        print_debug(f"EXIT process_photo_evidence - No photos provided")
        return None
        
    # Get the largest photo (last in the list)
    photo = photo_list[-1]
    
    # Send processing message only for standalone photos (which have no batch_id at this stage)
    if not batch_id:
        try:
            logger.info(f"Sending 'Processing photo...' message for standalone photo in case {case_id}")
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

        # --- Determine temporary save path --- 
        case_path = workflow_manager.case_manager.get_case_path(case_id)
        # Use batch_id for temp folder name if available, otherwise create a temp ID
        temp_batch_id = batch_id if batch_id else f"temp_standalone_{uuid.uuid4()}"
        temp_dir = case_path / f"temp_batch_{temp_batch_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate a unique temporary filename
        temp_filename = f"{uuid.uuid4()}.jpg"
        temp_photo_path = temp_dir / temp_filename
        print_debug(f"Saving photo temporarily to: {temp_photo_path}")

        # Save photo to temporary location
        if not file_ops.save_evidence_file(photo_data, temp_photo_path):
             logger.error(f"Failed to save photo file temporarily to {temp_photo_path}")
             error_text = "❌ Failed to temporarily save photo evidence. Please try again."
             await workflow_manager.telegram_client.send_message(user_id, error_text)
             print_debug(f"EXIT process_photo_evidence - Temp Save failed")
             return None

        # --- Add evidence pointing to the TEMP path --- 
        print_debug(f"Calling add_photo_evidence (with temp path) for case {case_id}")
        # Note: We still call add_photo_evidence, but it now needs to handle saving the temp path
        # We might need to adjust add_photo_evidence OR create a new method
        # Let's assume for now we create a PhotoEvidence object directly here
        # and add it to the case
        
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Failed to load case {case_id} to add temp photo evidence")
            # Cleanup temp file? Yes.
            try: 
                temp_photo_path.unlink()
            except OSError: 
                pass # Ignore errors during cleanup
            return None

        photo_evidence = PhotoEvidence(
            file_path=str(temp_photo_path), # Store the temporary path
            is_fingerprint=False
        )
        evidence_id = photo_evidence.evidence_id # Get the generated ID
        
        # Set attendance_started timestamp if this is the first evidence
        if not case_info.timestamps.attendance_started:
            case_info.timestamps.attendance_started = datetime.datetime.now()
        
        case_info.evidence.append(photo_evidence)
        
        # Save case info with the evidence pointing to the temp path
        if not workflow_manager.case_manager.save_case(case_info):
            logger.error(f"Failed to save case after adding photo evidence with temp path")
            # Cleanup temp file
            try: 
                temp_photo_path.unlink()
            except OSError: 
                pass # Ignore errors during cleanup
            return None

        # --- Success --- 
        print_debug(f"EXIT process_photo_evidence - Success (ID: {evidence_id}, Temp Path: {temp_photo_path})")
        return evidence_id
            
    except (NetworkError, DataError) as e:
        # Propagate these specific errors to caller
        logger.error(f"Error in photo evidence processing: {e}")
        error_text = f"❌ Error processing photo: {e}. Please try again."
        await workflow_manager.telegram_client.send_message(user_id, error_text)
        print_debug(f"EXIT process_photo_evidence - Network/Data error")
        # Cleanup potentially created temp file if error happened after save attempt
        if 'temp_photo_path' in locals() and temp_photo_path.exists():
            try: 
                temp_photo_path.unlink()
            except OSError: 
                pass # Ignore errors during cleanup
        raise
        
    except Exception as e:
        # Handle other exceptions here but don't propagate them
        logger.exception(f"Unexpected error processing photo evidence: {e}")
        error_text = "❌ Failed to save photo evidence. Please try again."
        await workflow_manager.telegram_client.send_message(user_id, error_text)
        print_debug(f"EXIT process_photo_evidence - Unexpected error")
        # Cleanup potentially created temp file
        if 'temp_photo_path' in locals() and temp_photo_path.exists():
            try: 
                temp_photo_path.unlink()
            except OSError: 
                pass # Ignore errors during cleanup
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
    
    try:
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
        
        # Verify that the evidence IDs actually exist in the case
        valid_evidence_ids = []
        for evidence_id in evidence_ids:
            evidence_exists = any(e.evidence_id == evidence_id and e.type == "photo" for e in case_info.evidence)
            if evidence_exists:
                valid_evidence_ids.append(evidence_id)
            else:
                logger.warning(f"Evidence ID {evidence_id} not found in case {case_id} or is not a photo")
        
        if not valid_evidence_ids:
            logger.error(f"Cannot process photo batch: None of the evidence IDs exist in case {case_id}")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: The photos could not be found in the case. Please try uploading again."
            )
            return
        
        # Update the batch with only valid evidence IDs
        if len(valid_evidence_ids) < len(evidence_ids):
            logger.warning(f"Updating batch {batch_id} with only valid evidence IDs: {len(valid_evidence_ids)} of {len(evidence_ids)}")
            workflow_manager.photo_batch_evidence_ids[batch_id] = valid_evidence_ids
        
        # First, ask if these photos are fingerprints
        # Use a short batch ID in callback data to stay within Telegram's 64-byte limit
        short_batch_id = batch_id[:10] if len(batch_id) > 10 else batch_id
        keyboard = [
            [
                InlineKeyboardButton("Yes, fingerprints", callback_data=f"fp_y_{short_batch_id}"),
                InlineKeyboardButton("No, regular photos", callback_data=f"fp_n_{short_batch_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Store a mapping from short batch ID to full batch ID
        if not hasattr(workflow_manager, 'short_to_full_batch_ids'):
            workflow_manager.short_to_full_batch_ids = {}
        workflow_manager.short_to_full_batch_ids[short_batch_id] = batch_id
        
        await workflow_manager.telegram_client.send_message(
            user_id,
            "🖐 Are these photos of fingerprints?",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.exception(f"Unexpected error in process_photo_batch for case {case_id}, batch {batch_id}: {e}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ An error occurred while processing your photos. Please try again."
        )
    
    # The rest of the process will be handled by the callback query handler

async def handle_photo_batch_fingerprint_response(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, 
                                                 batch_id: str, is_fingerprint: bool):
    """
    Handle the response to the fingerprint question and start collecting descriptions.
    """
    print_debug(f"ENTER handle_photo_batch_fingerprint_response: fingerprints={is_fingerprint}")
    
    try:
        # Check if batch ID exists
        if batch_id not in workflow_manager.photo_batch_evidence_ids:
            logger.error(f"Cannot process fingerprint response: Batch {batch_id} not found")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: Photo batch information was lost. Please try uploading the photos again."
            )
            return
        
        # Get all evidence IDs for this batch
        evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
        if not evidence_ids:
            logger.error(f"Cannot process fingerprint response: No photos found in batch {batch_id}")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: No photos were found in this batch. Please try uploading the photos again."
            )
            return
        
        # Load the case info to get actual evidence items
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Cannot process fingerprint response: Case {case_id} not found")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: Case information not found. Please try again later."
            )
            return
        
        # Filter to only include existing evidence IDs
        valid_evidence_ids = []
        for evidence_id in evidence_ids:
            if any(e.evidence_id == evidence_id and e.type == "photo" for e in case_info.evidence):
                valid_evidence_ids.append(evidence_id)
            else:
                logger.warning(f"Evidence ID {evidence_id} not found in case {case_id} during fingerprint response")
        
        if not valid_evidence_ids:
            logger.error(f"Cannot process fingerprint response: None of the evidence IDs exist in case {case_id}")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: The photos could not be found in the case. Please try uploading again."
            )
            return
        
        # Update batch with only valid evidence
        if len(valid_evidence_ids) < len(evidence_ids):
            workflow_manager.photo_batch_evidence_ids[batch_id] = valid_evidence_ids
            evidence_ids = valid_evidence_ids
        
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
    except Exception as e:
        logger.exception(f"Unexpected error in handle_photo_batch_fingerprint_response: {e}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ An error occurred while processing your response. Please try again later."
        )

async def request_photo_description(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, 
                                   batch_id: str, index: int):
    """
    Request description for a specific photo in the batch.
    """
    print_debug(f"ENTER request_photo_description for index {index}")
    
    try:
        # Validate batch_id
        if batch_id not in workflow_manager.photo_batch_evidence_ids:
            logger.error(f"Cannot request photo description: Batch {batch_id} not found")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: Photo batch information was lost. Please try uploading the photos again."
            )
            return
            
        # Get all evidence IDs for this batch
        evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
        if not evidence_ids:
            logger.error(f"Cannot request photo description: No photos found in batch {batch_id}")
            await workflow_manager.telegram_client.send_message(
                user_id, 
                "❌ Error: No photos were found in this batch. Please try uploading the photos again."
            )
            return
        
        # Check if the index is valid
        if index < 0 or index >= len(evidence_ids):
            logger.error(f"Invalid photo index {index} for batch {batch_id} with {len(evidence_ids)} photos")
            # If index is out of range but >= len, we've reached the end
            if index >= len(evidence_ids):
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    "✅ All photo descriptions collected. Processing..."
                )
                await rename_photo_batch(workflow_manager, user_id, case_id, batch_id)
            return
            
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
        # Use only first 8 chars of evidence_id to keep callback data short
        short_evidence_id = evidence_id[:8] if evidence_id else ""
        keyboard = [
            [
                InlineKeyboardButton("🗑️ Delete this photo", callback_data=f"del_p_{short_evidence_id}_{index}")
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
    except Exception as e:
        logger.exception(f"Unexpected error in request_photo_description for index {index}: {e}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ An error occurred while processing your photos. Please try again later."
        )
        # Clear any metadata about awaiting photo description
        workflow_manager.state_manager.set_metadata({
            "awaiting_photo_description": False,
            "photo_description_batch_id": None,
            "photo_description_index": None,
            "photo_description_evidence_id": None
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
            
            # --- Check for and trigger next queued batch --- 
            metadata = workflow_manager.state_manager.get_metadata()
            pending_queue = metadata.get('pending_photo_batch_queue', [])
            
            if pending_queue:
                next_batch_id = pending_queue.pop(0) # Get the next batch from the queue
                print_debug(f"DELETE_PHOTO: Processing next queued batch: {next_batch_id}. Queue size: {len(pending_queue)}")
                # Update metadata: Set new current batch, keep processing flag true, save queue
                workflow_manager.state_manager.set_metadata({
                    'pending_photo_batch_queue': pending_queue,
                    'is_processing_photos': True, 
                    'current_photo_batch_id': next_batch_id
                })
                # Start processing the next batch asynchronously
                asyncio.create_task(process_photo_batch(workflow_manager, user_id, case_id, next_batch_id))
            else:
                # No more queued batches, clear the processing flag
                print_debug("DELETE_PHOTO: No more photo batches in queue. Clearing processing flag.")
                workflow_manager.state_manager.set_metadata({
                    'is_processing_photos': False,
                    'current_photo_batch_id': None,
                    'pending_photo_batch_queue': [] # Ensure queue is cleared
                })
             # --- End Queue Check ---
             
    else:
        logger.error(f"Failed to save case after deleting photo evidence {evidence_id}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Failed to delete photo. Please try again."
        )

async def rename_photo_batch(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, batch_id: str):
    """
    Finalizes a photo batch: Moves photos from temporary location to the final
    directory, renames them sequentially, updates metadata, saves the case,
    and cleans up the temporary directory.
    """
    print_debug(f"ENTER rename_photo_batch for batch {batch_id}")
    
    temp_batch_path = None # Initialize
    final_photos_path = None # Initialize
    
    try:
        # Get all evidence IDs for this batch
        if batch_id not in workflow_manager.photo_batch_evidence_ids:
            logger.error(f"Cannot process photo batch: Batch {batch_id} not found for rename/commit.")
            # Send error? This might happen if processed concurrently, maybe just log warning.
            return

        evidence_ids = workflow_manager.photo_batch_evidence_ids[batch_id]
        if not evidence_ids:
            logger.warning(f"Cannot rename photo batch: No photos found in batch {batch_id}")
            # No photos to process, just clean up tracking
            if batch_id in workflow_manager.photo_batch_evidence_ids:
                del workflow_manager.photo_batch_evidence_ids[batch_id]
            return
        
        # Load the case info
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Cannot rename photo batch: Case {case_id} not found")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "❌ Error: Case information not found. Cannot finalize photos."
            )
            return

        # Determine paths
        case_path = workflow_manager.case_manager.get_case_path(case_id)
        # Assume temp path format used in process_photo_evidence
        # Need to handle potential standalone temp IDs too
        temp_batch_id = batch_id # Use the original batch_id for the temp folder name
        temp_batch_path = case_path / f"temp_batch_{temp_batch_id}"
        final_photos_path = case_path / "photos"
        final_photos_path.mkdir(parents=True, exist_ok=True) # Ensure final photos dir exists
        
        # --- Verify evidence IDs and paths before processing --- 
        valid_evidence_items = []
        actual_evidence_ids_in_batch = []
        for evidence_id in evidence_ids:
            found = False
            for evidence in case_info.evidence:
                if evidence.evidence_id == evidence_id and evidence.type == "photo":
                    # Check if the file path seems to be in the expected temp location
                    if str(temp_batch_path) in evidence.file_path:
                        valid_evidence_items.append(evidence) 
                        actual_evidence_ids_in_batch.append(evidence_id)
                        found = True
                        break
                    else:
                        logger.warning(f"Evidence {evidence_id} path {evidence.file_path} not in expected temp dir {temp_batch_path}. Skipping.")
                        break # Don't add this evidence item
            if not found:
                 logger.warning(f"Evidence {evidence_id} from batch {batch_id} not found in case or not a photo. Skipping.")
        
        if not valid_evidence_items:
            logger.error(f"Cannot rename photo batch: None of the evidence IDs from batch {batch_id} were found in the case with valid temp paths.")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "❌ Error: The photos for this batch could not be found or were corrupted. Please try uploading again."
            )
            # Clean up batch tracking even on failure here
            if batch_id in workflow_manager.photo_batch_evidence_ids:
                del workflow_manager.photo_batch_evidence_ids[batch_id]
            return
        
        # Use only the verified items and IDs from now on
        evidence_ids_to_process = actual_evidence_ids_in_batch
        
        # --- Calculate numbering --- 
        # Get the count of *already finalized* photos to determine starting index
        existing_photo_count = sum(
            1 for e in case_info.evidence 
            if e.type == "photo" and e.display_order is not None and final_photos_path.name in e.file_path
        )
        start_index = existing_photo_count + 1
        print_debug(f"RENAME_BATCH: Starting photo numbering at {start_index}")

        # --- Process each photo: Move, Update Metadata in Memory --- 
        processed_count = 0
        processing_errors = 0
        temp_paths_to_clean = set() # Keep track of temp paths processed
        
        for i, evidence_id in enumerate(evidence_ids_to_process):
            photo_evidence = next((e for e in valid_evidence_items if e.evidence_id == evidence_id), None)
            if not photo_evidence:
                # Should not happen due to pre-filtering, but safety check
                logger.error(f"Consistency Error: Evidence {evidence_id} missing during loop.")
                processing_errors += 1
                continue

            temp_path = Path(photo_evidence.file_path)
            temp_paths_to_clean.add(str(temp_path))
            photo_number = start_index + i
            new_filename = f"photo{photo_number:03d}.jpg"
            final_path = final_photos_path / new_filename
            
            try:
                # 1. Move file
                if not temp_path.exists():
                    logger.error(f"Cannot move photo: Temp file {temp_path} does not exist.")
                    processing_errors += 1
                    continue
                
                print_debug(f"RENAME_BATCH: Moving {temp_path} -> {final_path}")
                shutil.move(str(temp_path), str(final_path))
                print_debug(f"RENAME_BATCH: Move successful.")
                
                # 2. Update evidence object IN MEMORY (will be saved later)
                print_debug(f"RENAME_BATCH: Updating metadata in memory for evidence {evidence_id}")
                photo_evidence.file_path = str(final_path)
                photo_evidence.display_order = photo_number
                # We don't call update_evidence_metadata here anymore, we modify the loaded case_info directly
                print_debug(f"RENAME_BATCH: Metadata updated in memory: path={final_path}, order={photo_number}")
                processed_count += 1
                
            except OSError as e:
                logger.error(f"Failed to move photo {temp_path} to {final_path}: {e}")
                print_debug(f"RENAME_BATCH: Move FAILED for {temp_path}: {e}")
                processing_errors += 1
            except Exception as e:
                logger.exception(f"Unexpected error processing photo {temp_path}: {e}")
                print_debug(f"RENAME_BATCH: UNEXPECTED error for {temp_path}: {e}")
                processing_errors += 1
        
        # --- Final Save Attempt --- 
        save_successful = False
        if processing_errors == 0:
            print_debug(f"RENAME_BATCH: Attempting to save case {case_id} after processing batch {batch_id}")
            save_successful = workflow_manager.case_manager.save_case(case_info)
            print_debug(f"RENAME_BATCH: Save case result: {save_successful}")
        else:
            logger.error(f"RENAME_BATCH: Skipping final save for case {case_id} due to {processing_errors} errors during photo processing in batch {batch_id}.")

        # --- Cleanup and Confirmation --- 
        if save_successful:
            logger.info(f"Successfully processed and saved {processed_count}/{len(evidence_ids_to_process)} photos in batch {batch_id} for case {case_id}.")
            # Cleanup temp directory only on full success
            if temp_batch_path and temp_batch_path.exists():
                print_debug(f"RENAME_BATCH: Cleaning up temporary directory {temp_batch_path}")
                try:
                    shutil.rmtree(temp_batch_path)
                    print_debug(f"RENAME_BATCH: Temporary directory deleted.")
                except Exception as e:
                    logger.error(f"Failed to delete temporary directory {temp_batch_path}: {e}")
        else:
            logger.error(f"FAILED TO SAVE case {case_id} after processing batch {batch_id}. Processed {processed_count} photos with {processing_errors} errors. Temporary files *not* cleaned up: {temp_batch_path}")
            # Do not clean up temp dir if save failed or there were errors

        # Clean up the main batch tracking ID
        if batch_id in workflow_manager.photo_batch_evidence_ids:
            del workflow_manager.photo_batch_evidence_ids[batch_id]
            print_debug(f"Removed batch ID {batch_id} from tracking.")
        
        # Use the potentially updated in-memory case_info for the summary
        # Only reload from disk if the save failed, otherwise use the version we tried to save.
        summary_case_info = case_info if save_successful else workflow_manager.case_manager.load_case(case_id)
        if not summary_case_info:
             # Fallback if reload also fails
             summary_case_info = case_info 
             
        summary_message = await get_evidence_summary_message(summary_case_info)
        
        if processing_errors > 0 or not save_successful:
            await workflow_manager.telegram_client.send_message(
                user_id,
                f"⚠️ Finished processing photo batch, but encountered errors. Processed {processed_count} photos, {processing_errors} errors occurred. Case save status: {save_successful}. Please check logs. \n\n{summary_message}"
            )
        else:
            await workflow_manager.telegram_client.send_message(
                user_id,
                f"✅ Successfully processed {processed_count} photos.\n\n{summary_message}"
            )
        
        # Update the main status message using the same case_info object
        await update_case_status_message(workflow_manager, user_id, case_id, case_info=summary_case_info)
        
        # --- Check for and trigger next queued batch --- 
        metadata = workflow_manager.state_manager.get_metadata()
        pending_queue = metadata.get('pending_photo_batch_queue', [])
        
        if pending_queue:
            next_batch_id = pending_queue.pop(0) # Get the next batch from the queue
            print_debug(f"Processing next queued batch: {next_batch_id}. Queue size: {len(pending_queue)}")
            # Update metadata: Set new current batch, keep processing flag true, save queue
            workflow_manager.state_manager.set_metadata({
                'pending_photo_batch_queue': pending_queue,
                'is_processing_photos': True, 
                'current_photo_batch_id': next_batch_id
            })
            # Start processing the next batch asynchronously
            asyncio.create_task(process_photo_batch(workflow_manager, user_id, case_id, next_batch_id))
        else:
            # No more queued batches, clear the processing flag
            print_debug("No more photo batches in queue. Clearing processing flag.")
            workflow_manager.state_manager.set_metadata({
                'is_processing_photos': False,
                'current_photo_batch_id': None,
                'pending_photo_batch_queue': [] # Ensure queue is cleared
            })
        # --- End Queue Check ---
        
    except Exception as e:
        logger.exception(f"Unexpected error in rename_photo_batch for batch {batch_id}: {e}")
        # --- Ensure processing flag is cleared on unexpected error --- 
        try:
            workflow_manager.state_manager.set_metadata({
                'is_processing_photos': False,
                'current_photo_batch_id': None,
                # Keep pending queue as is, maybe retry later? For now, clear it.
                 'pending_photo_batch_queue': [] 
            })
            logger.warning(f"Cleared photo processing flag due to unexpected error in rename_photo_batch for batch {batch_id}")
        except Exception as meta_e:
            logger.error(f"Failed to clear metadata flags after error in rename_photo_batch: {meta_e}")
        # --- End Flag Cleanup --- 
        
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ An error occurred while finalizing your photos. Some photos may not have been properly saved or renamed. Please check logs."
        )
        # Attempt cleanup of batch tracking ID even on outer exception
        if batch_id in workflow_manager.photo_batch_evidence_ids:
            del workflow_manager.photo_batch_evidence_ids[batch_id]
        # Do not cleanup temp folder on outer error

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