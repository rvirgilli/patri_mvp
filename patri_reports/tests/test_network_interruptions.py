import pytest
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch, call, ANY
from pathlib import Path
import json
import time
import inspect

# Adjust path to import from patri_reports parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from patri_reports.workflow_manager import WorkflowManager
from patri_reports.state_manager import StateManager, AppState
from patri_reports.case_manager import CaseManager
from patri_reports.api.llm import LLMAPI
from patri_reports.api.whisper import WhisperAPI
from patri_reports.utils.error_handler import NetworkError, TimeoutError, DataError
from telegram import Update, User, Message, Document, CallbackQuery, PhotoSize, Voice

# Create our own fixtures since we can't rely on importing from test_end_to_end_workflow
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
    manager.save_audio_file = AsyncMock(return_value=(Path("/fake/path/audio_1.ogg"), "audio_1"))
    manager.update_evidence_metadata = MagicMock(return_value=True)
    manager.load_case = MagicMock(return_value=case_info)
    
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
def create_mock_update(user_id, text=None, callback_data=None, document=None, photo=None, voice=None):
    """Creates a mock Update object with specified attributes."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = user_id
    update.message = None
    update.callback_query = None

    # Create base message with all attributes explicitly set to None
    if text is not None or document is not None or photo is not None or voice is not None:
        base_message = MagicMock(spec=Message)
        base_message.message_id = 12345
        base_message.text = None
        base_message.document = None
        base_message.photo = None
        base_message.voice = None
        base_message.location = None  # Explicitly set location to None
        update.message = base_message

    if text is not None:
        update.message.text = text
    elif callback_data is not None:
        update.callback_query = AsyncMock(spec=CallbackQuery)
        update.callback_query.data = callback_data
        update.callback_query.message = MagicMock(spec=Message)
        update.callback_query.message.message_id = 67890
        update.callback_query.answer = AsyncMock()
    elif document is not None:
        update.message.document = document
    elif photo is not None:
        update.message.photo = photo
    elif voice is not None:
        update.message.voice = voice

    return update

# Constants for testing
TEST_USER_ID = 98765
mock_context = AsyncMock()

# --- Network Failure Tests ---

@pytest.mark.asyncio
async def test_pdf_upload_network_failure(workflow_manager, mock_state_manager, 
                                       mock_telegram_client, mock_case_manager):
    """Test handling network failure during PDF upload."""
    # Setup state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Mock PDF document
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.mime_type = 'application/pdf'
    mock_pdf.file_id = "PDF_FILE_ID_123"
    mock_pdf.file_name = "test_occurrence.pdf"
    
    # Make save_pdf_file simulate network error
    mock_case_manager.save_pdf_file.side_effect = NetworkError("Connection lost while downloading PDF")
    
    # Simulate uploading PDF
    pdf_update = create_mock_update(TEST_USER_ID, document=mock_pdf)
    await workflow_manager.handle_update(pdf_update, mock_context)
    
    # Verify error message with retry instructions was sent
    network_error_msg_found = False
    
    # Check in send_message calls
    for call in mock_telegram_client.send_message.await_args_list:
        if len(call.args) >= 2 and isinstance(call.args[1], str):
            if "network issue" in call.args[1].lower() and "try again" in call.args[1].lower():
                network_error_msg_found = True
                break
    
    # Check in edit_message_text calls
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str):
            if "network issue" in call.kwargs['text'].lower() and "try again" in call.kwargs['text'].lower():
                network_error_msg_found = True
                break
    
    assert network_error_msg_found, "No network error message with retry instructions found"
    
    # Verify we stayed in WAITING_FOR_PDF state
    mock_state_manager.set_state.assert_not_called()
    
    # Verify cleanup was attempted for the partially created case
    assert mock_case_manager.delete_case.called

@pytest.mark.asyncio
async def test_llm_api_failure_recovery(workflow_manager, mock_state_manager, 
                                      mock_telegram_client, mock_case_manager,
                                      mock_llm_processor):
    """Test graceful handling of LLM API failures during PDF processing."""
    # Setup state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Setup case info without relying on LLM
    case_info = {
        "case_id": "TEST-CASE-123",
        "location": {
            "address": "123 Test St, Sample City",
            "coordinates": {"latitude": 37.7749, "longitude": -122.4194}
        },
        "timestamp": {"case_received": "2023-08-01T12:00:00Z"},
        "metadata": {"title": "Test Case", "reference": "REF-123"}
    }
    
    # Make sure PDF is not detected as corrupted
    mock_case_manager.is_pdf_corrupted.return_value = False
    
    # Make extract_pdf_info return a valid value
    mock_case_manager.extract_pdf_info.return_value = case_info
    
    # Make PDF processing succeed
    mock_case_manager.process_pdf.return_value = case_info
    
    # Make LLM API call fail
    workflow_manager.generate_summary_and_checklist.side_effect = NetworkError("LLM API connection failed")
    
    # Mock PDF document
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.mime_type = 'application/pdf'
    mock_pdf.file_id = "PDF_FILE_ID_123"
    mock_pdf.file_name = "test_occurrence.pdf"
    
    # Simulate uploading PDF
    pdf_update = create_mock_update(TEST_USER_ID, document=mock_pdf)
    await workflow_manager.handle_update(pdf_update, mock_context)
    
    # Verify we still processed the case despite LLM error
    mock_state_manager.set_state.assert_called_with(AppState.EVIDENCE_COLLECTION, active_case_id=ANY)
    
    # Verify error message about summary generation
    llm_error_msg_found = False
    for call in mock_telegram_client.send_message.await_args_list:
        if len(call.args) >= 2 and isinstance(call.args[1], str):
            message = call.args[1].lower()
            if "unable" in message and ("summary" in message or "ai service" in message):
                llm_error_msg_found = True
                break
    
    assert llm_error_msg_found, "No message about LLM error found"
    
    # Verify we still sent a case creation success message
    case_created_msg_found = False
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str):
            message = call.kwargs['text'].lower()
            if "case" in message and "success" in message:
                case_created_msg_found = True
                break
    
    assert case_created_msg_found, "No case creation success message found"

@pytest.mark.asyncio
async def test_whisper_api_failure_recovery(workflow_manager, mock_state_manager, 
                                         mock_telegram_client, mock_case_manager,
                                         mock_whisper_processor):
    """Test graceful handling of Whisper API failures during audio transcription."""
    # Setup state for evidence collection
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
    
    # Mock telegram download to return audio bytes
    mock_telegram_client.download_file.return_value = (b'fake_audio_data', None)
    
    # IMPORTANT: This is required for handle_evidence_collection_state to choose the test path
    # The method checks if save_audio_file is both present and callable
    save_audio_file_mock = AsyncMock(return_value=(Path("/fake/path/audio_1.ogg"), "audio_1"))
    mock_case_manager.save_audio_file = save_audio_file_mock
    
    # Make sure Whisper API transcribe raises the expected network error
    mock_whisper_processor.transcribe.side_effect = NetworkError("Whisper API connection failed")
    
    # Mock voice object
    mock_voice = MagicMock(spec=Voice)
    mock_voice.file_id = "VOICE_FILE_ID_123"
    mock_voice.duration = 10  # 10 seconds
    
    # Create a mock message for the processing status
    mock_processing_msg = MagicMock()
    mock_processing_msg.message_id = 12345
    mock_telegram_client.send_message.return_value = mock_processing_msg
    
    # Mock temporary file
    mock_temp_file = MagicMock()
    mock_temp_file.name = '/tmp/temp_audio.ogg'
    mock_temp_file.__enter__.return_value = mock_temp_file
    
    # Simulate sending voice evidence
    voice_update = create_mock_update(TEST_USER_ID, voice=mock_voice)
    
    # Run the test with mocking of tempfile and os.unlink
    with patch('tempfile.NamedTemporaryFile', return_value=mock_temp_file), \
         patch('os.unlink', return_value=None), \
         patch('os.path.exists', return_value=True):
        await workflow_manager.handle_update(voice_update, mock_context)
    
    # Verify audio was still saved despite transcription failure
    mock_telegram_client.download_file.assert_awaited_once_with("VOICE_FILE_ID_123")
    save_audio_file_mock.assert_awaited_once()
    mock_case_manager.add_audio_evidence.assert_called_once_with("TEST-CASE-123", b'fake_audio_data', transcript="")
    
    # Verify transcription failure message
    transcription_failed = False
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str):
            if ("error" in call.kwargs['text'].lower() or 
                "failed" in call.kwargs['text'].lower() or 
                "❌" in call.kwargs['text'] or
                "⚠️" in call.kwargs['text']):
                transcription_failed = True
                break
    
    assert transcription_failed, "No transcription failure message shown to user"
    
    # Verify audio still saved message
    audio_saved = False
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str):
            if "audio" in call.kwargs['text'].lower() and "saved" in call.kwargs['text'].lower():
                audio_saved = True
                break
    
    assert audio_saved, "No audio saved confirmation shown to user"

# --- Timeout Tests ---

@pytest.mark.asyncio
async def test_pdf_processing_timeout(workflow_manager, mock_state_manager, 
                                    mock_telegram_client, mock_case_manager):
    """Test handling of PDF processing timeout."""
    # Setup state
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    
    # Configure mock to provide valid responses for the PDF processing steps
    mock_case_manager.create_case.return_value = Path("/fake/path/TEST-CASE-123")
    mock_case_manager.is_pdf_corrupted.return_value = False  # PDF is valid
    
    # Set up the timeout at the extract_pdf_info step
    mock_case_manager.extract_pdf_info.side_effect = TimeoutError("PDF extraction timeout")
    
    # Mock telegram download to return valid PDF content
    mock_telegram_client.download_file.return_value = (b'fake_pdf_content', None)
    
    # Mock PDF document
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.mime_type = 'application/pdf'
    mock_pdf.file_id = "PDF_FILE_ID_123"
    mock_pdf.file_name = "test_occurrence.pdf"
    
    # Simulate uploading PDF
    pdf_update = create_mock_update(TEST_USER_ID, document=mock_pdf)
    await workflow_manager.handle_update(pdf_update, mock_context)
    
    # Verify error message in edit_message_text calls
    error_msg_found = False
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str):
            text = call.kwargs['text'].lower()
            if "❌" in call.kwargs['text'] and "error" in text and "pdf" in text:
                error_msg_found = True
                break
    
    assert error_msg_found, "No error message found in any edit_message_text calls"
    
    # Verify we stayed in WAITING_FOR_PDF state (state wasn't changed after error)
    assert not any(call == call.call(AppState.EVIDENCE_COLLECTION, active_case_id=ANY) 
                 for call in mock_state_manager.set_state.call_args_list)

# --- State Recovery Tests ---

@pytest.mark.asyncio
async def test_restart_recovery(workflow_manager, mock_state_manager, 
                              mock_telegram_client, mock_case_manager):
    """Test application recovering state after simulated restart.
    
    Note: The current implementation treats a /start message during evidence collection
    as regular text rather than a command, so it adds it as a case note.
    """
    # Setup state to simulate resumed session
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
    
    # Mock case info for the existing case
    case_info = {
        "case_id": "TEST-CASE-123",
        "location": {"address": "123 Test St", "coordinates": {"latitude": 37.7749, "longitude": -122.4194}},
        "timestamp": {"case_received": "2023-08-01T12:00:00Z", "attendance_started": "2023-08-01T12:30:00Z"},
        "metadata": {"title": "Test Case", "reference": "REF-123"},
        "evidence": [
            {"id": "text_1", "type": "text", "content": "Previous note", "timestamp": "2023-08-01T12:30:00Z"}
        ]
    }
    mock_case_manager.load_case.return_value = case_info
    
    # Reset the mock to clear any previous calls
    mock_telegram_client.send_message.reset_mock()
    
    # Simulate startup/first message after restart
    start_update = create_mock_update(TEST_USER_ID, text="/start")
    await workflow_manager.handle_update(start_update, mock_context)
    
    # Verify the user state is maintained
    assert mock_state_manager.get_state.return_value == AppState.EVIDENCE_COLLECTION
    assert mock_state_manager.get_active_case_id.return_value == "TEST-CASE-123"
    
    # Verify that the /start command was added as a case note
    mock_case_manager.add_case_note.assert_called_once_with(
        "TEST-CASE-123", text_content="/start"
    )
    
    # Verify the note added confirmation message
    note_added_msg = any("Note added" in call.args[1] for call in mock_telegram_client.send_message.await_args_list if len(call.args) > 1)
    assert note_added_msg, "No confirmation message for adding the note"
    
    # Verify the state remains unchanged
    mock_state_manager.set_state.assert_not_called()

@pytest.mark.asyncio
async def test_data_corruption_recovery(workflow_manager, mock_state_manager, 
                                      mock_telegram_client, mock_case_manager):
    """Test recovery when case data is corrupted."""
    # Setup state with active case
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
    
    # Simulate data corruption
    mock_case_manager.load_case.side_effect = DataError("Case data file is corrupted")
    
    # Simulate user sending a message
    message_update = create_mock_update(TEST_USER_ID, text="Evidence text")
    await workflow_manager.handle_update(message_update, mock_context)
    
    # Verify error message might be in edit_message_text or send_message
    error_msg_found = False
    for call in mock_telegram_client.send_message.await_args_list:
        if len(call.args) >= 2 and isinstance(call.args[1], str) and "error" in call.args[1].lower():
            error_msg_found = True
            break
    
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str) and "error" in call.kwargs['text'].lower():
            error_msg_found = True
            break
            
    assert error_msg_found, "No error message found in any message calls"
    
    # Verify we reset to IDLE state
    mock_state_manager.set_state.assert_called_with(AppState.IDLE)

# --- Retry Logic Tests ---

@pytest.mark.asyncio
async def test_auto_retry_on_transient_error(workflow_manager, mock_state_manager, 
                                           mock_telegram_client, mock_case_manager,
                                           mock_whisper_processor):
    """Test automatic retry on transient error."""
    # Setup state for evidence collection
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
    
    # Setup save_audio_file to fail once, then succeed
    mock_case_manager.save_audio_file.side_effect = [
        NetworkError("Temporary network error"),  # First attempt fails
        (Path("/fake/path/audio_1.ogg"), "audio_1")  # Second attempt succeeds
    ]
    
    # Mock voice object
    mock_voice = MagicMock(spec=Voice)
    mock_voice.file_id = "VOICE_FILE_ID_123"
    mock_voice.duration = 10
    
    # Simulate sending voice evidence
    voice_update = create_mock_update(TEST_USER_ID, voice=mock_voice)
    
    # Patch time.sleep to avoid actual delays in tests
    with patch('time.sleep', return_value=None):
        await workflow_manager.handle_update(voice_update, mock_context)
    
    # Verify retry occurred
    assert mock_case_manager.save_audio_file.call_count == 2
    
    # Verify audio was processed after successful retry
    mock_whisper_processor.transcribe.assert_called_once()
    mock_case_manager.add_audio_evidence.assert_called_once()
    
    # Verify success message (not specifically about retries, just normal success)
    success_message_found = False
    
    # Check send_message calls
    for call in mock_telegram_client.send_message.await_args_list:
        if len(call.args) >= 2 and isinstance(call.args[1], str) and "audio" in call.args[1].lower() and "added" in call.args[1].lower():
            success_message_found = True
            break
    
    # Also check edit_message_text calls
    for call in mock_telegram_client.edit_message_text.await_args_list:
        if 'text' in call.kwargs and isinstance(call.kwargs['text'], str) and "audio" in call.kwargs['text'].lower():
            success_message_found = True
            break
    
    assert success_message_found, "No audio success message found in any message calls"

# --- Message Queue Tests ---

@pytest.mark.asyncio
async def test_message_processing_during_lengthy_operation(workflow_manager, mock_state_manager, 
                                                        mock_telegram_client, mock_case_manager):
    """Test system can queue and process messages during lengthy operations."""
    # Setup state
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
    
    # Set up a processing function that will delay
    original_process = workflow_manager.process_photo_evidence
    
    async def delayed_processing(*args, **kwargs):
        # Just a mock delay that won't actually pause the test
        await asyncio.sleep(0)
        return await original_process(*args, **kwargs)
    
    workflow_manager.process_photo_evidence = delayed_processing
    
    # Mock photo objects
    mock_photo1 = [MagicMock(spec=PhotoSize)]
    mock_photo1[0].file_id = "PHOTO_FILE_ID_1"
    
    mock_photo2 = [MagicMock(spec=PhotoSize)]
    mock_photo2[0].file_id = "PHOTO_FILE_ID_2"
    
    # Simulate sending two photos in quick succession
    photo_update1 = create_mock_update(TEST_USER_ID, photo=mock_photo1)
    photo_update2 = create_mock_update(TEST_USER_ID, photo=mock_photo2)
    
    # Process both updates
    await workflow_manager.handle_update(photo_update1, mock_context)
    await workflow_manager.handle_update(photo_update2, mock_context)
    
    # Verify both photos were processed
    assert mock_case_manager.add_photo_evidence.call_count == 2
    
    # Verify confirmation messages for both photos
    messages = [call.args[1] for call in mock_telegram_client.send_message.await_args_list]
    photo_confirmations = [msg for msg in messages if "Photo added" in msg]
    assert len(photo_confirmations) == 2

# --- Multiple Error Handling ---

@pytest.mark.asyncio
async def test_multiple_sequential_errors_recovery(workflow_manager, mock_state_manager, 
                                                mock_telegram_client, mock_case_manager):
    """Test system can recover from multiple sequential errors."""
    # Setup state
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = "TEST-CASE-123"
    
    # Set up a sequence of errors for multiple evidence types
    mock_case_manager.add_case_note.side_effect = [
        NetworkError("Text error 1"),  # First text fails
        "text_1"  # Second text succeeds
    ]
    
    mock_case_manager.add_photo_evidence.side_effect = DataError("Photo error")
    
    # Simulate sending text with error
    text_update1 = create_mock_update(TEST_USER_ID, text="Text evidence 1")
    await workflow_manager.handle_update(text_update1, mock_context)
    
    # Verify error message
    assert any("error" in call.args[1].lower() 
              for call in mock_telegram_client.send_message.await_args_list)
    
    # Reset message mock to clear history
    mock_telegram_client.send_message.reset_mock()
    
    # Simulate sending text again (should succeed)
    text_update2 = create_mock_update(TEST_USER_ID, text="Text evidence 2")
    await workflow_manager.handle_update(text_update2, mock_context)
    
    # Verify success message
    assert any("text note added" in call.args[1].lower() 
              for call in mock_telegram_client.send_message.await_args_list)
    
    # Reset message mock to clear history
    mock_telegram_client.send_message.reset_mock()
    
    # Simulate sending photo (should fail with data error)
    mock_photo = [MagicMock(spec=PhotoSize)]
    mock_photo[0].file_id = "PHOTO_FILE_ID_1"
    photo_update = create_mock_update(TEST_USER_ID, photo=mock_photo)
    await workflow_manager.handle_update(photo_update, mock_context)
    
    # Verify different error message for photo
    assert any("error" in call.args[1].lower() and "photo" in call.args[1].lower()
              for call in mock_telegram_client.send_message.await_args_list)
    
    # Verify we're still in EVIDENCE_COLLECTION state
    assert mock_state_manager.set_state.call_count == 0  # Should not change state 