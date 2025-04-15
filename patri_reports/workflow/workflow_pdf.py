import logging
from typing import Optional, TYPE_CHECKING
from pathlib import Path
import os
import time
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..state_manager import AppState
from ..utils.error_handler import NetworkError, TimeoutError, DataError
from .workflow_utils import _safe_update_message

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

async def start_new_case_workflow(workflow_manager: 'WorkflowManager', user_id: int, message_id_to_edit: Optional[int] = None):
    """Transitions to the WAITING_FOR_PDF state and prompts user to upload a PDF."""
    if not workflow_manager.telegram_client:
        return
        
    logger.info(f"Transitioning user {user_id} to WAITING_FOR_PDF state.")
    
    # Set state to waiting for PDF (automatically clears any case_id)
    if workflow_manager.state_manager.set_state(AppState.WAITING_FOR_PDF):
        # Successfully transitioned
        logger.info(f"Transitioned user {user_id} to WAITING_FOR_PDF state.")
        
        prompt_text = "📄 Please send the occurrence PDF report for the new case."
        buttons = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_case")]]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Always send a new message for better visibility in the chat
        if message_id_to_edit:
            # First acknowledge the button click by editing the original message
            try:
                await workflow_manager.telegram_client.edit_message_text(
                    chat_id=user_id, 
                    message_id=message_id_to_edit,
                    text="Starting new case...",
                    reply_markup=None
                )
            except Exception as e:
                logger.warning(f"Failed to edit message {message_id_to_edit}: {e}")
        
        # Then send a new message with the prompt
        await workflow_manager.telegram_client.send_message(user_id, prompt_text, reply_markup=reply_markup)
    else:
        logger.error(f"Failed to transition user {user_id} state to WAITING_FOR_PDF.")
        await workflow_manager.telegram_client.send_message(user_id, "Could not start the new case process. Please try again.")
        from .workflow_idle import show_idle_menu
        await show_idle_menu(workflow_manager, user_id) # Reshow menu

async def handle_waiting_for_pdf_state(workflow_manager: 'WorkflowManager', update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Handles updates when the application is waiting for a PDF."""
    if not workflow_manager.telegram_client:
        return # Should not happen if initialized correctly
        
    logger.debug(f"Handling WAITING_FOR_PDF state for user {user_id}")
    query = update.callback_query
    message = update.message

    if query:
        await query.answer() # Acknowledge button press
        if query.data == "cancel_new_case":
            logger.info(f"User {user_id} cancelled new case initiation.")
            # Transition back to IDLE (set_state handles clearing case_id)
            if workflow_manager.state_manager.set_state(AppState.IDLE):
                await workflow_manager.telegram_client.edit_message_text(
                    chat_id=user_id,
                    message_id=query.message.message_id,
                    text="Cancelled. Returning to main menu.",
                    reply_markup=None
                )
                from .workflow_idle import show_idle_menu
                await show_idle_menu(workflow_manager, user_id)
        elif query.data == "cancel_pdf_upload":
            logger.info(f"User {user_id} cancelled PDF upload for existing case.")
            # Clean up any temporary data
            if hasattr(workflow_manager.state_manager, 'custom_data'):
                temp_key = f"temp_pdf_{user_id}"
                if temp_key in workflow_manager.state_manager.custom_data:
                    del workflow_manager.state_manager.custom_data[temp_key]
            
            # Return to IDLE state
            if workflow_manager.state_manager.set_state(AppState.IDLE):
                await workflow_manager.telegram_client.edit_message_text(
                    chat_id=user_id,
                    message_id=query.message.message_id,
                    text="Cancelled. Returning to main menu.",
                    reply_markup=None
                )
                from .workflow_idle import show_idle_menu
                await show_idle_menu(workflow_manager, user_id)
        elif query.data.startswith("continue_"):
            # Extract case ID from callback data
            case_id = query.data.replace("continue_", "")
            logger.info(f"User {user_id} chose to continue evidence collection for case {case_id}")
            
            # Update the message
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=query.message.message_id,
                text=f"Continuing evidence collection for existing case.",
                reply_markup=None
            )
            
            # Clean up any temporary data
            if hasattr(workflow_manager.state_manager, 'custom_data'):
                temp_key = f"temp_pdf_{user_id}"
                if temp_key in workflow_manager.state_manager.custom_data:
                    del workflow_manager.state_manager.custom_data[temp_key]
            
            # Set state to evidence collection with the existing case ID
            workflow_manager.state_manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id=case_id)
            
            # Get case info to send status
            case_info = workflow_manager.case_manager.load_case(case_id)
            
            # Create/update status message
            try:
                from .workflow_status import create_case_status_message
                await create_case_status_message(workflow_manager, user_id, case_id)
            except Exception as e:
                logger.warning(f"Failed to create/update status message: {e}")
            
            # Prompt for evidence collection
            try:
                from .workflow_evidence import send_evidence_prompt
                await send_evidence_prompt(workflow_manager, user_id, case_id)
            except Exception as e:
                logger.error(f"Failed to send evidence prompt: {e}")
                await workflow_manager.telegram_client.send_message(
                    user_id, 
                    "✅ Continuing with existing case. You can now send evidence."
                )
                
        elif query.data.startswith("overwrite_"):
            # Extract case ID from callback data
            case_id = query.data.replace("overwrite_", "")
            logger.info(f"User {user_id} chose to overwrite case {case_id}")
            
            # Update the message to indicate processing
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=query.message.message_id,
                text=f"Overwriting existing case, please wait...",
                reply_markup=None
            )
            
            # Get the stored temporary data
            temp_data = None
            if hasattr(workflow_manager.state_manager, 'custom_data'):
                temp_key = f"temp_pdf_{user_id}"
                if temp_key in workflow_manager.state_manager.custom_data:
                    temp_data = workflow_manager.state_manager.custom_data[temp_key]
                    del workflow_manager.state_manager.custom_data[temp_key]
            
            if not temp_data:
                logger.error(f"No temporary PDF data found for case {case_id}")
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    "❌ Error: Could not find PDF data. Please try uploading again."
                )
                return
            
            # Delete the existing case
            try:
                result = workflow_manager.case_manager.delete_case(case_id)
                if not result:
                    logger.warning(f"Failed to delete case {case_id}, but continuing with new upload")
            except Exception as e:
                logger.error(f"Error deleting case {case_id}: {e}")
            
            # Re-upload the PDF to create a new case
            pdf_file = temp_data.get("pdf_file")
            if pdf_file:
                # Process the PDF again, which will create a new case
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    "🔄 Processing PDF to create a new case..."
                )
                await process_pdf_input(workflow_manager, user_id, pdf_file, query.message.message_id)
            else:
                logger.error("Missing PDF file in temporary data")
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    "❌ Error: Missing PDF data. Please try uploading again."
                )
                from .workflow_idle import show_idle_menu
                await show_idle_menu(workflow_manager, user_id)
        elif query.data == "start_new_case":
            # User is trying to start a new case while already in WAITING_FOR_PDF
            # This could happen if multiple menus are displayed or state is inconsistent
            logger.warning(f"User {user_id} clicked 'Start New Case' while already in WAITING_FOR_PDF state - handling gracefully")
            # Show a message and re-prompt for PDF
            prompt_text = "📄 Please send the occurrence PDF report for the new case."
            buttons = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_case")]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await workflow_manager.telegram_client.send_message(user_id, prompt_text, reply_markup=reply_markup)
        else:
            logger.warning(f"Received unexpected callback data in WAITING_FOR_PDF state: {query.data}")
            await workflow_manager.telegram_client.send_message(user_id, "Invalid action while waiting for PDF.")

    elif message and message.document and message.document.mime_type == 'application/pdf':
        logger.info(f"User {user_id} submitted a PDF document.")
        pdf_file = message.document
        await process_pdf_input(workflow_manager, user_id, pdf_file, message.message_id)

    elif message:
        # Send a single reminder message instead of potentially duplicating
        logger.debug(f"Received non-PDF message from user {user_id} in WAITING_FOR_PDF state.")
        await workflow_manager.telegram_client.send_message(user_id, "Please send a PDF file or click Cancel.")

async def process_pdf_input(workflow_manager: 'WorkflowManager', user_id: int, pdf_file, message_id: int):
    """Process an uploaded PDF file to create a new case."""
    
    if not workflow_manager.telegram_client:
        logger.error("TelegramClient not set in process_pdf_input")
        return

    status_message_id = None
    case_id = None
    temp_pdf_path = None
    
    try:
        # Send initial processing message
        try:
            processing_message = await workflow_manager.telegram_client.send_message(
                user_id,
                "📄 Processing your PDF... This may take a moment."
            )
            
            # Check if processing_message was successfully sent
            if processing_message:
                status_message_id = processing_message.message_id
            else:
                logger.warning("Failed to send processing message, but continuing PDF processing")
        except Exception as e:
            logger.warning(f"Failed to send processing message: {e}, but continuing PDF processing")
        
        # Download the PDF
        logger.info(f"Downloading PDF (file_id: {pdf_file.file_id}, name: {pdf_file.file_name})")
        
        # Safe message update - either edit existing or send new
        await _safe_update_message(
            workflow_manager,
            user_id, 
            status_message_id, 
            "📥 Downloading PDF file..."
        )
        
        # Use the updated download method which returns tuple (content, error)
        file_content, error_message = await workflow_manager.telegram_client.download_file(pdf_file.file_id)
        
        if error_message or not file_content:
            logger.error(f"Failed to download PDF: {error_message}")
            await _safe_update_message(
                workflow_manager,
                user_id,
                status_message_id,
                f"❌ Error downloading PDF: {error_message or 'Unknown error'}\n\nPlease try again or upload a different file."
            )
            return
        
        # Update status after download
        await _safe_update_message(
            workflow_manager,
            user_id,
            status_message_id,
            f"✅ PDF downloaded ({len(file_content)/1024:.1f} KB)\n Analyzing document..."
        )
        
        # Create a temporary directory and save PDF there
        import tempfile
        import shutil
        import os
        from pathlib import Path
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="pdf_analysis_")
        temp_pdf_path = Path(temp_dir) / "temp_document.pdf"
        
        # Save PDF to temp location
        try:
            with open(temp_pdf_path, 'wb') as f:
                f.write(file_content)
            logger.info(f"Saved temporary PDF to {temp_pdf_path}")
        except Exception as e:
            logger.error(f"Failed to save temporary PDF: {e}")
            await _safe_update_message(
                workflow_manager,
                user_id,
                status_message_id,
                "❌ Failed to save your PDF. Please try again later."
            )
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        # Check if PDF is valid/not corrupted
        if workflow_manager.case_manager.is_pdf_corrupted(temp_pdf_path):
            logger.error(f"Corrupted or invalid PDF detected")
            await _safe_update_message(
                workflow_manager,
                user_id,
                status_message_id,
                "❌ The PDF file appears to be corrupted or invalid. Please upload a valid PDF document."
            )
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        # Process the PDF and extract metadata
        await _safe_update_message(
            workflow_manager,
            user_id,
            status_message_id,
            "🔍 Extracting information from PDF..."
        )
        
        # Extract text and metadata from the temporary PDF
        try:
            # Extract PDF info without creating a case yet
            extracted_info = workflow_manager.case_manager.extract_pdf_info(temp_pdf_path)
            
            if not extracted_info:
                logger.error("Failed to extract PDF information")
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    status_message_id,
                    "❌ Failed to extract information from the PDF. Please ensure it contains readable text."
                )
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
                
            # Check if we have case_number, report_number, and case_year in extracted_info
            if isinstance(extracted_info, dict):
                case_number = extracted_info.get("case_number")
                report_number = extracted_info.get("report_number")
                case_year = extracted_info.get("case_year")
                has_case_data = case_number and report_number and case_year
            else:
                # Try to access attributes
                has_case_data = (hasattr(extracted_info, "case_number") and 
                                hasattr(extracted_info, "report_number") and 
                                hasattr(extracted_info, "case_year") and 
                                extracted_info.case_number and 
                                extracted_info.report_number and 
                                extracted_info.case_year)
                if has_case_data:
                    case_number = extracted_info.case_number
                    report_number = extracted_info.report_number
                    case_year = extracted_info.case_year
            
            # Generate proper case ID from extracted data
            if not has_case_data:
                logger.error("Could not extract essential case information from PDF")
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    status_message_id,
                    "❌ Could not extract case number, report number, and year from PDF. Please check the document."
                )
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
                
            # Get prefix from environment variable or use default
            case_id_prefix = os.environ.get("CASE_ID_PREFIX", "SEPPATRI").split('#')[0].strip()
            
            # Create new case ID with underscores for internal use (file storage)
            case_id = f"{case_id_prefix}_{case_number}_{report_number}_{case_year}"
            # Create display version with the correct format for user display
            display_id = f"{case_id_prefix} {case_number}/{report_number}/{case_year}"
            
            logger.info(f"Generated proper case ID: {case_id} (display: {display_id})")
            
            # Check if case already exists
            existing_case = workflow_manager.case_manager.load_case(case_id)
            if existing_case:
                logger.info(f"Case {case_id} already exists. Asking user what to do.")
                # Clean up temp directory, no longer needed for now
                shutil.rmtree(temp_dir, ignore_errors=True)
                
                # Store the PDF data temporarily in the state_manager's custom_data
                if not hasattr(workflow_manager.state_manager, 'custom_data'):
                    setattr(workflow_manager.state_manager, 'custom_data', {})
                
                workflow_manager.state_manager.custom_data[f"temp_pdf_{user_id}"] = {
                    "pdf_file": pdf_file,
                    "extracted_info": extracted_info,
                    "case_id": case_id,
                    "display_id": display_id
                }
                
                # Present options to user
                buttons = [
                    [InlineKeyboardButton("Continue Evidence Collection", callback_data=f"continue_{case_id}")],
                    [InlineKeyboardButton("Overwrite Case (Delete Current Data)", callback_data=f"overwrite_{case_id}")],
                    [InlineKeyboardButton("Cancel", callback_data="cancel_pdf_upload")]
                ]
                reply_markup = InlineKeyboardMarkup(buttons)
                
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    status_message_id,
                    f"⚠️ A case with ID {display_id} already exists. What would you like to do?",
                    reply_markup=reply_markup
                )
                return
            
            # NOW create the case with the correct ID
            case_path = workflow_manager.case_manager.create_case(case_id, pdf_file.file_name)
            if not case_path:
                logger.error(f"Failed to create case directory structure for case {case_id}")
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    status_message_id,
                    "❌ Failed to create case storage. Please try again later."
                )
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            
            # Move the PDF to the permanent location
            pdf_path = case_path / "document.pdf"
            try:
                shutil.copy2(temp_pdf_path, pdf_path)
                logger.info(f"Copied PDF from {temp_pdf_path} to {pdf_path}")
                
                # Register the PDF in the case
                workflow_manager.case_manager.register_pdf_in_case(case_id, str(pdf_path))
                
                # Update case with all extracted info (already have the correct ID)
                workflow_manager.case_manager.update_case_with_extracted_info(case_id, extracted_info)
                logger.info(f"Updated case {case_id} with extracted information")
            except Exception as e:
                logger.error(f"Failed to move PDF or update case: {e}")
                await _safe_update_message(
                    workflow_manager,
                    user_id,
                    status_message_id,
                    "❌ Failed to finalize case creation. Please try again later."
                )
                workflow_manager.case_manager.delete_case(case_id)  # Clean up partial case
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary directory {temp_dir}")
                
        except Exception as e:
            logger.exception(f"Error extracting PDF information: {e}")
            await _safe_update_message(
                workflow_manager,
                user_id,
                status_message_id,
                "❌ Error processing the PDF. The file may be password-protected, corrupt, or in an unsupported format."
            )
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        # Update status message to indicate success
        await _safe_update_message(
            workflow_manager,
            user_id,
            status_message_id,
            "✅ PDF processed successfully!"
        )
        
        # Create and pin the case status message (with just the case ID)
        try:
            from .workflow_status import create_case_status_message
            await create_case_status_message(workflow_manager, user_id, case_id)
            logger.info(f"Created and pinned status message for case {case_id}")
        except Exception as e:
            logger.warning(f"Failed to create/pin status message for case {case_id}: {e}")
            # Continue anyway - this is not critical
        
        # Set state to evidence collection with the case ID
        workflow_manager.state_manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id=case_id)
        
        # Try to add the user to the list of allowed users if not already there
        if hasattr(workflow_manager, 'allowed_users'):
            if user_id not in workflow_manager.allowed_users:
                workflow_manager.allowed_users.append(user_id)
                logger.info(f"Added user {user_id} to allowed users list")
        else:
            logger.debug(f"WorkflowManager does not have allowed_users attribute, skipping user addition")
            
        # Try to generate LLM content for the case (summary and checklist)
        try:
            logger.info(f"Attempting to generate LLM content for case {case_id}")
            await generate_case_llm_content(workflow_manager, case_id)
            
            # Send the occurrence briefing to the user
            from .workflow_llm import send_occurrence_briefing
            await send_occurrence_briefing(workflow_manager, user_id, case_id)
            logger.info(f"Sent occurrence briefing for case {case_id}")
        except Exception as e:
            logger.error(f"Failed to generate LLM content for case {case_id}: {e}")
            # Continue anyway - this can be done later or manually
        
        # Send the first evidence collection prompt
        try:
            from .workflow_evidence import send_evidence_prompt
            await send_evidence_prompt(workflow_manager, user_id, case_id)
        except Exception as e:
            logger.error(f"Failed to send evidence prompt for case {case_id}: {e}")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "✅ Case created successfully! You can now start sending evidence for this case."
            )
        
    except Exception as e:
        logger.exception(f"Unhandled error in process_pdf_input: {e}")
        # Try to clean up temp directory if it exists
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        # Notify user of error
        error_message = f"An unexpected error occurred while processing your PDF: {str(e)}"
        await _safe_update_message(workflow_manager, user_id, status_message_id, f"❌ {error_message}")
        
        # If we created a partial case, try to delete it
        if case_id:
            try:
                workflow_manager.case_manager.delete_case(case_id)
                logger.info(f"Cleaned up partial case {case_id} after error")
            except Exception as cleanup_error:
                logger.error(f"Failed to clean up partial case {case_id}: {cleanup_error}") 

async def generate_case_llm_content(workflow_manager: 'WorkflowManager', case_id: str) -> bool:
    """Generate LLM content (summary and checklist) for a case.
    
    Args:
        workflow_manager: The workflow manager instance
        case_id: The case ID to generate content for
        
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Generating LLM content for case {case_id}")
        
        # Check dependencies
        if not workflow_manager.case_manager:
            logger.error("No case manager available for LLM content generation")
            return False
            
        # Load the case
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Failed to load case {case_id} for LLM content generation")
            return False
            
        # Import LLM functionality
        from .workflow_llm import generate_case_summary, generate_case_checklist
        
        # Generate summary
        case_summary = await generate_case_summary(workflow_manager, case_id)
        if case_summary:
            logger.info(f"Generated summary for case {case_id}")
            case_info.llm_summary = case_summary
            workflow_manager.case_manager.save_case(case_info)
        else:
            logger.warning(f"Failed to generate summary for case {case_id}")
            
        # Generate checklist
        case_checklist = await generate_case_checklist(workflow_manager, case_id)
        if case_checklist:
            logger.info(f"Generated checklist for case {case_id}")
            case_info.llm_checklist = case_checklist
            workflow_manager.case_manager.save_case(case_info)
        else:
            logger.warning(f"Failed to generate checklist for case {case_id}")
            
        return True
    except Exception as e:
        logger.error(f"Error generating LLM content for case {case_id}: {e}")
        return False 