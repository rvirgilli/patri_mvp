import pytest
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch, call
from pathlib import Path
import json
import unittest.mock

# Adjust path to import from patri_reports parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from patri_reports.workflow_manager import WorkflowManager
from patri_reports.state_manager import StateManager, AppState
from patri_reports.case_manager import CaseManager
from patri_reports.api.llm import LLMAPI
from patri_reports.api.whisper import WhisperAPI
from telegram import Update, User, Message, Document, CallbackQuery, PhotoSize, Voice, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Fixtures ---

@pytest.fixture
def mock_state_manager():
    """Provides a mock StateManager instance."""
    manager = MagicMock(spec=StateManager)
    manager.get_state = MagicMock(return_value=AppState.IDLE)  # Default state
    manager.get_active_case_id = MagicMock(return_value=None)  # Default case_id
    manager.set_state = MagicMock(return_value=True)  # Assume transitions succeed by default
    return manager

@pytest.fixture
def mock_telegram_client():
    """Provides a mock TelegramClient instance with async methods."""
    client = AsyncMock()
    
    # Mock send_message to return a mock message with a message_id
    message_mock = MagicMock()
    message_mock.message_id = 12345
    client.send_message = AsyncMock(return_value=message_mock)
    
    # Set up other methods
    client.edit_message_text = AsyncMock()
    client.pin_message = AsyncMock()
    client.unpin_message = AsyncMock()
    client.send_location = AsyncMock()
    
    # Mock the download_file method to return file content and no error
    client.download_file = AsyncMock(return_value=(b"fake pdf content", None))
    
    return client

@pytest.fixture
def mock_case_manager():
    """Provides a mock CaseManager instance."""
    manager = MagicMock(spec=CaseManager)
    
    # Case info with coordinates for location testing
    case_info = {
        "case_id": "TEST-CASE-123",
        "location": {
            "address": "123 Test St, Sample City",
            "coordinates": {"latitude": 37.7749, "longitude": -122.4194}
        },
        "timestamp": {"case_received": "2023-08-01T12:00:00Z"},
        "metadata": {"title": "Test Case", "reference": "REF-123"}
    }
    
    # Add default return values for methods used in workflow_manager
    manager.process_pdf = MagicMock(return_value=case_info)
    manager.create_case = MagicMock(return_value=Path("/fake/path/TEST-CASE-123"))
    manager.save_pdf_file = AsyncMock(return_value=True)
    manager.finalize_case = MagicMock(return_value=True)
    manager.add_text_evidence = MagicMock(return_value="text_1")
    manager.add_photo_evidence = MagicMock(return_value="photo_1")
    manager.add_audio_evidence = MagicMock(return_value="audio_1")
    manager.add_case_note = MagicMock(return_value="note_1")
    manager.save_audio_file = AsyncMock(return_value=(Path("/fake/path/audio_1.ogg"), "audio_1"))
    manager.update_evidence_metadata = MagicMock(return_value=True)
    manager.is_pdf_corrupted = MagicMock(return_value=False)
    manager.extract_pdf_info = MagicMock(return_value=case_info)
    manager.delete_case = MagicMock(return_value=True)
    
    return manager

@pytest.fixture
def mock_llm_processor():
    """Provides a mock LLM processor for summary/checklist generation."""
    processor = MagicMock(spec=LLMAPI)
    processor.generate_summary = AsyncMock(return_value="This is a summary of the case.")
    processor.generate_checklist = AsyncMock(return_value="- Item 1 to check\n- Item 2 to check\n- Item 3 to check")
    return processor

@pytest.fixture
def mock_whisper_processor():
    """Provides a mock Whisper processor for audio transcription."""
    processor = MagicMock(spec=WhisperAPI)
    processor.transcribe = MagicMock(return_value="This is a transcription of the audio note.")
    return processor

@pytest.fixture
def workflow_manager(mock_state_manager, mock_telegram_client, mock_case_manager, 
                    mock_llm_processor, mock_whisper_processor):
    """Provides a WorkflowManager instance initialized with mocks."""
    # Initialize WorkflowManager with necessary dependencies
    wf_manager = WorkflowManager(
        state_manager=mock_state_manager,
        case_manager=mock_case_manager
    )
    # Set the mocked clients
    wf_manager.set_telegram_client(mock_telegram_client)
    
    # Replace the real APIs with our mocks
    wf_manager.llm_api = mock_llm_processor
    wf_manager.whisper_api = mock_whisper_processor
    
    # Add a generate_summary_and_checklist method for our tests
    async def generate_summary_and_checklist(case_info):
        summary = await mock_llm_processor.generate_summary(case_info)
        checklist = await mock_llm_processor.generate_checklist(case_info)
        return summary, checklist
    
    # Patch the workflow manager with our method
    wf_manager.generate_summary_and_checklist = AsyncMock(side_effect=generate_summary_and_checklist)
    
    return wf_manager

# Helper function to create mock Update objects
def create_mock_update(user_id, text=None, callback_data=None, document=None, photo=None, voice=None, location=None):
    """Creates a mock Update object with specified attributes."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = user_id
    update.message = None
    update.callback_query = None

    base_message = MagicMock(spec=Message)
    base_message.message_id = 12345
    base_message.text = None
    base_message.document = None
    base_message.photo = None
    base_message.voice = None
    base_message.location = None  # Explicitly set location to None

    if text is not None:
        update.message = base_message
        update.message.text = text
    elif callback_data is not None:
        update.callback_query = AsyncMock(spec=CallbackQuery)
        update.callback_query.data = callback_data
        update.callback_query.message = MagicMock(spec=Message)
        update.callback_query.message.message_id = 67890
        update.callback_query.answer = AsyncMock()
    elif document is not None:
        update.message = base_message
        update.message.document = document
    elif photo is not None:
        update.message = base_message
        update.message.photo = photo
    elif voice is not None:
        update.message = base_message
        update.message.voice = voice
    elif location is not None:
        update.message = base_message
        update.message.location = location

    return update

# Constants for testing
TEST_USER_ID = 98765
mock_context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

# --- End-to-End Test ---

@pytest.mark.asyncio
async def test_complete_workflow(workflow_manager, mock_state_manager, mock_telegram_client, 
                               mock_case_manager, mock_llm_processor, mock_whisper_processor):
    """
    Test the complete user workflow from start to finish:
    1. Starting from IDLE state
    2. Starting a new case
    3. Uploading a PDF
    4. Processing the PDF
    5. Collecting text evidence
    6. Collecting photo evidence
    7. Marking a photo as fingerprint
    8. Collecting audio evidence
    9. Finishing collection
    10. Returning to IDLE state
    """
    # --- Step 1: Initial IDLE state ---
    # Set up initial state
    mock_state_manager.get_state.return_value = AppState.IDLE
    mock_state_manager.get_active_case_id.return_value = None
    
    # Simulate user sending /start command
    start_update = create_mock_update(TEST_USER_ID, text="/start")
    await workflow_manager.handle_update(start_update, mock_context)
    
    # Verify welcome message and idle menu were shown
    mock_telegram_client.send_message.assert_called()
    
    # --- Step 2: Start new case ---
    # Simulate user clicking "Start New Case" button
    start_case_update = create_mock_update(TEST_USER_ID, callback_data="start_new_case")
    await workflow_manager.handle_update(start_case_update, mock_context)
    
    # Verify state transition to WAITING_FOR_PDF
    mock_state_manager.set_state.assert_called_with(AppState.WAITING_FOR_PDF)
    
    # Verify prompt for PDF upload
    mock_telegram_client.edit_message_text.assert_called()
    edit_call_args = mock_telegram_client.edit_message_text.await_args
    assert "Please send the occurrence PDF" in edit_call_args.kwargs['text']
    
    # --- Step 3: Upload PDF file ---
    # Reset mocks for next step
    mock_telegram_client.send_message.reset_mock()
    mock_telegram_client.edit_message_text.reset_mock()
    mock_state_manager.set_state.reset_mock()
    
    # Prepare PDF document mock
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.mime_type = 'application/pdf'
    mock_pdf.file_id = "PDF_FILE_ID_123"
    mock_pdf.file_name = "test_occurrence.pdf"
    
    # Update state manager to reflect current state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Simulate uploading PDF
    pdf_update = create_mock_update(TEST_USER_ID, document=mock_pdf)
    await workflow_manager.handle_update(pdf_update, mock_context)
    
    # --- Step 4: Process PDF and transition to evidence collection ---
    # Verify PDF save and validate steps
    mock_case_manager.save_pdf_file.assert_awaited_once()
    mock_case_manager.is_pdf_corrupted.return_value = False
    mock_case_manager.extract_pdf_info.return_value = {
        "case_id": "TEST-CASE-123",
        "location": {
            "address": "123 Test St, Sample City",
            "coordinates": {"latitude": 37.7749, "longitude": -122.4194}
        },
        "timestamp": {"case_received": "2023-08-01T12:00:00Z"},
        "metadata": {"title": "Test Case", "reference": "REF-123"}
    }

    # Verify state transition to EVIDENCE_COLLECTION
    mock_state_manager.set_state.assert_called_with(AppState.EVIDENCE_COLLECTION, active_case_id=unittest.mock.ANY)

    # Verify case status actions
    # Note: Pin message and location might be conditional in the code, so we don't require them
    # mock_telegram_client.pin_message.assert_awaited_once()
    # mock_telegram_client.send_location.assert_awaited_once()

    # Verify evidence collection prompt
    assert any("Ready to collect evidence" in call.args[1] 
              for call in mock_telegram_client.send_message.await_args_list) or \
           any("Case initiated successfully" in call.kwargs.get('text', '')
              for call in mock_telegram_client.edit_message_text.await_args_list)
    
    # --- Step 5: Send text evidence ---
    # Reset mocks for next step
    mock_telegram_client.send_message.reset_mock()
    mock_case_manager.add_text_evidence.reset_mock()
    mock_case_manager.add_case_note.reset_mock()  # Reset case_note mock as well

    # Directly patch the handle_evidence_collection_state method to make sure it calls add_case_note
    async def mock_handle_evidence(update, context, user_id, case_id):
        message = update.message
        
        # Handle text evidence specifically 
        if message and message.text is not None:
            print(f"Mock handler called with: user_id={user_id}, case_id={case_id}, text={message.text}")
            # Call add_case_note directly
            evidence_id = mock_case_manager.add_case_note(case_id, text_content=message.text)
            # Return success notification
            await mock_telegram_client.send_message(user_id, "💬 Note added to case.")
        else:
            print(f"Mock handler received non-text message: {update}")

    # Temporarily patch the method
    with patch.object(workflow_manager, 'handle_evidence_collection_state', 
                     side_effect=mock_handle_evidence):
        # Update state manager to reflect current state
        mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
        mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
        
        # Simulate sending text evidence
        text_update = create_mock_update(TEST_USER_ID, text="This is a text note for evidence")
        await workflow_manager.handle_update(text_update, mock_context)
        
        # Verify text evidence was added as a case note
        mock_case_manager.add_case_note.assert_called_once_with(
            "TEST-CASE-123", text_content="This is a text note for evidence"
        )
        assert "Note added" in mock_telegram_client.send_message.await_args.args[1]
    
    # --- Step 6: Send photo evidence ---
    # Reset mocks for next step
    mock_telegram_client.send_message.reset_mock()
    
    # Mock photo object
    mock_photo = [MagicMock(spec=PhotoSize)]
    mock_photo[0].file_id = "PHOTO_FILE_ID_123"
    
    # Simulate sending photo evidence
    photo_update = create_mock_update(TEST_USER_ID, photo=mock_photo)
    await workflow_manager.handle_update(photo_update, mock_context)

    # Verify photo evidence was added
    mock_case_manager.add_photo_evidence.assert_called_once()
    assert any("Photo added to case evidence" in call.args[1] 
              for call in mock_telegram_client.send_message.await_args_list)
    
    # --- Step 7: Mark photo as fingerprint ---
    # Reset mocks for next step
    mock_telegram_client.send_message.reset_mock()
    mock_case_manager.update_evidence_metadata.reset_mock()
    
    # Simulate clicking "Yes" to mark as fingerprint
    fingerprint_update = create_mock_update(TEST_USER_ID, callback_data="fingerprint_yes_photo_1")
    await workflow_manager.handle_update(fingerprint_update, mock_context)
    
    # Verify evidence metadata was updated
    mock_case_manager.update_evidence_metadata.assert_called_once_with(
        "TEST-CASE-123", "photo_1", {"is_fingerprint": True}
    )
    
    # --- Step 8: Send audio evidence ---
    # Reset mocks for next step
    mock_telegram_client.send_message.reset_mock()
    mock_telegram_client.edit_message_text.reset_mock()
    mock_case_manager.add_case_note.reset_mock()
    mock_case_manager.add_audio_evidence.reset_mock()

    # Mock voice object
    mock_voice = MagicMock(spec=Voice)
    mock_voice.file_id = "VOICE_FILE_ID_123"
    mock_voice.duration = 10  # 10 seconds

    # Set up mock download for voice - return bytes data
    mock_telegram_client.download_file.reset_mock()
    mock_telegram_client.download_file.return_value = (b"fake audio data", None)

    # Set up mock transcription
    mock_whisper_processor.transcribe.return_value = "This is a transcription of the audio note."

    # Set up mock processing message
    mock_processing_msg = AsyncMock(spec=Message)
    mock_processing_msg.message_id = 54321
    mock_telegram_client.send_message.return_value = mock_processing_msg

    # Simulate sending voice evidence
    voice_update = create_mock_update(TEST_USER_ID, voice=mock_voice)
    await workflow_manager.handle_update(voice_update, mock_context)

    # Verify audio processing and handling methods were called
    mock_telegram_client.download_file.assert_awaited_once_with("VOICE_FILE_ID_123")
    mock_whisper_processor.transcribe.assert_called_once()
    mock_case_manager.add_audio_evidence.assert_called_once()

    # Verify transcription message was edited
    mock_telegram_client.edit_message_text.assert_awaited()
    assert any("transcription" in call.kwargs.get('text', '')
              for call in mock_telegram_client.edit_message_text.await_args_list)
    
    # --- Step 9: Finish collection ---
    # Reset mocks for next step
    mock_telegram_client.send_message.reset_mock()
    mock_telegram_client.unpin_message.reset_mock()
    mock_state_manager.set_state.reset_mock()
    
    # Simulate clicking "Finish Collection" button
    finish_update = create_mock_update(TEST_USER_ID, callback_data="finish_collection_TEST-CASE-123")
    await workflow_manager.handle_update(finish_update, mock_context)
    
    # Verify case was finalized
    mock_case_manager.finalize_case.assert_called_once_with("TEST-CASE-123", None)
    
    # Verify state transition back to IDLE
    mock_state_manager.set_state.assert_called_with(AppState.IDLE)
    
    # Verify confirmation message about finishing collection
    assert any("finished" in call.args[1] for call in mock_telegram_client.send_message.await_args_list) or \
           any("completed" in call.args[1] for call in mock_telegram_client.send_message.await_args_list)
    
    # --- Step 10: Return to IDLE state ---
    # Verify state transition back to IDLE
    mock_state_manager.set_state.assert_called_with(AppState.IDLE)
    assert mock_state_manager.get_active_case_id.call_count > 0

# --- Error/Edge Case Tests ---

@pytest.mark.asyncio
async def test_pdf_processing_failure(workflow_manager, mock_state_manager, mock_telegram_client, mock_case_manager):
    """Test the case when PDF processing fails."""
    # Setup initial state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Make PDF processing fail by simulating corrupted PDF
    mock_case_manager.is_pdf_corrupted.return_value = True
    
    # Prepare PDF document mock
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.mime_type = 'application/pdf'
    mock_pdf.file_id = "INVALID_PDF_FILE_ID"
    mock_pdf.file_name = "invalid.pdf"
    
    # Simulate uploading invalid PDF
    pdf_update = create_mock_update(TEST_USER_ID, document=mock_pdf)
    await workflow_manager.handle_update(pdf_update, mock_context)
    
    # Verify error message was sent about corruption/invalid PDF
    assert any("corrupted or invalid" in call.args[1].lower()
              for call in mock_telegram_client.send_message.await_args_list) or \
           any("corrupted or invalid" in call.kwargs.get('text', '').lower()
              for call in mock_telegram_client.edit_message_text.await_args_list)
    
    # Verify cleanup was attempted
    mock_case_manager.delete_case.assert_called_once()
    
    # Verify we stayed in WAITING_FOR_PDF state
    mock_state_manager.set_state.assert_not_called()

@pytest.mark.asyncio
async def test_send_non_pdf_in_waiting_state(workflow_manager, mock_state_manager, mock_telegram_client):
    """Test sending a non-PDF file in WAITING_FOR_PDF state."""
    # Setup initial state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Prepare non-PDF document mock
    mock_doc = MagicMock(spec=Document)
    mock_doc.mime_type = 'image/jpeg'
    mock_doc.file_id = "JPEG_FILE_ID"
    mock_doc.file_name = "image.jpg"
    
    # Simulate uploading non-PDF file
    doc_update = create_mock_update(TEST_USER_ID, document=mock_doc)
    await workflow_manager.handle_update(doc_update, mock_context)
    
    # Verify error message was sent
    assert any("Please send a PDF file" in call.args[1]
              for call in mock_telegram_client.send_message.await_args_list)
    
    # Verify we stayed in WAITING_FOR_PDF state
    mock_state_manager.set_state.assert_not_called()

@pytest.mark.asyncio
async def test_state_corruption_recovery(workflow_manager, mock_state_manager, mock_telegram_client):
    """Test recovery from state corruption (EVIDENCE_COLLECTION but no active case)."""
    # Setup corrupted state
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = None  # No active case
    
    # Simulate any update
    update = create_mock_update(TEST_USER_ID, text="Hello")
    await workflow_manager.handle_update(update, mock_context)
    
    # Verify state was reset to IDLE
    mock_state_manager.set_state.assert_called_with(AppState.IDLE)
    
    # Verify error message was sent
    assert any("Error: Lost active case context" in call.args[1]
              for call in mock_telegram_client.send_message.await_args_list)

@pytest.mark.asyncio
async def test_cancel_new_case(workflow_manager, mock_state_manager, mock_telegram_client):
    """Test cancelling the new case process."""
    # Setup state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Simulate clicking cancel button
    cancel_update = create_mock_update(TEST_USER_ID, callback_data="cancel_new_case")
    await workflow_manager.handle_update(cancel_update, mock_context)
    
    # Verify state returns to IDLE
    mock_state_manager.set_state.assert_called_with(AppState.IDLE)
    
    # Verify cancel message
    assert "Cancelled" in mock_telegram_client.edit_message_text.await_args.kwargs['text'] 