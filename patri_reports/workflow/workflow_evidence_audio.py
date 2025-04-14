import logging
import tempfile
import os
from typing import Optional, Dict, TYPE_CHECKING
import datetime
import uuid

from telegram import Voice, Message
from ..utils.error_handler import NetworkError, TimeoutError, DataError
from .workflow_status import update_case_status_message
from .workflow_evidence_utils import print_debug, _safe_update_message, get_evidence_summary_message
from ..api.whisper import TranscriptionError, TransientError, PermanentError
from ..utils import file_ops

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

async def handle_voice_message(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, message: Message):
    """Handle a voice message, either as evidence or as a photo description."""
    print_debug(f"Handling voice message for {case_id}")
    
    # Check if we're waiting for a photo description
    metadata = workflow_manager.state_manager.get_metadata()
    if metadata.get("awaiting_photo_description"):
        await handle_voice_photo_description(workflow_manager, user_id, case_id, message)
    else:
        await handle_voice_evidence(workflow_manager, user_id, case_id, message)

async def handle_voice_photo_description(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, message: Message):
    """Process voice message as a photo description."""
    # This is an audio description for a photo, process it differently
    # First we'll get the transcript
    processing_msg = await workflow_manager.telegram_client.send_message(
        user_id, 
        "Transcribing audio description..."
    )
    
    try:
        # Download voice file
        audio_data, error_message = await workflow_manager.telegram_client.download_file(message.voice.file_id)
        
        if error_message or not audio_data:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=processing_msg.message_id,
                text=f"❌ Failed to download audio: {error_message or 'Unknown error'}. Please try again with text."
            )
            return
        
        # Transcribe the audio
        temp_filename = None
        transcript = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_filename = temp_file.name
            
            # Call WhisperAPI for transcription - fix for the await issue
            language = "pt"  # Use Portuguese for transcription
            transcript = workflow_manager.whisper_api.transcribe(
                temp_filename,
                language=language
            )
            
            if not transcript:
                await workflow_manager.telegram_client.edit_message_text(
                    chat_id=user_id,
                    message_id=processing_msg.message_id,
                    text="❌ Failed to transcribe audio. Please try again with text."
                )
                return
                
            # Use the transcript as the photo description
            await handle_photo_description(
                workflow_manager,
                user_id,
                case_id,
                transcript,
                is_audio=True,
                audio_file_id=message.voice.file_id
            )
            
        except (TranscriptionError, TransientError, PermanentError) as e:
            logger.error(f"Transcription error for photo description: {e}")
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=processing_msg.message_id,
                text=f"❌ Failed to transcribe audio: {str(e)}. Please try again with text."
            )
            return
            
        finally:
            # Clean up temp file
            if temp_filename and os.path.exists(temp_filename):
                try:
                    os.unlink(temp_filename)
                except Exception as e:
                    logger.error(f"Failed to delete temp file {temp_filename}: {e}")
                
    except Exception as e:
        logger.exception(f"Error processing voice description: {e}")
        await workflow_manager.telegram_client.edit_message_text(
            chat_id=user_id,
            message_id=processing_msg.message_id,
            text="❌ Error processing audio description. Please try again with text."
        )
        return

async def handle_voice_evidence(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, message: Message):
    """Process voice message as general audio evidence."""
    # Regular voice message processing for evidence
    processing_msg = await workflow_manager.telegram_client.send_message(user_id, "Processing audio and transcribing...")
    
    try:
        # Download voice file
        audio_data, error_message = await workflow_manager.telegram_client.download_file(message.voice.file_id)
        
        if error_message or not audio_data:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=processing_msg.message_id,
                text=f"❌ Failed to download audio: {error_message or 'Unknown error'}. Please try again."
            )
            print_debug(f"EXIT handle_voice_evidence - voice download failure")
            return
        
        # Create a temp file path for transcription
        temp_filename = None
        transcript = None
        
        # Save to temporary file for whisper API
        try:
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_filename = temp_file.name
            
            # Call WhisperAPI for transcription
            logger.info(f"Transcribing audio file for case {case_id}")
            
            # Always use Portuguese (Brazil) for transcription
            language = "pt"
            logger.info(f"Using Brazilian Portuguese for transcription in case {case_id}")
            
            # Transcribe with Portuguese language - fix for the await issue
            logger.info(f"Calling whisper API for file {temp_filename}")
            transcript = workflow_manager.whisper_api.transcribe(temp_filename, language=language)
            logger.info(f"Transcription result: {transcript is not None}")
            
            # Update the processing message with transcript status
            if transcript:
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    processing_msg.message_id,
                    f"Processing audio... Transcription: \"{transcript}\""
                )
            else:
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    processing_msg.message_id,
                    "Processing audio... (Transcription failed)"
                )
        
        except (TranscriptionError, TransientError) as e:
            # Handle temporary transcription errors but continue with audio evidence
            logger.warning(f"Transcription error (recoverable): {e}")
            await _safe_update_message(
                workflow_manager,
                user_id,
                processing_msg.message_id,
                f"Processing audio... (Transcription issue: {str(e)}, continuing anyway)"
            )
            # Continue with adding audio evidence even with transcription issues
        
        except PermanentError as e:
            # Handle permanent transcription errors but continue with audio evidence
            logger.error(f"Permanent transcription error: {e}")
            await _safe_update_message(
                workflow_manager,
                user_id,
                processing_msg.message_id,
                "Processing audio... (Transcription unavailable, continuing anyway)"
            )
            # Continue with adding audio evidence even if transcription fails
        
        except Exception as e:
            logger.exception(f"Transcription error: {e}")
            await _safe_update_message(
                workflow_manager,
                user_id,
                processing_msg.message_id,
                "Processing audio... (Transcription error, continuing anyway)"
            )
            # Continue with adding audio evidence even if transcription fails
        
        finally:
            # Clean up temp file
            if temp_filename and os.path.exists(temp_filename):
                try:
                    os.unlink(temp_filename)
                except Exception as file_e:
                    logger.error(f"Failed to delete temp file {temp_filename}: {file_e}")
        
        # Add audio evidence
        logger.info(f"Adding audio evidence for case {case_id}")
        
        # Get duration from the message (but don't pass if not supported by function)
        # Fix for the duration_seconds parameter issue
        evidence_id = workflow_manager.case_manager.add_audio_evidence(
            case_id,
            audio_data,
            transcript=transcript
        )
        
        if evidence_id:
            # Show success message
            await _safe_update_message(
                workflow_manager,
                user_id, 
                processing_msg.message_id,
                "✅ Voice recording added to evidence."
            )
            
            # Reload case info and update status message
            case_info = workflow_manager.case_manager.load_case(case_id)
            await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
            
            # Show the evidence summary with the new counts
            summary_message = await get_evidence_summary_message(case_info)
            await workflow_manager.telegram_client.send_message(
                user_id,
                f"✅ Voice recording added to evidence.\n\n{summary_message}"
            )
        else:
            await _safe_update_message(
                workflow_manager,
                user_id,
                processing_msg.message_id,
                "❌ Failed to save audio file. Please try again."
            )
            
    except (NetworkError, DataError, TimeoutError) as e:
        # Network errors are handled by WorkflowManager.handle_error
        logger.error(f"Error processing voice message for case {case_id}: {e}")
        await _safe_update_message(
            workflow_manager,
            user_id,
            processing_msg.message_id,
            f"❌ Error: {e}"
        )
        raise
    
    except Exception as e:
        logger.exception(f"Unexpected error processing voice: {e}")
        await _safe_update_message(
            workflow_manager,
            user_id,
            processing_msg.message_id,
            "❌ Unexpected error processing voice message."
        )

async def handle_photo_description(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, 
                                  description: str, is_audio: bool = False, audio_file_id: Optional[str] = None):
    """
    Handle the user's response for a photo description.
    
    Args:
        workflow_manager: The workflow manager instance
        user_id: The user's Telegram ID
        case_id: The case ID
        description: The text description
        is_audio: Whether the description is from an audio message
        audio_file_id: The audio file ID if is_audio is True
    """
    print_debug(f"ENTER handle_photo_description")
    
    # Get the current state
    metadata = workflow_manager.state_manager.get_metadata()
    if not metadata.get("awaiting_photo_description"):
        # Not waiting for a description, ignore
        logger.warning(f"Received photo description when not awaiting one: {description[:30]}...")
        return
    
    batch_id = metadata.get("photo_description_batch_id")
    index = metadata.get("photo_description_index")
    evidence_id = metadata.get("photo_description_evidence_id")
    
    if not all([batch_id, index is not None, evidence_id]):
        logger.error(f"Missing photo description metadata: {metadata}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Error: Lost track of which photo you're describing. Please try again."
        )
        return
    
    # Prepare the metadata update for the photo evidence
    evidence_metadata = {"description": description}
    
    # If there's an audio file, download and save it
    audio_file_path = None
    if is_audio and audio_file_id:
        try:
            audio_data, error_message = await workflow_manager.telegram_client.download_file(audio_file_id)
            if audio_data and not error_message:
                # Save the audio file in the audio directory
                case_info = workflow_manager.case_manager.load_case(case_id)
                case_path = workflow_manager.case_manager.get_case_path(case_id, case_info.case_year)
                audio_dir = case_path / "audio"
                audio_filename = f"photo_desc_{evidence_id[-8:]}_{uuid.uuid4()}.ogg"
                audio_path = audio_dir / audio_filename
                
                # Save the audio file
                if file_ops.save_evidence_file(audio_data, audio_path):
                    # Add the audio file path to the photo evidence metadata
                    evidence_metadata["audio_file_path"] = str(audio_path)
                else:
                    logger.error(f"Failed to save audio description file for photo {evidence_id}")
        except Exception as e:
            logger.error(f"Failed to save audio description: {e}")
    
    # Update the photo evidence with the description and optional audio path
    if workflow_manager.case_manager.update_evidence_metadata(
        case_id, 
        evidence_id, 
        evidence_metadata
    ):
        # Clear the awaiting_photo_description state
        workflow_manager.state_manager.set_metadata({
            "awaiting_photo_description": False,
            "photo_description_batch_id": None,
            "photo_description_index": None,
            "photo_description_evidence_id": None
        })
        
        # Move to the next photo
        from .workflow_evidence_photo import request_photo_description
        await request_photo_description(workflow_manager, user_id, case_id, batch_id, index + 1)
    else:
        logger.error(f"Failed to update photo description for evidence {evidence_id}")
        await workflow_manager.telegram_client.send_message(
            user_id,
            "❌ Failed to save description. Please try again."
        ) 