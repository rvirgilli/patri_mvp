import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import unittest.mock # Import unittest.mock

# Adjust path to import from patri_reports parent directory
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from patri_reports.workflow_manager import WorkflowManager
from patri_reports.state_manager import StateManager, AppState
from patri_reports.telegram_client import TelegramClient # Keep for type hints if needed
from telegram import Update, User, Message, Document, CallbackQuery, PhotoSize, Voice, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from pathlib import Path

# --- Fixtures --- 

@pytest.fixture
def mock_state_manager():
    """Provides a mock StateManager instance."""
    manager = MagicMock(spec=StateManager)
    manager.get_state = MagicMock(return_value=AppState.IDLE) # Default state
    manager.get_active_case_id = MagicMock(return_value=None) # Default case_id
    manager.set_state = MagicMock(return_value=True) # Assume transitions succeed by default
    return manager

@pytest.fixture
def mock_telegram_client():
    """Provides a mock TelegramClient instance with async methods."""
    client = AsyncMock(spec=TelegramClient)
    # Ensure methods called by WorkflowManager are AsyncMocks
    client.send_message = AsyncMock()
    client.edit_message_text = AsyncMock()
    # Add mocks for other potential interactions if needed (pin_message, etc.)
    # client.pin_message = AsyncMock()
    # client.unpin_message = AsyncMock()
    return client

@pytest.fixture
def mock_case_manager():
    """Provides a mock CaseManager instance."""
    from patri_reports.case_manager import CaseManager
    manager = MagicMock(spec=CaseManager)
    
    # Add default return values for methods used in workflow_manager
    manager.process_pdf = MagicMock(return_value=None)
    manager.finalize_case = MagicMock(return_value=True)
    manager.add_text_evidence = MagicMock(return_value="text_evidence_id")
    manager.add_photo_evidence = MagicMock(return_value="photo_evidence_id")
    manager.add_audio_evidence = MagicMock(return_value="audio_evidence_id")
    manager.add_case_note = MagicMock(return_value="note_evidence_id")
    manager.update_evidence_metadata = MagicMock(return_value=True)
    manager.extract_pdf_info = MagicMock(return_value=None)
    manager.is_pdf_corrupted = MagicMock(return_value=False)
    manager.delete_case = MagicMock(return_value=True)
    
    # Add methods needed by process_pdf_input tests
    manager.create_case = MagicMock(return_value=Path("/fake/path/test-case-123"))
    
    # Make save_pdf_file an AsyncMock since it's awaited in workflow_manager
    manager.save_pdf_file = AsyncMock(return_value=True)
    
    return manager

@pytest.fixture
def workflow_manager(mock_state_manager, mock_telegram_client, mock_case_manager):
    """Provides a WorkflowManager instance initialized with mocks."""
    # Initialize WorkflowManager with necessary dependencies
    wf_manager = WorkflowManager(
        state_manager=mock_state_manager,
        case_manager=mock_case_manager
    )
    # Set the mocked TelegramClient
    wf_manager.set_telegram_client(mock_telegram_client)
    return wf_manager

# Helper function to create mock Update objects
def create_mock_update(user_id, text=None, callback_data=None, document=None, photo=None, voice=None):
    """Creates a mock Update object with specified attributes."""
    # Use MagicMock for the top-level update and user as async behavior isn't directly tested here
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = user_id
    update.message = None
    update.callback_query = None

    # Create a base message mock using MagicMock
    base_message = MagicMock(spec=Message)
    base_message.message_id = 12345 # Assign a default ID
    base_message.text = None
    base_message.document = None
    base_message.photo = None
    base_message.voice = None
    base_message.location = None # Ensure location is None by default

    if text is not None:
        update.message = base_message
        update.message.text = text
    elif callback_data is not None:
        # Callback query needs async mock for .answer()
        update.callback_query = AsyncMock(spec=CallbackQuery)
        update.callback_query.data = callback_data
        # Attach a message mock to the callback query
        update.callback_query.message = MagicMock(spec=Message)
        update.callback_query.message.message_id = 67890
        update.callback_query.answer = AsyncMock() # Ensure answer is awaitable
    elif document is not None:
        update.message = base_message
        update.message.document = document
    elif photo is not None:
         update.message = base_message
         update.message.photo = photo
    elif voice is not None:
         update.message = base_message
         update.message.voice = voice

    return update

mock_context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
TEST_USER_ID = 98765

# --- Test handle_update Routing --- 

@pytest.mark.asyncio
async def test_handle_update_routes_to_idle(workflow_manager, mock_state_manager):
    mock_state_manager.get_state.return_value = AppState.IDLE
    update = create_mock_update(TEST_USER_ID, text="/start")
    with patch.object(workflow_manager, 'handle_idle_state', new_callable=AsyncMock) as mock_handler:
        await workflow_manager.handle_update(update, mock_context)
        mock_handler.assert_awaited_once_with(update, mock_context, TEST_USER_ID)

@pytest.mark.asyncio
async def test_handle_update_routes_to_waiting_for_pdf(workflow_manager, mock_state_manager):
    mock_state_manager.get_state.return_value = AppState.WAITING_FOR_PDF
    update = create_mock_update(TEST_USER_ID, text="some text") # Example update
    with patch.object(workflow_manager, 'handle_waiting_for_pdf_state', new_callable=AsyncMock) as mock_handler:
        await workflow_manager.handle_update(update, mock_context)
        mock_handler.assert_awaited_once_with(update, mock_context, TEST_USER_ID)

@pytest.mark.asyncio
async def test_handle_update_routes_to_evidence_collection(workflow_manager, mock_state_manager):
    active_case = "CASE-ROUTE-1"
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = active_case
    update = create_mock_update(TEST_USER_ID, text="evidence text") # Example update
    with patch.object(workflow_manager, 'handle_evidence_collection_state', new_callable=AsyncMock) as mock_handler:
        await workflow_manager.handle_update(update, mock_context)
        mock_handler.assert_awaited_once_with(update, mock_context, TEST_USER_ID, active_case)

@pytest.mark.asyncio
async def test_handle_update_resets_if_collection_but_no_case_id(workflow_manager, mock_state_manager, mock_telegram_client):
    mock_state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_state_manager.get_active_case_id.return_value = None # Simulate missing case ID
    update = create_mock_update(TEST_USER_ID, text="should not process")
    with patch.object(workflow_manager, 'handle_evidence_collection_state', new_callable=AsyncMock) as mock_handler:
         with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
              await workflow_manager.handle_update(update, mock_context)
              mock_handler.assert_not_awaited() # Should not reach collection handler
              mock_state_manager.set_state.assert_called_once_with(AppState.IDLE) # Should reset state
              mock_telegram_client.send_message.assert_any_call(TEST_USER_ID, "Error: Lost active case context. Returning to main menu.")
              mock_show_menu.assert_awaited_once_with(TEST_USER_ID) # Should show idle menu

# --- Test handle_idle_state --- 

@pytest.mark.asyncio
async def test_idle_state_handles_start_command(workflow_manager, mock_telegram_client):
    update = create_mock_update(TEST_USER_ID, text="/start")
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
         await workflow_manager.handle_idle_state(update, mock_context, TEST_USER_ID)
         mock_show_menu.assert_awaited_once_with(TEST_USER_ID)

@pytest.mark.asyncio
async def test_idle_state_handles_start_new_case_button(workflow_manager, mock_state_manager):
    update = create_mock_update(TEST_USER_ID, callback_data="start_new_case")
    with patch.object(workflow_manager, 'start_new_case_workflow', new_callable=AsyncMock) as mock_start_workflow:
        await workflow_manager.handle_idle_state(update, mock_context, TEST_USER_ID)
        update.callback_query.answer.assert_awaited_once()
        mock_start_workflow.assert_awaited_once_with(TEST_USER_ID, update.callback_query.message.message_id)

@pytest.mark.asyncio
async def test_idle_state_ignores_other_text(workflow_manager, mock_telegram_client):
    update = create_mock_update(TEST_USER_ID, text="hello bot")
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
        await workflow_manager.handle_idle_state(update, mock_context, TEST_USER_ID)
        mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, "Use the button to start a new case, or /help.")
        mock_show_menu.assert_awaited_once_with(TEST_USER_ID)

@pytest.mark.asyncio
async def test_idle_state_ignores_other_callbacks(workflow_manager, mock_telegram_client):
    update = create_mock_update(TEST_USER_ID, callback_data="other_callback")
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
        await workflow_manager.handle_idle_state(update, mock_context, TEST_USER_ID)
        update.callback_query.answer.assert_awaited_once()
        mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, "Invalid action.")
        mock_show_menu.assert_awaited_once_with(TEST_USER_ID)

# --- Test start_new_case_workflow --- 

@pytest.mark.asyncio
async def test_start_new_case_workflow_success(workflow_manager, mock_state_manager, mock_telegram_client):
    message_id_to_edit = 67890
    await workflow_manager.start_new_case_workflow(TEST_USER_ID, message_id_to_edit)
    # Verify state transition
    mock_state_manager.set_state.assert_called_once_with(AppState.WAITING_FOR_PDF)
    # Verify message edit
    mock_telegram_client.edit_message_text.assert_awaited_once()
    call_args = mock_telegram_client.edit_message_text.await_args
    assert call_args.kwargs['chat_id'] == TEST_USER_ID
    assert call_args.kwargs['message_id'] == message_id_to_edit
    assert "Please send the occurrence PDF" in call_args.kwargs['text']
    assert call_args.kwargs['reply_markup'] is not None
    # Check button data
    button = call_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.text == "❌ Cancel"
    assert button.callback_data == "cancel_new_case"

@pytest.mark.asyncio
async def test_start_new_case_workflow_state_transition_fails(workflow_manager, mock_state_manager, mock_telegram_client):
    mock_state_manager.set_state.return_value = False # Simulate failure
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
         await workflow_manager.start_new_case_workflow(TEST_USER_ID)
         mock_state_manager.set_state.assert_called_once_with(AppState.WAITING_FOR_PDF)
         mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, "Could not start the new case process. Please try again.")
         mock_show_menu.assert_awaited_once_with(TEST_USER_ID)
         mock_telegram_client.edit_message_text.assert_not_awaited()

# --- Test handle_waiting_for_pdf_state --- 

@pytest.mark.asyncio
async def test_waiting_state_handles_cancel_button(workflow_manager, mock_state_manager, mock_telegram_client):
    update = create_mock_update(TEST_USER_ID, callback_data="cancel_new_case")
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
        await workflow_manager.handle_waiting_for_pdf_state(update, mock_context, TEST_USER_ID)
        update.callback_query.answer.assert_awaited_once()
        mock_state_manager.set_state.assert_called_once_with(AppState.IDLE)
        mock_telegram_client.edit_message_text.assert_awaited_once_with(
            chat_id=TEST_USER_ID,
            message_id=update.callback_query.message.message_id,
            text="Cancelled. Returning to main menu.",
            reply_markup=None
        )
        mock_show_menu.assert_awaited_once_with(TEST_USER_ID)

@pytest.mark.asyncio
async def test_waiting_state_handles_pdf_document(workflow_manager):
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.mime_type = 'application/pdf'
    mock_pdf.file_id = "FILEID123"
    mock_pdf.file_unique_id = "UNIQUE123"
    update = create_mock_update(TEST_USER_ID, document=mock_pdf)
    with patch.object(workflow_manager, 'process_pdf_input', new_callable=AsyncMock) as mock_process_pdf:
        await workflow_manager.handle_waiting_for_pdf_state(update, mock_context, TEST_USER_ID)
        mock_process_pdf.assert_awaited_once_with(TEST_USER_ID, mock_pdf, update.message.message_id)

@pytest.mark.asyncio
async def test_waiting_state_ignores_non_pdf_document(workflow_manager, mock_telegram_client):
    mock_doc = MagicMock(spec=Document)
    mock_doc.mime_type = 'image/jpeg'
    update = create_mock_update(TEST_USER_ID, document=mock_doc)
    with patch.object(workflow_manager, 'process_pdf_input', new_callable=AsyncMock) as mock_process_pdf:
        await workflow_manager.handle_waiting_for_pdf_state(update, mock_context, TEST_USER_ID)
        mock_process_pdf.assert_not_awaited()
        mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, "Please send a PDF file or click Cancel.")

@pytest.mark.asyncio
async def test_waiting_state_ignores_other_text(workflow_manager, mock_telegram_client):
    update = create_mock_update(TEST_USER_ID, text="Is this ready?")
    with patch.object(workflow_manager, 'process_pdf_input', new_callable=AsyncMock) as mock_process_pdf:
        await workflow_manager.handle_waiting_for_pdf_state(update, mock_context, TEST_USER_ID)
        mock_process_pdf.assert_not_awaited()
        mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, "Please send a PDF file or click Cancel.")

# --- Test process_pdf_input (Placeholder) --- 

@pytest.mark.asyncio
async def test_process_pdf_input_success_placeholder(workflow_manager, mock_state_manager, mock_telegram_client, mock_case_manager):
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.file_id = "FILEID456"
    mock_pdf.file_unique_id = "UNIQUE456"
    mock_pdf.file_name = "test.pdf"
    message_id = 11223

    # Set up mock processing message
    mock_processing_msg = MagicMock()
    mock_processing_msg.message_id = message_id
    mock_telegram_client.send_message.return_value = mock_processing_msg

    # Mock the download_file method to return a tuple (content, error)
    mock_telegram_client.download_file.return_value = (b"%PDF test data", None)

    # Mock the case info object for extract_pdf_info
    mock_case_info = MagicMock()
    mock_case_info.case_id = "test-case-123"
    mock_case_info.get_display_id.return_value = "123/2023"
    mock_case_info.coordinates = (-16.123, -40.456)
    mock_case_info.address = "Test Address"
    mock_case_info.llm_summary = None
    mock_case_info.llm_checklist = None
    
    # Set the mock return value for extract_pdf_info
    mock_case_manager.extract_pdf_info.return_value = mock_case_info
    
    # Add _generate_case_id method to the WorkflowManager instance for this test
    workflow_manager._generate_case_id = MagicMock(return_value="test-case-123")
    
    # Mock other async methods
    workflow_manager.create_case_status_message = AsyncMock(return_value=123456)
    workflow_manager.send_evidence_prompt = AsyncMock()

    await workflow_manager.process_pdf_input(TEST_USER_ID, mock_pdf, message_id)

    # Verify download was called
    mock_telegram_client.download_file.assert_awaited_once_with(mock_pdf.file_id)
    
    # Verify case creation 
    mock_case_manager.create_case.assert_called_once()
    
    # Verify save_pdf_file was called
    mock_case_manager.save_pdf_file.assert_awaited_once()
    
    # Verify extract_pdf_info was called
    mock_case_manager.extract_pdf_info.assert_called_once()
    
    # Verify state was set correctly
    mock_state_manager.set_state.assert_any_call(
        AppState.EVIDENCE_COLLECTION, 
        active_case_id="test-case-123"
    )

@pytest.mark.asyncio
async def test_process_pdf_input_state_transition_fails(workflow_manager, mock_state_manager, mock_telegram_client, mock_case_manager):
    mock_pdf = MagicMock(spec=Document)
    mock_pdf.file_id = "FILEID789"
    mock_pdf.file_unique_id = "UNIQUE789"
    mock_pdf.file_name = "test.pdf"
    message_id = 11223

    # Set up mock processing message
    mock_processing_msg = MagicMock()
    mock_processing_msg.message_id = message_id
    mock_telegram_client.send_message.return_value = mock_processing_msg

    # Mock the download_file method to return a tuple (content, error)
    mock_telegram_client.download_file.return_value = (b"%PDF test data", None)

    # Mock the case info object for extract_pdf_info
    mock_case_info = MagicMock()
    mock_case_info.case_id = "test-case-456"
    mock_case_info.get_display_id.return_value = "456/2023"
    
    # Set the mock return value for extract_pdf_info
    mock_case_manager.extract_pdf_info.return_value = mock_case_info
    
    # Mock the case_manager.create_case method with specific case ID
    mock_case_manager.create_case.return_value = Path("/fake/path/test-case-456")
    
    # Add _generate_case_id method to the WorkflowManager instance for this test
    workflow_manager._generate_case_id = MagicMock(return_value="test-case-456")

    # Simulate state transition failure
    mock_state_manager.set_state.side_effect = [
        # First call is for setting to EVIDENCE_COLLECTION, which fails
        False,
        # Second call is for fallback to IDLE, which succeeds
        True
    ]

    await workflow_manager.process_pdf_input(TEST_USER_ID, mock_pdf, message_id)

    # Verify attempted state transition
    mock_state_manager.set_state.assert_any_call(
        AppState.EVIDENCE_COLLECTION, 
        active_case_id="test-case-456"
    )
    
    # Verify case was deleted after failure
    mock_case_manager.delete_case.assert_called_once_with("test-case-456")

# --- Test handle_evidence_collection_state (Placeholder) --- 

@pytest.mark.asyncio
async def test_collection_state_handles_finish_button(workflow_manager):
    case_id = "CASE-COLLECT-1"
    update = create_mock_update(TEST_USER_ID, callback_data=f"finish_collection_{case_id}")
    with patch.object(workflow_manager, 'finish_collection_workflow', new_callable=AsyncMock) as mock_finish:
        # Assuming the state is already correctly EVIDENCE_COLLECTION with case_id
        # If not, setup would be needed here via workflow_manager.state_manager
        await workflow_manager.handle_evidence_collection_state(update, mock_context, TEST_USER_ID, case_id)
        update.callback_query.answer.assert_awaited_once()
        mock_finish.assert_awaited_once_with(TEST_USER_ID, case_id)

@pytest.mark.asyncio
async def test_collection_state_handles_finish_button_wrong_case(workflow_manager, mock_telegram_client):
    case_id = "CASE-COLLECT-WRONG-1"
    wrong_case_id = "CASE-COLLECT-WRONG-2"
    update = create_mock_update(TEST_USER_ID, callback_data=f"finish_collection_{wrong_case_id}")
    
    # Mock state manager via workflow_manager
    workflow_manager.state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    workflow_manager.state_manager.get_active_case_id.return_value = case_id
    
    with patch.object(workflow_manager, 'finish_collection_workflow', new_callable=AsyncMock) as mock_finish:
        await workflow_manager.handle_update(update, mock_context)
        update.callback_query.answer.assert_awaited_with("Case ID mismatch. Please try again.")
        mock_finish.assert_not_awaited()

@pytest.mark.asyncio
async def test_collection_state_handles_text_evidence(workflow_manager, mock_telegram_client):
    case_id = "CASE-COLLECT-TXT"
    update = create_mock_update(TEST_USER_ID, text="This is text evidence.")
    
    # Set up state via workflow_manager's state_manager
    workflow_manager.state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    workflow_manager.state_manager.get_active_case_id.return_value = case_id
    
    # Mock case_manager.add_case_note to simulate adding a note
    workflow_manager.case_manager.add_case_note.return_value = "text123"
    
    # Patch other necessary methods
    with patch.object(workflow_manager, 'create_case_status_message', return_value=None), \
         patch.object(workflow_manager, 'send_evidence_prompt', new_callable=AsyncMock) as mock_prompt:
    
        # Call handle_update
        await workflow_manager.handle_update(update, mock_context)

        # Verify internal calls (Original Assertions)
        workflow_manager.case_manager.add_case_note.assert_called_once_with(
            case_id, text_content="This is text evidence."
        )
        mock_telegram_client.send_message.assert_any_call(
            TEST_USER_ID, "💬 Note added to case. Text note added successfully."
        )
        mock_prompt.assert_called()

@pytest.mark.asyncio
async def test_collection_state_handles_photo_evidence(workflow_manager, mock_telegram_client):
    case_id = "CASE-COLLECT-IMG"
    mock_photo = [MagicMock(spec=PhotoSize)]
    mock_photo[-1].file_unique_id = "UNIQUEPIC1"
    mock_photo[-1].file_id = "FILEPIC1"
    update = create_mock_update(TEST_USER_ID, photo=mock_photo)
    
    # Set up state via workflow_manager's state_manager
    workflow_manager.state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    workflow_manager.state_manager.get_active_case_id.return_value = case_id
    
    # Mock download_file and add_photo_evidence
    mock_telegram_client.download_file.return_value = (b'photo_data_bytes', None)
    workflow_manager.case_manager.add_photo_evidence.return_value = "photo123"
    
    # Patch other necessary methods
    with patch.object(workflow_manager, 'create_case_status_message', return_value=None), \
         patch.object(workflow_manager, 'update_case_status_message', new_callable=AsyncMock) as mock_update_status, \
         patch.object(workflow_manager, 'send_evidence_prompt', new_callable=AsyncMock) as mock_send_prompt:
        
        # Call handle_update
        await workflow_manager.handle_update(update, mock_context)

        # Verify internal calls
        mock_telegram_client.download_file.assert_awaited_once_with(mock_photo[-1].file_id)
        workflow_manager.case_manager.add_photo_evidence.assert_called_once_with(
            case_id, b'photo_data_bytes'
        )
        mock_telegram_client.send_message.assert_any_call(
            TEST_USER_ID, "📷 Photo added to case evidence."
        )
        fingerprint_call_found = False
        for call_args in mock_telegram_client.send_message.await_args_list:
            args, kwargs = call_args
            if len(args) > 1 and isinstance(args[1], str) and "Is this a fingerprint photo?" in args[1]:
                assert isinstance(kwargs.get('reply_markup'), InlineKeyboardMarkup)
                fingerprint_call_found = True
                break
        assert fingerprint_call_found, "Fingerprint confirmation message not found or malformed."
        mock_update_status.assert_called()

@pytest.mark.asyncio
async def test_collection_state_handles_fingerprint_button(workflow_manager, mock_telegram_client):
    case_id = "CASE-FP-BTN"
    evidence_id = "photo123"
    update = create_mock_update(TEST_USER_ID, callback_data=f"fingerprint_yes_{evidence_id}")

    # Mock state manager via workflow_manager
    workflow_manager.state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    workflow_manager.state_manager.get_active_case_id.return_value = case_id

    # Mock metadata update success
    workflow_manager.case_manager.update_evidence_metadata.return_value = True

    with patch.object(workflow_manager, 'send_evidence_prompt', new_callable=AsyncMock) as mock_prompt:
        await workflow_manager.handle_update(update, mock_context)

        # Verify callback answer
        update.callback_query.answer.assert_awaited_with("Evidence metadata updated.")

        # Verify metadata update call
        workflow_manager.case_manager.update_evidence_metadata.assert_called_once_with(
            case_id, evidence_id, {"is_fingerprint": True}
        )

        # Verify prompt was sent again
        mock_prompt.assert_awaited_once_with(TEST_USER_ID, case_id)

@pytest.mark.asyncio
async def test_collection_state_handles_voice_evidence(workflow_manager, mock_telegram_client):
    case_id = "CASE-COLLECT-AUD"
    mock_voice = MagicMock(spec=Voice)
    mock_voice.file_unique_id = "UNIQUEAUD1"
    mock_voice.file_id = "FILEAUD1"
    mock_voice.duration = 5
    update = create_mock_update(TEST_USER_ID, voice=mock_voice)
    
    # Set up state via workflow_manager's state_manager
    workflow_manager.state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    workflow_manager.state_manager.get_active_case_id.return_value = case_id
    
    # Mock required functions
    mock_telegram_client.download_file.return_value = (b'audio_data_bytes', None)  # Fix: Return tuple
    mock_processing_msg = MagicMock(spec=Message, message_id=12345)
    mock_telegram_client.send_message.return_value = mock_processing_msg
    workflow_manager.case_manager.add_case_note.return_value = "audio123"
    mock_temp_file = MagicMock()
    mock_temp_file.name = '/tmp/temp_audio.ogg'
    mock_temp_file.__enter__.return_value = mock_temp_file
    mock_temp_file.__exit__.return_value = None
    
    # Mock the transcribe method
    mock_whisper_transcribe = MagicMock(return_value="This is the transcription")
    workflow_manager.whisper_api.transcribe = mock_whisper_transcribe
    
    # Patch other necessary methods
    with patch('tempfile.NamedTemporaryFile', return_value=mock_temp_file), \
         patch('os.unlink'), \
         patch.object(workflow_manager, 'update_case_status_message', new_callable=AsyncMock) as mock_update_status, \
         patch.object(workflow_manager, 'send_evidence_prompt', new_callable=AsyncMock) as mock_prompt:
        
        # Call handle_update
        await workflow_manager.handle_update(update, mock_context)
        
        # Verify internal calls
        mock_telegram_client.download_file.assert_awaited_once_with(mock_voice.file_id)
        mock_whisper_transcribe.assert_called_once_with('/tmp/temp_audio.ogg')
        workflow_manager.case_manager.add_case_note.assert_called_once_with(
            case_id,
            text_content="This is the transcription",
            audio_data=b'audio_data_bytes',
            duration_seconds=5
        )

# --- Test finish_collection_workflow (Placeholder) --- 

@pytest.mark.asyncio
async def test_finish_collection_workflow_success(workflow_manager, mock_state_manager, mock_telegram_client):
    case_id = "CASE-FINISH-1"
    mock_state_manager.get_active_case_id.return_value = case_id # Ensure current case matches
    
    # Ensure load_case returns None to avoid the second formatted message
    workflow_manager.case_manager.load_case.return_value = None
    
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
         await workflow_manager.finish_collection_workflow(TEST_USER_ID, case_id)
         # Check finalize_case called with potentially None year parameter
         workflow_manager.case_manager.finalize_case.assert_called_once_with(case_id, None)
         mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, f"✅ Evidence collection finished for Case {case_id}.")
         mock_state_manager.set_state.assert_called_once_with(AppState.IDLE)
         mock_show_menu.assert_awaited_once_with(TEST_USER_ID)

@pytest.mark.asyncio
async def test_finish_collection_workflow_wrong_case(workflow_manager, mock_state_manager, mock_telegram_client):
    case_id = "CASE-FINISH-1"
    current_active_case = "CASE-ACTIVE-DIFFERENT"
    mock_state_manager.get_active_case_id.return_value = current_active_case
    
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
         await workflow_manager.finish_collection_workflow(TEST_USER_ID, case_id)
         mock_telegram_client.send_message.assert_awaited_once_with(TEST_USER_ID, "Error: Cannot finish collection for an inactive or different case.")
         mock_state_manager.set_state.assert_not_called() # State should not change
         mock_show_menu.assert_not_awaited()

@pytest.mark.asyncio
async def test_finish_collection_workflow_state_fails(workflow_manager, mock_state_manager, mock_telegram_client):
    case_id = "CASE-FINISH-FAIL"
    mock_state_manager.get_active_case_id.return_value = case_id
    mock_state_manager.set_state.return_value = False # Simulate failure
    
    with patch.object(workflow_manager, 'show_idle_menu', new_callable=AsyncMock) as mock_show_menu:
         await workflow_manager.finish_collection_workflow(TEST_USER_ID, case_id)
         # Confirmation message should still be sent before state change attempt
         mock_telegram_client.send_message.assert_any_call(TEST_USER_ID, f"✅ Evidence collection finished for Case {case_id}.")
         # Error message specific to state change failure
         mock_telegram_client.send_message.assert_any_call(TEST_USER_ID, "Error finalizing case state. Returning to main menu.")
         mock_state_manager.set_state.assert_called_once_with(AppState.IDLE)
         mock_show_menu.assert_awaited_once_with(TEST_USER_ID) # Should still show menu 

def test_generate_case_id_format(workflow_manager):
    """Test that case IDs are generated with the correct format."""
    # Generate a case ID
    case_id = workflow_manager._generate_case_id()
    
    # Check format: PREFIX_XXXXX_XXXX_YEAR (where XXXXX is 5 digits, XXXX is 4 digits)
    parts = case_id.split('_')
    
    # Verify there are 4 parts
    assert len(parts) == 4, f"Case ID should have 4 parts separated by underscores, got: {case_id}"
    
    # Verify the prefix is as expected (default or from environment)
    import os
    expected_prefix = os.environ.get("CASE_ID_PREFIX", "SEPPATRI").split('#')[0].strip()
    assert parts[0] == expected_prefix, f"Expected prefix {expected_prefix}, got: {parts[0]}"
    
    # Verify case number is 5 digits
    assert len(parts[1]) == 5 and parts[1].isdigit(), f"Case number should be 5 digits, got: {parts[1]}"
    
    # Verify report number is 4 digits
    assert len(parts[2]) == 4 and parts[2].isdigit(), f"Report number should be 4 digits, got: {parts[2]}"
    
    # Verify year is the current year
    from datetime import datetime
    assert parts[3] == str(datetime.now().year), f"Year should be {datetime.now().year}, got: {parts[3]}"

def test_generate_case_id_with_custom_prefix(workflow_manager):
    """Test case ID generation with a custom prefix from environment variable."""
    import os
    
    # Save original environment variable if it exists
    original_prefix = os.environ.get("CASE_ID_PREFIX")
    
    try:
        # Set a custom prefix
        os.environ["CASE_ID_PREFIX"] = "TESTPREFIX"
        
        # Generate a case ID with the custom prefix
        case_id = workflow_manager._generate_case_id()
        
        # Verify the prefix is used
        assert case_id.startswith("TESTPREFIX_"), f"Case ID should start with TESTPREFIX_, got: {case_id}"
    finally:
        # Restore original environment variable or remove it
        if original_prefix is not None:
            os.environ["CASE_ID_PREFIX"] = original_prefix
        else:
            os.environ.pop("CASE_ID_PREFIX", None) 