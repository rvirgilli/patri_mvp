import logging
import os
import signal
import sys
import time
import asyncio
import socket
import platform
import uuid
import threading
from functools import wraps
from typing import Optional, Tuple, ClassVar

from telegram import Update, InlineKeyboardMarkup, Bot
# Import the base class for type checking if needed, but avoid generic alias
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext, CallbackQueryHandler
from telegram.error import TelegramError, NetworkError as TelegramNetworkError, TimedOut as TelegramTimedOut, Conflict as TelegramConflict

# Import error handling utils
from patri_reports.utils.error_handler import with_async_retry, NetworkError, TimeoutError, with_async_timeout, safe_api_call

# Assuming config is loaded elsewhere, e.g., in utils.config
# We will need access to BOT_TOKEN and ALLOWED_USERS
# from utils.config import BOT_TOKEN, ALLOWED_USERS
# For now, let's use placeholders or environment variables directly

logger = logging.getLogger(__name__)

# Authentication Decorator
def restricted(func):
    """Decorator to restrict access to allowed users based on ALLOWED_USERS in instance."""
    @wraps(func)
    async def wrapped(*args, **kwargs):
        # args[0] is self (the TelegramClient instance)
        # args[1] is update
        # args[2] is context (we don't strictly need to type-check it here)
        
        self_obj = None
        update_obj = None
        
        # Fix order of args which may vary by method
        for arg in args:
            if hasattr(arg, 'allowed_users') and isinstance(getattr(arg, 'allowed_users'), list):
                self_obj = arg
            elif isinstance(arg, Update):
                update_obj = arg
        
        if not self_obj:
            logger.error("Could not find TelegramClient instance in method args")
            return
            
        if not update_obj:
            logger.error("Could not find Update object in method args")
            return
            
        # Get the user_id from the update
        user_id = None
        if update_obj.effective_user:
            user_id = update_obj.effective_user.id
        
        if not user_id:
            logger.warning("Could not determine user_id from update")
            return
        
        # Get the allowed users list
        allowed_users_list = self_obj.allowed_users
        
        # Empty list means no restrictions (unless @restricted was applied)
        if not allowed_users_list:
            logger.warning("No ALLOWED_USERS list found in instance, but @restricted was applied")
            return await func(*args, **kwargs)

        if user_id not in allowed_users_list:
            logger.warning(f"Unauthorized access attempt by user_id: {user_id}")
            if update_obj.message:
                await update_obj.message.reply_text("Sorry, you are not authorized to use this bot.")
            elif update_obj.callback_query:
                await update_obj.callback_query.answer("Unauthorized", show_alert=True)
            return # Block execution
            
        # Call the original function/method with original args/kwargs
        return await func(*args, **kwargs)
    return wrapped

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown."""
    signal_name = "SIGINT" if sig == signal.SIGINT else "SIGTERM"
    logger.info(f"Received {signal_name} signal, initiating clean shutdown...")
    
    # Get the client instance if it exists
    client = TelegramClient._instance
    if client and client.is_running:
        logger.info("Stopping running Telegram client instance...")
        # Schedule the cleanup to run
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(client.async_cleanup())
        else:
            # Cannot use asyncio here, force exit after brief delay
            logger.info("No running event loop, forcing exit in 1 second...")
            threading.Timer(1.0, lambda: os._exit(0)).start()
    else:
        logger.info("No running client to stop")

class TelegramClient:
    # Singleton instance
    _instance: ClassVar[Optional['TelegramClient']] = None
    _initialized: ClassVar[bool] = False
    
    # Class-level counter to track number of instances created
    _instance_count = 0
    
    # Admin notification settings
    # Change this to your personal Telegram ID for monitoring
    ADMIN_CHAT_ID = None
    
    def __new__(cls, *args, **kwargs):
        """Implement singleton pattern to ensure only one client is created."""
        if cls._instance is None:
            logger.info("Creating new TelegramClient singleton instance")
            cls._instance = super(TelegramClient, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, workflow_manager: 'WorkflowManager', admin_chat_id: Optional[int] = None):
        """Initializes the Telegram Client."""
        # Skip initialization if already initialized
        if TelegramClient._initialized:
            logger.info("TelegramClient already initialized, skipping __init__")
            return
            
        # Increment instance counter
        TelegramClient._instance_count += 1
        logger.info(f"=== DEBUG: Creating TelegramClient instance #{TelegramClient._instance_count} ===")
        
        logger.info("TelegramClient.__init__ starting...") # DEBUG
        self.workflow_manager = workflow_manager
        
        # Store token name but don't create application yet
        # This prevents session conflicts when the class is imported/initialized multiple times
        self.bot_token = None  # Don't access token until needed
        allowed_users_str = os.getenv("ALLOWED_TELEGRAM_USERS", "")
        self.allowed_users = [int(user_id.strip()) for user_id in allowed_users_str.split(',') if user_id.strip().isdigit()]

        # Set admin chat ID from parameter
        self.ADMIN_CHAT_ID = admin_chat_id
        if self.ADMIN_CHAT_ID:
            logger.info(f"Admin notifications will be sent to ID: {self.ADMIN_CHAT_ID}")
        else:
            logger.info("Admin notifications disabled (admin_chat_id not provided)")

        # Connection settings for improved error handling
        self.NETWORK_RETRY_LIMIT = int(os.getenv("NETWORK_RETRY_LIMIT", "3"))
        self.NETWORK_RETRY_DELAY = int(os.getenv("NETWORK_RETRY_DELAY", "2"))
        self.FILE_DOWNLOAD_TIMEOUT = int(os.getenv("FILE_DOWNLOAD_TIMEOUT", "60"))
        
        # Status tracking
        self.is_running = False
        self.stop_event = asyncio.Event()
        
        # Warning for empty allowed_users is now handled inside the decorator if applied
        if self.allowed_users:
            logger.info(f"Bot restricted to users: {self.allowed_users}")
        else:
             logger.info("ALLOWED_TELEGRAM_USERS is empty or not set. Access control relies on @restricted decorator.")

        # Application will be created only when run() is called
        self.application = None
        
        # Mark as initialized
        TelegramClient._initialized = True
        logger.info("TelegramClient.__init__ finished.") # DEBUG
        
    def _initialize_application(self):
        """Initialize the application when needed - only called by run()."""
        if self.application:
            logger.info("Application already initialized")
            return
            
        # Get token only when needed
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            logger.critical("TELEGRAM_BOT_TOKEN environment variable not set!")
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
            
        # Using the default builder pattern with adjusted timeout values
        # Increase connection_pool_ttl for more stable connections
        logger.info("TelegramClient: Before Application.builder().build()...") # DEBUG
        self.application = Application.builder().token(self.bot_token).connection_pool_size(8).build()
        logger.info("TelegramClient: After Application.builder().build().") # DEBUG

        # Register handlers
        self._register_handlers()
        
        # Register error handler for the application
        self.application.add_error_handler(self._handle_error)

    def _register_handlers(self):
        """Registers general handlers that delegate to the WorkflowManager."""
        # Register specific command handlers
        # Handle /start, /help, /finish, and /cancel
        command_handler = CommandHandler(['start', 'help', 'finish', 'cancel'], self.dispatch_update)
        self.application.add_handler(command_handler)

        # Generic message handler (catches text)
        message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, self.dispatch_update)
        self.application.add_handler(message_handler, group=1) # Use group for order if needed

        # Callback query handler (for inline buttons)
        callback_handler = CallbackQueryHandler(self.dispatch_update)
        self.application.add_handler(callback_handler)

        # Add a handler for documents (specifically PDFs)
        document_handler = MessageHandler(filters.Document.PDF, self.dispatch_update)
        self.application.add_handler(document_handler)

        # Add handlers for other evidence types
        photo_handler = MessageHandler(filters.PHOTO, self.dispatch_update)
        self.application.add_handler(photo_handler)
        voice_handler = MessageHandler(filters.VOICE, self.dispatch_update)
        self.application.add_handler(voice_handler)
        
        # Add handler for location messages (Task 9)
        location_handler = MessageHandler(filters.LOCATION, self.dispatch_update)
        self.application.add_handler(location_handler)

        logger.info("Registered generic message, callback, document, photo, voice, and location handlers.")

    async def _handle_error(self, update: Optional[Update], context: CallbackContext):
        """Global error handler for the Telegram application.
        
        This handles exceptions that were unhandled by command handlers.
        """
        logger.info(f"TelegramClient._handle_error called with context.error: {type(context.error).__name__}") # DEBUG
        error = context.error
        
        # Format user info if available
        user_info = "unknown user"
        if update and update.effective_user:
            user_info = f"user_id: {update.effective_user.id}"
        
        # Handle different types of errors
        if isinstance(error, TelegramNetworkError):
            logger.error(f"Network error when communicating with Telegram for {user_info}: {error}")
            # Optionally notify user about connection issues
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "Sorry, I'm experiencing connection issues. Please try again in a moment."
                    )
                except Exception:
                    # If replying also fails, we can't do much
                    pass
        elif isinstance(error, TelegramTimedOut):
            logger.error(f"Timeout error when communicating with Telegram for {user_info}: {error}")
            # Optionally notify user about timeout
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "Sorry, the operation timed out. Please try again."
                    )
                except Exception:
                    pass
        elif isinstance(error, TelegramConflict):
            logger.error(f"Conflict error when communicating with Telegram for {user_info}: {error}")
            if "terminated by other getUpdates request" in str(error):
                logger.error("Multiple bot instances detected! This instance will be terminated.")
                # Stop this instance to avoid further conflicts
                if self.application:
                    try:
                        # Schedule application stop
                        asyncio.create_task(self.application.stop())
                        logger.info("Application stop scheduled due to conflict with another instance")
                        
                        # Force exit the entire process after a short delay
                        # This ensures we don't continue polling after stopping
                        logger.info("Process will exit in 1 second...")
                        
                        # Use a separate thread to exit after delay
                        # This allows current async functions to complete
                        import threading
                        import os
                        import time
                        
                        def exit_after_delay():
                            time.sleep(1)
                            logger.info("Forcefully terminating process due to Telegram conflict")
                            os._exit(1)  # Force exit without cleanup
                            
                        exit_thread = threading.Thread(target=exit_after_delay)
                        exit_thread.daemon = True  # Thread won't block process exit
                        exit_thread.start()
                        
                    except Exception as stop_error:
                        logger.error(f"Failed to stop application: {stop_error}")
                        # Force exit anyway
                        import os
                        logger.info("Force exiting process due to conflict error handling failure")
                        os._exit(1)  # Force exit without cleanup
            # Don't try to notify the user as this is not a user-facing error
        else:
            # Log all unhandled exceptions
            logger.exception(f"Unhandled exception for {user_info}: {error}")
            # Notify user of general error
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "Sorry, an error occurred while processing your request."
                    )
                except Exception:
                    pass
                    
        # Attempt to notify workflow_manager about the error if it might be in a state expecting a response
        if self.workflow_manager and update:
            try:
                await self.workflow_manager.handle_error(update, str(error))
            except Exception as workflow_error:
                logger.error(f"Failed to notify workflow_manager about error: {workflow_error}")

    @restricted # Apply restriction here to cover all dispatched updates
    async def dispatch_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generic handler to pass updates to the WorkflowManager."""
        if self.workflow_manager:
            try:
                await self.workflow_manager.handle_update(update, context)
            except Exception as e:
                logger.exception(f"Error in workflow_manager.handle_update: {e}")
                # Try to send a user-friendly error message
                if update.message:
                    await update.message.reply_text(
                        "Sorry, I encountered an error processing your message. Please try again later."
                    )
                elif update.callback_query:
                    await update.callback_query.answer(
                        "Sorry, something went wrong. Please try again.", 
                        show_alert=True
                    )
        else:
            logger.error("WorkflowManager not set in TelegramClient during dispatch.")
            # Optionally send an error message to the user
            if update.message:
                await update.message.reply_text("Bot is not properly configured. Please contact support.")
            elif update.callback_query:
                await update.callback_query.answer("Configuration error", show_alert=True)

    # --- Methods for WorkflowManager to interact with Telegram --- 

    @with_async_retry(max_retries=3, delay_seconds=2, exceptions_to_retry=(TelegramNetworkError, TelegramTimedOut, NetworkError))
    async def send_message(
        self, 
        chat_id: int, 
        text: str, 
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: Optional[str] = None # e.g., ParseMode.MARKDOWN_V2
    ):
        """Sends a message to a specific chat ID with automatic retries for network issues."""
        try:
            message = await self.application.bot.send_message(
                chat_id=chat_id, 
                text=text, 
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            logger.debug(f"Sent message to {chat_id}: {text[:50]}...")
            return message
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            # Convert telegram errors to our custom errors for retry handling
            if isinstance(e, TelegramNetworkError):
                raise NetworkError(f"Network error when sending message: {e}")
            elif isinstance(e, TelegramTimedOut):
                raise TimeoutError(f"Timeout when sending message: {e}")
            raise  # Re-raise other exceptions

    @with_async_retry(max_retries=3, delay_seconds=2, exceptions_to_retry=(TelegramNetworkError, TelegramTimedOut, NetworkError))
    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: Optional[str] = None
    ):
        """Edits an existing message with automatic retries for network issues."""
        try:
            await self.application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            logger.debug(f"Edited message {message_id} in chat {chat_id}: {text[:50]}...")
        except Exception as e:
            # Check for 'message is not modified' error BEFORE logging general error
            # Make the check case-insensitive and broader
            if "message is not modified" in str(e).lower():
                logger.debug(f"Message {message_id} not modified (error ignored): {e}")
            else:
                # Log other errors
                logger.error(f"Failed to edit message {message_id} in chat {chat_id}: {e}")
                # Convert telegram errors to our custom errors for retry handling
                if isinstance(e, TelegramNetworkError):
                    raise NetworkError(f"Network error when editing message: {e}")
                elif isinstance(e, TelegramTimedOut):
                    raise TimeoutError(f"Timeout when editing message: {e}")
                raise  # Re-raise other exceptions

    # Add other interaction methods as needed (send_photo, send_document, pin_message, etc.)

    @with_async_retry(max_retries=2, delay_seconds=1)
    async def pin_message(self, chat_id: int, message_id: int, disable_notification: bool = False):
        """Pins a message in a chat with automatic retries."""
        try:
            await self.application.bot.pin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
                disable_notification=disable_notification
            )
            logger.debug(f"Pinned message {message_id} in chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to pin message {message_id} in chat {chat_id}: {e}")
            # Convert telegram errors to our custom errors for retry handling
            if isinstance(e, TelegramNetworkError):
                raise NetworkError(f"Network error when pinning message: {e}")
            elif isinstance(e, TelegramTimedOut):
                raise TimeoutError(f"Timeout when pinning message: {e}")
            raise

    @with_async_retry(max_retries=2, delay_seconds=1)
    async def unpin_message(self, chat_id: int, message_id: int):
        """Unpins a specific message in a chat with automatic retries."""
        try:
            await self.application.bot.unpin_chat_message(
                chat_id=chat_id,
                message_id=message_id
            )
            logger.debug(f"Unpinned message {message_id} in chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to unpin message {message_id} in chat {chat_id}: {e}")
            # Convert telegram errors to our custom errors for retry handling
            if isinstance(e, TelegramNetworkError):
                raise NetworkError(f"Network error when unpinning message: {e}")
            raise

    @with_async_retry(max_retries=2, delay_seconds=1)
    async def unpin_all_messages(self, chat_id: int):
        """Unpins all messages in a chat with automatic retries."""
        try:
            await self.application.bot.unpin_all_chat_messages(chat_id=chat_id)
            logger.debug(f"Unpinned all messages in chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to unpin all messages in chat {chat_id}: {e}")
            # Convert telegram errors to our custom errors for retry handling
            if isinstance(e, TelegramNetworkError):
                raise NetworkError(f"Network error when unpinning all messages: {e}")
            raise

    @with_async_retry(max_retries=2, delay_seconds=1)
    async def send_location(
        self, 
        chat_id: int, 
        latitude: float, 
        longitude: float, 
        venue_name: Optional[str] = None, 
        address: Optional[str] = None, 
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ):
        """
        Send a location or venue message with automatic retries for network issues.
        
        Args:
            chat_id: Telegram chat ID to send to
            latitude: Location latitude
            longitude: Location longitude
            venue_name: Optional name of venue for sending as venue instead of simple location
            address: Optional address text (for venue)
            reply_markup: Optional inline keyboard markup
        """
        try:
            if venue_name and address:
                # Send as venue (with name and address)
                result = await self.application.bot.send_venue(
                    chat_id=chat_id,
                    latitude=latitude,
                    longitude=longitude,
                    title=venue_name,
                    address=address,
                    reply_markup=reply_markup
                )
                logger.debug(f"Sent venue location to {chat_id}: {venue_name}, {address}")
            else:
                # Send as regular location
                result = await self.application.bot.send_location(
                    chat_id=chat_id,
                    latitude=latitude,
                    longitude=longitude,
                    reply_markup=reply_markup
                )
                logger.debug(f"Sent location to {chat_id}: {latitude}, {longitude}")
            return result
        except Exception as e:
            logger.error(f"Failed to send location to {chat_id}: {e}")
            # Convert telegram errors to our custom errors for retry handling
            if isinstance(e, TelegramNetworkError):
                raise NetworkError(f"Network error when sending location: {e}")
            elif isinstance(e, TelegramTimedOut):
                raise TimeoutError(f"Timeout when sending location: {e}")
            raise

    @with_async_retry(max_retries=2, delay_seconds=1)
    async def send_photo(self, chat_id: int, photo, caption: Optional[str] = None, reply_markup: Optional[InlineKeyboardMarkup] = None):
        """Send a photo to a chat with automatic retries for network issues."""
        try:
            result = await self.application.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup
            )
            logger.debug(f"Sent photo to {chat_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to send photo to {chat_id}: {e}")
            # Convert telegram errors to our custom errors for retry handling
            if isinstance(e, TelegramNetworkError):
                raise NetworkError(f"Network error when sending photo: {e}")
            elif isinstance(e, TelegramTimedOut):
                raise TimeoutError(f"Timeout when sending photo: {e}")
            raise

    async def download_file(self, file_id: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Downloads a file from Telegram with timeout and error handling.
        
        Args:
            file_id: Telegram file ID to download
            
        Returns:
            Tuple of (file_content: Optional[bytes], error_message: Optional[str])
        """
        try:
            # Get file information first
            file_info = await with_async_timeout(
                self.application.bot.get_file,
                timeout_seconds=10,  # Shorter timeout for metadata
                file_id=file_id
            )
            
            logger.info(f"Downloading file {file_id}, size: {file_info.file_size} bytes")
            
            # If file is very large, notify about potentially long download
            if file_info.file_size and file_info.file_size > 10*1024*1024:  # 10MB
                logger.warning(f"Large file download initiated: {file_info.file_size/1024/1024:.1f}MB")
            
            # Custom download with progress tracking and timeout
            start_time = asyncio.get_event_loop().time()
            
            # Download the file with a timeout
            file_content = await with_async_timeout(
                file_info.download_as_bytearray,
                timeout_seconds=self.FILE_DOWNLOAD_TIMEOUT
            )
            
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"Downloaded file {file_id} ({len(file_content)/1024:.1f}KB) in {elapsed:.2f}s")
            
            return file_content, None
            
        except asyncio.TimeoutError as e:
            error_msg = f"File download timed out after {self.FILE_DOWNLOAD_TIMEOUT} seconds: {e}"
            logger.error(error_msg)
            return None, f"Download timed out. Please try again or use a smaller file."
            
        except TelegramNetworkError as e:
            error_msg = f"Network error downloading file: {e}"
            logger.error(error_msg)
            return None, "Network error during download. Please check your connection and try again."
            
        except Exception as e:
            error_msg = f"Error downloading file {file_id}: {e}"
            logger.exception(error_msg)
            return None, "Error downloading the file. Please try again later."

    @with_async_retry(max_retries=2, delay_seconds=1)
    async def send_admin_notification(self, message: str, parse_mode: Optional[str] = None) -> bool:
        """
        Send a notification message to the admin chat ID if configured.
        
        Args:
            message: The message text to send
            parse_mode: Optional parse mode ("Markdown" or "HTML")
            
        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        if not self.ADMIN_CHAT_ID:
            logger.info("Admin notification skipped: No admin chat ID configured")
            return False
            
        try:
            await self.send_message(
                chat_id=self.ADMIN_CHAT_ID,
                text=message,
                parse_mode=parse_mode
            )
            logger.debug(f"Admin notification sent successfully")
            return True
        except Exception as e:
            if "chat not found" in str(e).lower():
                logger.warning(f"Could not send admin notification: Admin (ID: {self.ADMIN_CHAT_ID}) needs to start a chat with the bot first")
                # Don't retry - this will fail until the admin messages the bot
                return False
            else:
                logger.error(f"Failed to send admin notification: {e}")
                # Let the retry decorator handle other errors
                raise

    def cleanup(self):
        """Properly cleanup resources when shutting down."""
        try:
            if self.application:
                logger.info("Cleaning up TelegramClient resources...")
                
                # Get the current event loop
                try:
                    loop = asyncio.get_event_loop()
                    
                    # Check if we're in the event loop
                    if loop.is_running():
                        # We're already in an event loop, create a task
                        logger.info("Event loop is running, scheduling stop task")
                        asyncio.create_task(self.application.stop())
                    else:
                        # We're not in an event loop, run until complete
                        logger.info("Running application.stop() in event loop")
                        loop.run_until_complete(self.application.stop())
                except RuntimeError as e:
                    if "no running event loop" in str(e):
                        # Create a new event loop if needed
                        logger.info("No running event loop, creating new one for cleanup")
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.application.stop())
                        loop.close()
                    else:
                        raise
                
                logger.info("TelegramClient cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during TelegramClient cleanup: {e}")
            
    async def _check_and_clear_webhook(self):
        """Check for and remove any existing webhooks.
        Also sends a dummy getUpdates request to clear any hanging sessions.
        """
        if not self.application or not self.application.bot:
            logger.error("Application or bot not initialized")
            return False
            
        try:
            # Check webhook status
            logger.info("Checking webhook configuration...")
            webhook_info = await self.application.bot.get_webhook_info()
            
            if webhook_info.url:
                logger.warning(f"Found existing webhook URL: {webhook_info.url}")
                logger.info("Deleting webhook...")
                
                # First delete without drop_pending_updates
                await self.application.bot.delete_webhook()
                logger.info("Webhook deleted (kept pending updates)")
                
                # Get webhook info again to verify
                webhook_info = await self.application.bot.get_webhook_info()
                if webhook_info.url:
                    logger.warning("Webhook still exists, trying again with drop_pending_updates=True")
                    await self.application.bot.delete_webhook(drop_pending_updates=True)
                
                # Final verification
                webhook_info = await self.application.bot.get_webhook_info()
                if webhook_info.url:
                    logger.error("Failed to delete webhook after multiple attempts")
                    return False
                else:
                    logger.info("Webhook deleted successfully")
            else:
                logger.info("No webhook is currently set")
                
            # Additional step: request getUpdates with timeout=0 to clear any hanging sessions
            try:
                logger.info("Sending a dummy getUpdates request to reset any hanging sessions...")
                await self.application.bot.get_updates(timeout=0, offset=-1, limit=1)
                logger.info("Dummy request completed successfully")
            except Exception as e:
                # This might fail with 409 if another instance is running, which is fine
                logger.warning(f"Dummy request failed (expected if another instance is running): {e}")
                
            return True
        except Exception as e:
            logger.error(f"Error checking/clearing webhook: {e}")
            return False

    async def _notify_admin(self):
        """Send instance information to admin for monitoring."""
        if not self.ADMIN_CHAT_ID:
            return
            
        try:
            # Gather system information
            hostname = socket.gethostname()
            try:
                # Try to get local IP address
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                local_ip = s.getsockname()[0]
                s.close()
            except:
                local_ip = "Unknown"
                
            python_version = sys.version.split()[0]
            platform_info = platform.platform()
            pid = os.getpid()
            start_time = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Format message
            message = (
                f"🔔 Patri Reports Bot Instance Started\n"
                f"Start time: {start_time}\n"
                f"PID: {pid}\n"
                f"Host: {hostname}\n"
                f"IP: {local_ip}\n"
                f"Python: {python_version}\n"
                f"Platform: {platform_info}\n"
                f"Instance Count: {self._instance_count}\n"
            )
            
            # Send to admin
            await self.application.bot.send_message(
                chat_id=self.ADMIN_CHAT_ID,
                text=message
            )
            logger.info(f"Admin notification sent to {self.ADMIN_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")

    async def async_cleanup(self):
        """Asynchronous version of cleanup for signal handlers."""
        logger.info("Performing async cleanup...")
        self.is_running = False
        self.stop_event.set()
        
        if self.application:
            try:
                await self.application.stop()
                logger.info("Application stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping application during async cleanup: {e}")
                
        logger.info("Async cleanup completed")

    def run(self):
        """Runs the Telegram bot.
        
        This method is called by main.py to start the bot.
        It creates an application instance if needed and starts polling for updates.
        """
        try:
            # Initialize application just before running
            self._initialize_application()
            
            if not self.application:
                logger.critical("Failed to initialize application")
                return
                
            # Set running state
            self.is_running = True
            self.stop_event.clear()
            
            # Admin notification status
            logger.info(f"Admin notification status: {'enabled for ID: ' + str(self.ADMIN_CHAT_ID) if self.ADMIN_CHAT_ID else 'disabled'}")
            
            # Delete any existing webhook before starting polling to avoid conflicts
            logger.info("Checking webhook configuration...")
            asyncio.get_event_loop().run_until_complete(self._check_and_clear_webhook())
            
            # Add a waiting period to ensure Telegram's server-side session has expired
            # Telegram API maintains sessions for some time, even after clients disconnect
            logger.info("Waiting 5 seconds to ensure server-side sessions are cleared...")
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(5))
            
            # Clear all pinned messages for allowed users
            if self.allowed_users:
                logger.info("Clearing pinned messages for all allowed users")
                asyncio.get_event_loop().run_until_complete(self._clear_all_pinned_messages())
            
            # Send startup notification to all allowed users
            try:
                if self.allowed_users:
                    startup_message = "🟢 *Patri Reports Assistant is now online!*\nThe system has been initialized and is ready to process reports."
                    for user_id in self.allowed_users:
                        logger.info(f"Sending startup notification to user {user_id}")
                        asyncio.get_event_loop().run_until_complete(
                            self.send_message(user_id, startup_message, parse_mode="Markdown")
                        )
                        # Show the welcome menu only if we're in IDLE state
                        if self.workflow_manager:
                            try:
                                # Check if we're in IDLE state
                                from patri_reports.state_manager import AppState
                                current_state = self.workflow_manager.state_manager.get_state()
                                
                                # Only show idle menu if we're in IDLE state
                                if current_state == AppState.IDLE:
                                    # Import the show_idle_menu function here to avoid circular imports
                                    from patri_reports.workflow.workflow_idle import show_idle_menu
                                    asyncio.get_event_loop().run_until_complete(
                                        show_idle_menu(self.workflow_manager, user_id)
                                    )
                            except ImportError as ie:
                                logger.warning(f"Could not import show_idle_menu: {ie}")
                            except Exception as e:
                                logger.warning(f"Failed to show idle menu: {e}")
            except Exception as e:
                logger.warning(f"Failed to send startup notification: {e}")
            
            # Send admin notification
            if self.ADMIN_CHAT_ID:
                asyncio.get_event_loop().run_until_complete(self._notify_admin())
            
            # Use a unique session name to avoid conflicts with previous sessions
            session_name = f"patri_reports_{uuid.uuid4().hex[:8]}"
            logger.info(f"Using unique session name: {session_name}")
            
            # Run the bot with proper error handling
            logger.info("Starting polling...")
            self.application.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "my_chat_member"],
                close_loop=False  # Don't close the event loop to allow for cleanup
            )
            
            # If we get here, polling has ended normally
            logger.info("Polling ended normally")
            self.is_running = False
            
        except TelegramConflict as e:
            if "terminated by other getUpdates request" in str(e):
                logger.error("409 Conflict: Another bot instance is already running. This instance will not start.")
                
                # Try a more aggressive approach - wait and retry once with exponential backoff
                logger.info("Attempting to retry after a longer delay...")
                
                # First clean up any existing application
                if self.application:
                    try:
                        self.cleanup()
                    except Exception as cleanup_error:
                        logger.error(f"Error during cleanup before retry: {cleanup_error}")
                
                # Reset the singleton instance to force a complete reinitialization
                TelegramClient.reset_instance()
                
                # Wait a much longer time - 60 seconds
                logger.info("Waiting 60 seconds before retry attempt...")
                time.sleep(60)
                
                # Try to start again - but only once to avoid infinite loop
                try:
                    logger.info("Reinitializing the application...")
                    # Reinitialize
                    self._instance = TelegramClient(self.workflow_manager)
                    self._initialize_application()
                    
                    # Try polling again with even more aggressive clearing
                    logger.info("Retrying polling after delay...")
                    self.application.run_polling(
                        drop_pending_updates=True,
                        allowed_updates=["message", "callback_query", "my_chat_member"]
                    )
                except Exception as retry_error:
                    logger.error(f"Retry attempt failed: {retry_error}")
                    logger.info("Exiting after retry failure")
                    os._exit(1)
            else:
                logger.exception(f"Unexpected Telegram conflict error: {e}")
                # Still exit for unexpected conflicts
                os._exit(1)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt. Shutting down...")
            # Allow for a graceful exit
            if self.application:
                try:
                    self.cleanup()
                except Exception as e:
                    logger.error(f"Error during cleanup after keyboard interrupt: {e}")
            logger.info("Shutdown complete. Exiting.")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Error running bot: {e}")
            os._exit(1)
        finally:
            # Always mark as not running, even if an exception occurred
            self.is_running = False
            self.stop_event.set()
            logger.info("Bot stopped")
            
    async def _clear_all_pinned_messages(self):
        """Clear all pinned messages for all allowed users."""
        if not self.allowed_users or not self.application or not self.application.bot:
            return
        
        for user_id in self.allowed_users:
            try:
                logger.info(f"Clearing pinned messages for user {user_id}")
                await self.unpin_all_messages(user_id)
                logger.info(f"Successfully cleared pinned messages for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to clear pinned messages for user {user_id}: {e}")
                # Continue with other users even if one fails

    # Add a method to reset the singleton for testing purposes
    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (mainly for testing)."""
        cls._instance = None
        cls._initialized = False
        cls._instance_count = 0
        logger.info("TelegramClient singleton has been reset")

# Example of how to run (should be removed or commented out)
# if __name__ == '__main__':
# ... (keep commented out or remove) 