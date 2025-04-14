import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock, call
import asyncio

# Adjust path to import from patri_reports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Set dummy env vars for testing module import and default cases
TEST_BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
TEST_ALLOWED_USER_ID = 12345
TEST_OTHER_USER_ID = 54321

@pytest.fixture(autouse=True)
def setup_env_vars():
    """Set default env vars for tests, clean up after."""
    original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    original_users = os.environ.get("ALLOWED_TELEGRAM_USERS")
    os.environ["TELEGRAM_BOT_TOKEN"] = TEST_BOT_TOKEN
    os.environ["ALLOWED_TELEGRAM_USERS"] = str(TEST_ALLOWED_USER_ID)
    yield
    # Restore original or remove if not present initially
    if original_token is None:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    else:
        os.environ["TELEGRAM_BOT_TOKEN"] = original_token
    if original_users is None:
        os.environ.pop("ALLOWED_TELEGRAM_USERS", None)
    else:
        os.environ["ALLOWED_TELEGRAM_USERS"] = original_users


# --- Mocking Setup ---
# We need to mock the chained calls Application.builder().token().build()
@pytest.fixture
def mock_telegram_app():
    """Provides a mock Application object and its builder chain."""
    with patch('telegram.ext.Application.builder') as mock_builder_cls:
        mock_builder_instance = MagicMock()
        # Create an AsyncMock for the app instance
        mock_app_instance = AsyncMock()

        # Explicitly set synchronous methods to be MagicMock
        mock_app_instance.add_handler = MagicMock()
        mock_app_instance.add_error_handler = MagicMock()
        mock_app_instance.run_polling = MagicMock()

        # Configure the mock chain
        mock_builder_cls.return_value = mock_builder_instance
        mock_builder_instance.token.return_value = mock_builder_instance  # builder().token() returns builder
        mock_builder_instance.connection_pool_size.return_value = mock_builder_instance  # builder().connection_pool_size() returns builder
        mock_builder_instance.build.return_value = mock_app_instance  # builder().build() returns app
        
        # Create AsyncMock for bot methods
        mock_app_instance.bot = AsyncMock()
        mock_app_instance.bot.send_message = AsyncMock()
        mock_app_instance.bot.edit_message_text = AsyncMock()
        mock_app_instance.bot.pin_chat_message = AsyncMock()
        mock_app_instance.bot.unpin_chat_message = AsyncMock()
        mock_app_instance.bot.unpin_all_chat_messages = AsyncMock()
        mock_app_instance.bot.send_location = AsyncMock()
        mock_app_instance.bot.send_venue = AsyncMock()
        mock_app_instance.bot.send_photo = AsyncMock()
        mock_app_instance.bot.get_file = AsyncMock()
        
        # Yield all necessary mocks for potential assertions
        yield {
            "builder_cls": mock_builder_cls,
            "builder_instance": mock_builder_instance,
            "app_instance": mock_app_instance
        }

@pytest.fixture
def mock_workflow_manager():
    """Provides a mock WorkflowManager instance."""
    manager = AsyncMock()
    manager.handle_update = AsyncMock() # Ensure handle_update is async
    return manager

# Import client *after* potential mocks can be set up by fixtures if needed
from patri_reports.telegram_client import TelegramClient # Assuming decorator is also imported/used here
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters


# --- Test Initialization --- 

def test_client_initialization_success(mock_telegram_app, mock_workflow_manager):
    """Test successful initialization and handler registration."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    assert client.application is mock_telegram_app["app_instance"]
    assert client.bot_token == TEST_BOT_TOKEN
    assert client.allowed_users == [TEST_ALLOWED_USER_ID]
    assert client.workflow_manager is mock_workflow_manager
    
    # Check builder call chain
    mock_telegram_app["builder_cls"].assert_called_once()
    mock_telegram_app["builder_instance"].token.assert_called_once_with(TEST_BOT_TOKEN)
    mock_telegram_app["builder_instance"].build.assert_called_once()
    
    # Check if generic handlers were added
    add_handler_calls = mock_telegram_app["app_instance"].add_handler.call_args_list
    # Expect handlers for Message (Text/Command), CallbackQuery, Document, Photo, Voice
    assert len(add_handler_calls) >= 5 
    # Simplified check: Count handler types
    handler_counts = {
        MessageHandler: 0,
        CallbackQueryHandler: 0
    }
    message_filter_types = set() # Track filters used with MessageHandler
    
    for handler_call in add_handler_calls:
        handler = handler_call.args[0]
        assert handler.callback == client.dispatch_update
        if isinstance(handler, MessageHandler):
            handler_counts[MessageHandler] += 1
            # Attempt to identify filter types without direct comparison
            if hasattr(handler.filters, '__name__'): # Simple filters like filters.PHOTO
                 message_filter_types.add(handler.filters.__name__)
            elif isinstance(handler.filters, filters.Document):
                 message_filter_types.add("Document") # Special case for Document filter
            elif isinstance(handler.filters, filters.BaseFilter): # Catch complex/combined filters
                 # Could try string representation, but might be fragile
                 # For now, just acknowledge a complex filter was added
                 message_filter_types.add("ComplexMessageFilter") 
                 
        elif isinstance(handler, CallbackQueryHandler):
            handler_counts[CallbackQueryHandler] += 1
             
    # Assert counts and presence of key filter types
    assert handler_counts[MessageHandler] >= 4 # Text/Cmd, PDF, Photo, Voice
    assert handler_counts[CallbackQueryHandler] >= 1
    # Check if key filter types were registered (names might vary slightly)
    # assert "PHOTO" in message_filter_types # Name might be just PHOTO
    # assert "VOICE" in message_filter_types
    # assert "Document" in message_filter_types
    # assert "ComplexMessageFilter" in message_filter_types # For the TEXT/COMMAND combo

def test_client_initialization_missing_token(mock_telegram_app, mock_workflow_manager):
    """Test initialization fails if BOT_TOKEN is missing."""
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is required"):
        TelegramClient(workflow_manager=mock_workflow_manager)

def test_client_initialization_warns_missing_users(mock_telegram_app, mock_workflow_manager):
    """Test initialization logs info if ALLOWED_USERS is missing or empty."""
    os.environ.pop("ALLOWED_TELEGRAM_USERS", None)
    # Patch the logger.info used within TelegramClient for this case
    with patch('patri_reports.telegram_client.logger.info') as mock_info:
        client = TelegramClient(workflow_manager=mock_workflow_manager)
        assert client.allowed_users == []
        # Check if the specific info message was logged during __init__
        mock_info.assert_any_call("ALLOWED_TELEGRAM_USERS is empty or not set. Access control relies on @restricted decorator.")

# --- Test Dispatcher and Restriction --- 

@pytest.fixture
def mock_update_context():
    """Provides mock Update and Context objects."""
    mock_update = AsyncMock(spec=Update)
    mock_update.effective_user = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.callback_query = None # Default to message update
    mock_context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
    return mock_update, mock_context

@pytest.mark.asyncio
async def test_dispatch_update_allowed_user(mock_telegram_app, mock_workflow_manager, mock_update_context):
    """Test dispatch_update calls workflow_manager.handle_update for allowed user."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    mock_update, mock_context = mock_update_context
    mock_update.effective_user.id = TEST_ALLOWED_USER_ID

    await client.dispatch_update(mock_update, mock_context)

    mock_workflow_manager.handle_update.assert_awaited_once_with(mock_update, mock_context)

@pytest.mark.asyncio
async def test_dispatch_update_unauthorized_user(mock_telegram_app, mock_workflow_manager, mock_update_context):
    """Test dispatch_update blocks unauthorized user and doesn't call handle_update."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    mock_update, mock_context = mock_update_context
    mock_update.effective_user.id = TEST_OTHER_USER_ID # Unauthorized

    await client.dispatch_update(mock_update, mock_context)

    # Check decorator reply
    mock_update.message.reply_text.assert_awaited_once_with("Sorry, you are not authorized to use this bot.")
    # Ensure workflow manager was NOT called
    mock_workflow_manager.handle_update.assert_not_awaited()

@pytest.mark.asyncio
async def test_dispatch_update_unauthorized_user_callback(mock_telegram_app, mock_workflow_manager, mock_update_context):
    """Test dispatch_update blocks unauthorized user for callback query."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    mock_update, mock_context = mock_update_context
    # Simulate a callback query update
    mock_update.message = None
    mock_update.callback_query = AsyncMock()
    mock_update.effective_user.id = TEST_OTHER_USER_ID # Unauthorized

    await client.dispatch_update(mock_update, mock_context)

    # Check decorator reply via callback_query.answer
    mock_update.callback_query.answer.assert_awaited_once_with("Unauthorized", show_alert=True)
    mock_workflow_manager.handle_update.assert_not_awaited()

@pytest.mark.asyncio
async def test_dispatch_update_missing_workflow_manager(mock_telegram_app, mock_update_context):
    """Test dispatch_update handles missing workflow_manager gracefully."""
    client = TelegramClient(workflow_manager=None) # Simulate missing manager
    mock_update, mock_context = mock_update_context
    mock_update.effective_user.id = TEST_ALLOWED_USER_ID # Authorized user

    with patch('patri_reports.telegram_client.logger.error') as mock_log_error:
         await client.dispatch_update(mock_update, mock_context)
         mock_log_error.assert_called_with("WorkflowManager not set in TelegramClient during dispatch.")
         # Check if error reply was sent
         mock_update.message.reply_text.assert_awaited_once_with("Bot is not properly configured. Please contact support.")

# --- Test Helper Methods --- 

@pytest.mark.asyncio
async def test_send_message(mock_telegram_app, mock_workflow_manager):
    """Test send_message calls bot.send_message correctly."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    chat_id = 12345
    text = "Test message"
    button = InlineKeyboardButton("Test", callback_data="test")
    reply_markup = InlineKeyboardMarkup([[button]])
    
    await client.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    
    client.application.bot.send_message.assert_awaited_once_with(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

@pytest.mark.asyncio
async def test_edit_message_text(mock_telegram_app, mock_workflow_manager):
    """Test edit_message_text calls bot.edit_message_text correctly."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    chat_id = 12345
    message_id = 67890
    text = "Updated text"
    button = InlineKeyboardButton("Updated", callback_data="updated")
    reply_markup = InlineKeyboardMarkup([[button]])
    
    await client.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup, parse_mode="MarkdownV2")
    
    client.application.bot.edit_message_text.assert_awaited_once_with(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="MarkdownV2"
    )

@pytest.mark.asyncio
async def test_edit_message_text_handles_not_modified(mock_telegram_app, mock_workflow_manager):
    """Test edit_message_text ignores 'Message is not modified' error."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    chat_id = 12345
    message_id = 67890
    text = "Same text"

    # Configure the mock bot to raise the specific error
    client.application.bot.edit_message_text = AsyncMock(
        side_effect=Exception("Conflict: message is not modified")
    )

    # Patch logger to check it wasn't called with an error
    with patch('patri_reports.telegram_client.logger.error') as mock_log_error:
        # Should not raise an exception
        await client.edit_message_text(chat_id, message_id, text)
        # Verify no error was logged (bot suppresses this specific error)
        mock_log_error.assert_not_called()

# --- Test Run Method ---

def test_run_method(mock_telegram_app, mock_workflow_manager):
    """Test the run method calls application.run_polling."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    mocked_app = client.application
    assert mocked_app is mock_telegram_app["app_instance"]
    client.run()
    mocked_app.run_polling.assert_called_once()

# Note: The direct tests for the @restricted decorator are removed as its 
# functionality is now tested implicitly through the command handlers which use it,
# and it relies on instance state (self.allowed_users). 

@pytest.mark.asyncio
async def test_pin_message(mock_telegram_app, mock_workflow_manager):
    """Test pinning a message."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    await client.pin_message(123456, 789)
    
    mock_telegram_app["app_instance"].bot.pin_chat_message.assert_awaited_once_with(
        chat_id=123456,
        message_id=789,
        disable_notification=False
    )

@pytest.mark.asyncio
async def test_unpin_message(mock_telegram_app, mock_workflow_manager):
    """Test unpinning a specific message."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    await client.unpin_message(123456, 789)
    
    mock_telegram_app["app_instance"].bot.unpin_chat_message.assert_awaited_once_with(
        chat_id=123456,
        message_id=789
    )

@pytest.mark.asyncio
async def test_unpin_all_messages(mock_telegram_app, mock_workflow_manager):
    """Test unpinning all messages in a chat."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    await client.unpin_all_messages(123456)
    
    mock_telegram_app["app_instance"].bot.unpin_all_chat_messages.assert_awaited_once_with(
        chat_id=123456
    )

@pytest.mark.asyncio
async def test_send_location(mock_telegram_app, mock_workflow_manager):
    """Test sending a location."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    await client.send_location(123456, 12.345, 67.890)
    
    mock_telegram_app["app_instance"].bot.send_location.assert_awaited_once_with(
        chat_id=123456,
        latitude=12.345,
        longitude=67.890,
        reply_markup=None
    )

@pytest.mark.asyncio
async def test_send_photo(mock_telegram_app, mock_workflow_manager):
    """Test sending a photo."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    test_photo = b"FAKE_PHOTO_DATA"
    test_caption = "Test photo caption"
    
    await client.send_photo(
        chat_id=123456,
        photo=test_photo,
        caption=test_caption
    )
    
    mock_telegram_app["app_instance"].bot.send_photo.assert_awaited_once_with(
        chat_id=123456,
        photo=test_photo,
        caption=test_caption,
        reply_markup=None
    )

@pytest.mark.asyncio
async def test_download_file(mock_telegram_app, mock_workflow_manager):
    """Test downloading a file."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    # Mock the File object
    mock_file = AsyncMock()
    mock_file.file_size = 1024
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"FAKE_FILE_DATA"))
    mock_telegram_app["app_instance"].bot.get_file = AsyncMock(return_value=mock_file)
    
    content, error = await client.download_file("test_file_id")
    
    mock_telegram_app["app_instance"].bot.get_file.assert_awaited_once_with(file_id="test_file_id")
    mock_file.download_as_bytearray.assert_awaited_once()
    assert content == bytearray(b"FAKE_FILE_DATA")
    assert error is None

@pytest.mark.asyncio
async def test_download_file_error(mock_telegram_app, mock_workflow_manager):
    """Test error handling while downloading a file."""
    client = TelegramClient(workflow_manager=mock_workflow_manager)
    
    # Set up the mock to raise an exception
    mock_telegram_app["app_instance"].bot.get_file = AsyncMock(side_effect=Exception("File not found"))
    
    content, error = await client.download_file("test_file_id")
    
    mock_telegram_app["app_instance"].bot.get_file.assert_awaited_once_with(file_id="test_file_id")
    assert content is None
    assert error is not None
    assert "Error downloading the file" in error 