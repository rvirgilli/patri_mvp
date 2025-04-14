#!/usr/bin/env python3
"""
Minimal Telegram bot implementation focused on solving the 409 Conflict error.
This implementation uses a careful initialization and session management approach
to prevent conflicts when starting multiple instances.
"""

import os
import sys
import time
import logging
import asyncio
import signal
import threading
import httpx
import socket
import platform
from logging.handlers import RotatingFileHandler
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.error import RetryAfter, TimedOut, NetworkError, Conflict
from typing import Optional, Callable, Dict, Any, List
from functools import wraps
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [PID:%(process)d] - %(message)s',
    handlers=[
        logging.FileHandler("minimal_bot.log"),
        logging.StreamHandler()
    ]
)

# Create a module-level logger
logger = logging.getLogger("minimal_bot")
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv()

# Define a signal handler for graceful shutdown
def signal_handler(sig, frame):
    """Handle termination signals."""
    signal_name = "SIGINT" if sig == signal.SIGINT else "SIGTERM"
    logger.info(f"Received {signal_name} signal, initiating clean shutdown...")
    
    # Get the bot instance if it exists
    bot = MinimalBot._instance
    if bot and bot.running:
        logger.info("Stopping running bot instance...")
        # Set the stop event to trigger clean shutdown in polling loop
        bot.stop_event.set()
        # We can't await an async method in signal handler, so just set the flag
        bot.running = False
    else:
        logger.info("No running bot to stop")

class MinimalBot:
    """
    Minimal Telegram bot implementation with proper session management
    to avoid 409 Conflict errors.
    """
    
    # Class variable to ensure singleton pattern
    _instance = None
    _initialized = False
    
    # Admin notification settings
    # Change this to your personal Telegram ID
    ADMIN_CHAT_ID = None  # You'll need to add your Telegram ID here
    
    @classmethod
    def get_instance(cls, token=None):
        if cls._instance is None:
            if token is None:
                # Use the new bot token (confirmed working)
                token = "7926182470:AAGWsfaO1wzNmz6AV7loN3B3VKG22UVNtAs"
            cls._instance = cls(token)
        return cls._instance
    
    def __new__(cls, *args, **kwargs):
        """Implement singleton pattern to prevent multiple instances."""
        if cls._instance is None:
            logger.info("Creating new MinimalBot singleton instance")
            cls._instance = super(MinimalBot, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, token: Optional[str] = None):
        """Initialize the bot with careful session management."""
        # Skip initialization if already initialized
        if MinimalBot._initialized:
            logger.info("MinimalBot already initialized, skipping __init__")
            return
            
        # Store but don't use token until needed (lazy initialization)
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            logger.critical("Bot token not provided and TELEGRAM_BOT_TOKEN not set in environment")
            raise ValueError("Bot token is required")
            
        # Initialize variables but don't create connections yet
        self.bot = None
        self.application = None
        self.running = False
        self.stop_event = asyncio.Event()
        self.message_handlers = []
        
        logger.info("MinimalBot instance created (not yet connected)")
        MinimalBot._initialized = True
    
    async def _create_bot(self):
        """Create the bot instance with careful initialization."""
        try:
            # Import here to avoid early initialization
            from telegram import Bot
            
            logger.info("Creating Bot instance...")
            self.bot = Bot(self.token)
            
            # Test the connection
            me = await self.bot.get_me()
            logger.info(f"Successfully connected as @{me.username} (ID: {me.id})")
            
            return True
        except Exception as e:
            logger.error(f"Error creating bot: {e}")
            return False
    
    async def _check_and_clear_webhook(self):
        """Check for and remove any existing webhooks."""
        if not self.bot:
            return False
            
        try:
            # Check webhook status
            logger.info("Checking webhook configuration...")
            webhook_info = await self.bot.get_webhook_info()
            
            if webhook_info.url:
                logger.warning(f"Found existing webhook URL: {webhook_info.url}")
                logger.info("Deleting webhook...")
                
                # First delete without drop_pending_updates
                await self.bot.delete_webhook()
                logger.info("Webhook deleted (kept pending updates)")
                
                # Get webhook info again to verify
                webhook_info = await self.bot.get_webhook_info()
                if webhook_info.url:
                    logger.warning("Webhook still exists, trying again with drop_pending_updates=True")
                    await self.bot.delete_webhook(drop_pending_updates=True)
                
                # Final verification
                webhook_info = await self.bot.get_webhook_info()
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
                await self.bot.get_updates(timeout=0, offset=-1, limit=1)
                logger.info("Dummy request completed successfully")
            except Exception as e:
                # This might fail with 409 if another instance is running, which is fine
                logger.warning(f"Dummy request failed (expected if another instance is running): {e}")
                
            return True
        except Exception as e:
            logger.error(f"Error checking/clearing webhook: {e}")
            return False
    
    def add_message_handler(self, handler_func: Callable):
        """Add a function to handle incoming messages."""
        self.message_handlers.append(handler_func)
        logger.info(f"Added message handler: {handler_func.__name__}")
        
    async def _process_updates(self, updates):
        """Process incoming updates and dispatch to handlers."""
        for update in updates:
            if update.message:
                logger.info(f"Received message from {update.message.from_user.id}: {update.message.text}")
                
                # Pass to all registered handlers
                for handler in self.message_handlers:
                    try:
                        await handler(update.message)
                    except Exception as e:
                        logger.error(f"Error in message handler {handler.__name__}: {e}")
    
    async def _polling_loop(self):
        """Main polling loop with proper error handling."""
        from telegram.error import TimedOut, NetworkError, Conflict

        # Track the last update ID to avoid processing duplicates
        offset = 0
        error_count = 0  # Initialize error counter
        consecutive_conflicts = 0
        logger.info("Starting polling loop...")
        
        # Add longer artificial delay to ensure any prior sessions are cleared
        logger.info("Waiting 10 seconds before starting polling...")
        await asyncio.sleep(10)
        
        logger.info(f"Process {os.getpid()} starting getUpdates polling")
        
        while not self.stop_event.is_set():
            try:
                logger.debug("Polling for updates...")
                updates = await self.bot.get_updates(
                    offset=offset,
                    timeout=30,  # Long polling timeout
                    allowed_updates=["message", "callback_query", "my_chat_member"]
                )
                
                # Reset error counters after successful request
                error_count = 0
                consecutive_conflicts = 0
                
                if updates:
                    # Process updates
                    await self._process_updates(updates)
                    
                    # Update offset to avoid getting the same updates again
                    offset = updates[-1].update_id + 1
                    
                # Small sleep to avoid hammering the API if something goes wrong
                await asyncio.sleep(0.1)
                
            except Conflict as e:
                consecutive_conflicts += 1
                logger.error(f"409 Conflict error ({consecutive_conflicts}/3): {e}")
                
                if consecutive_conflicts >= 3:
                    logger.error("Multiple consecutive conflicts, another bot instance is definitely running. Stopping polling.")
                    self.stop_event.set()
                    break
                else:
                    # Try waiting longer before retrying
                    logger.info(f"Waiting 60 seconds before retry attempt {consecutive_conflicts}...")
                    await asyncio.sleep(60)
                
            except (TimedOut, NetworkError) as e:
                # These are normal for long polling, just log and continue
                logger.warning(f"Network issue during polling: {e}")
                await asyncio.sleep(1)  # Brief backoff
                
            except Exception as e:
                error_count += 1
                logger.error(f"Unexpected error during polling ({error_count}/5): {e}")
                await asyncio.sleep(2)  # Longer backoff for unexpected errors
                
                # Consider stopping if we get persistent errors
                if error_count > 5:
                    logger.error("Too many errors, stopping polling")
                    self.stop_event.set()
                    break
        
        logger.info("Polling loop stopped")
    
    async def _notify_admin(self):
        """Send instance information to admin for monitoring."""
        if not self.ADMIN_CHAT_ID:
            logger.warning("Admin chat ID not set, skipping admin notification")
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
                f"🔔 Bot Instance Started\n"
                f"Bot username: @{self.bot.username}\n"
                f"Start time: {start_time}\n"
                f"PID: {pid}\n"
                f"Host: {hostname}\n"
                f"IP: {local_ip}\n"
                f"Python: {python_version}\n"
                f"Platform: {platform_info}\n"
            )
            
            # Send to admin
            await self.bot.send_message(
                chat_id=self.ADMIN_CHAT_ID,
                text=message
            )
            logger.info(f"Admin notification sent to {self.ADMIN_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")

    async def start(self):
        """Initialize and start the bot, setting up webhooks/polling correctly."""
        # Set status flag
        self.running = True
        self.stop_event = asyncio.Event()

        try:
            # Initialize the bot
            logger.info("Creating Bot instance...")
            self.bot = Bot(token=self.token)
            
            # Verify bot can connect to Telegram
            me = await self.bot.get_me()
            logger.info(f"Successfully connected as @{me.username} (ID: {me.id})")
            
            # Check and clear webhook
            success = await self._check_and_clear_webhook()
            if not success:
                logger.error("Failed to configure webhook")
                self.running = False
                return False
                
            # Notify admin about this instance (if configured)
            await self._notify_admin()
                
            # Start polling in the background
            logger.info("Starting polling...")
            self.polling_task = asyncio.create_task(self._polling_loop())
            
            # Setup is complete
            logger.info("Bot is running. Press Ctrl+C to stop.")
            return True
            
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            self.running = False
            return False
    
    async def stop(self):
        """Stop the bot gracefully."""
        if not self.running:
            logger.warning("Bot is not running")
            return
            
        logger.info("Stopping bot...")
        self.stop_event.set()
        self.running = False
        
        # Wait for polling to stop
        await asyncio.sleep(1)
        
        logger.info("Bot stopped")
        
    @classmethod
    def reset(cls):
        """Reset the singleton instance (for testing purposes)."""
        cls._instance = None
        cls._initialized = False
        logger.info("MinimalBot singleton has been reset")

async def demo_handler(message):
    """Demo message handler that echoes messages."""
    from telegram import Message
    
    if not isinstance(message, Message):
        return
        
    text = message.text.strip()
    if text:
        try:
            await message.reply_text(f"You said: {text}")
        except Exception as e:
            logger.error(f"Error sending reply: {e}")

async def main():
    """Run a simple demo of the minimal bot."""
    logger.info(f"Bot process started with PID: {os.getpid()}")
    
    try:
        # Create and start the bot
        bot = MinimalBot.get_instance()
        
        # Ask for admin Telegram ID if not set
        if not bot.ADMIN_CHAT_ID:
            print("\n===== Admin Notification Setup =====")
            print("To receive notifications about bot instances, please enter your Telegram ID.")
            print("You can get your ID by sending a message to @userinfobot on Telegram.")
            admin_id = input("Enter your Telegram ID (or press Enter to skip): ").strip()
            if admin_id:
                try:
                    bot.ADMIN_CHAT_ID = int(admin_id)
                    print(f"Admin notifications will be sent to ID: {bot.ADMIN_CHAT_ID}")
                except ValueError:
                    print("Invalid ID format. Notifications will be disabled.")
            else:
                print("Admin notifications disabled.")
            print("=====================================\n")
        
        success = await bot.start()
        
        if success:
            logger.info("Bot started successfully, running for 2 minutes...")
            # Wait for a while
            for _ in range(120):  # 2 minutes
                if bot.stop_event.is_set():
                    break
                await asyncio.sleep(1)
            
            # Stop the bot
            await bot.stop()
        else:
            logger.error("Failed to start bot")
        
        logger.info("Bot demo completed")
    except Exception as e:
        logger.exception(f"Unhandled error: {e}")
        return 1
    return 0

if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, signal_handler)
    
    try:
        # Run the async main function
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by keyboard")
        sys.exit(130)  # Standard code for SIGINT
    except Exception as e:
        logger.exception(f"Unhandled error: {e}")
        sys.exit(1) 