#!/usr/bin/env python3
"""
Debug script for Telegram client to investigate 409 Conflict errors.
This script creates a minimal implementation to check webhook status,
singleton behavior, and proper cleanup.
"""

import os
import sys
import logging
import asyncio
import time
import signal
import subprocess
from dotenv import load_dotenv

# Adjust path to import from patri_reports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from patri_reports.utils.log_setup import setup_logging
from telegram import Bot
from telegram.error import TelegramError, NetworkError, TimedOut, Conflict

# Load environment variables from .env file
load_dotenv()

# Setup logging
setup_logging()
logger = logging.getLogger("debug_telegram")

async def check_webhook_status(token):
    """Check the current webhook status for the bot."""
    try:
        bot = Bot(token)
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Current webhook configuration: {webhook_info.to_dict()}")
        
        if webhook_info.url:
            logger.warning(f"Webhook is currently set to URL: {webhook_info.url}")
            
            # Delete the webhook
            logger.info("Deleting webhook...")
            await bot.delete_webhook()
            
            # Check again to confirm
            webhook_info = await bot.get_webhook_info()
            logger.info(f"Webhook after deletion: {webhook_info.to_dict()}")
        else:
            logger.info("No webhook is currently set")
            
        return webhook_info
    except Exception as e:
        logger.error(f"Error checking webhook status: {e}")
        return None

def test_bot_process():
    """Test bot in a separate subprocess."""
    try:
        logger.info("Starting bot process for 5 seconds to test for conflicts...")
        
        # Start the process and capture output
        process = subprocess.Popen(
            ["python", "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Let it run for 5 seconds
        logger.info(f"Bot process started with PID {process.pid}")
        time.sleep(5)
        
        # Check if it's still running
        if process.poll() is None:
            logger.info("Bot is running successfully without conflicts")
            # Terminate it
            process.terminate()
            try:
                process.wait(timeout=5)
                logger.info(f"Bot process terminated with exit code: {process.returncode}")
            except subprocess.TimeoutExpired:
                logger.warning("Bot didn't terminate gracefully, killing...")
                process.kill()
                process.wait()
                logger.info(f"Bot process killed with exit code: {process.returncode}")
        else:
            # Process already exited
            stdout, stderr = process.communicate()
            logger.error(f"Bot exited prematurely with code {process.returncode}")
            logger.error(f"STDOUT: {stdout}")
            logger.error(f"STDERR: {stderr}")
            
        return process.returncode
    except Exception as e:
        logger.error(f"Error testing bot process: {e}")
        return -1

async def test_singleton():
    """Test if our singleton implementation works correctly."""
    try:
        # This import is inside the function to prevent immediate initialization
        from patri_reports.telegram_client import TelegramClient
        from patri_reports.workflow_manager import WorkflowManager
        from patri_reports.state_manager import StateManager
        from patri_reports.case_manager import CaseManager
        
        logger.info("Testing singleton pattern...")
        
        # Create minimal dependencies
        state_manager = StateManager(state_file="debug_state.json")
        case_manager = CaseManager(data_dir="debug_data")
        
        # First instance
        logger.info("Creating first TelegramClient instance...")
        workflow_manager1 = WorkflowManager(state_manager=state_manager, case_manager=case_manager)
        client1 = TelegramClient(workflow_manager=workflow_manager1)
        
        # Second instance
        logger.info("Creating second TelegramClient instance...")
        workflow_manager2 = WorkflowManager(state_manager=state_manager, case_manager=case_manager)
        client2 = TelegramClient(workflow_manager=workflow_manager2)
        
        # Check if they're the same object
        logger.info(f"Client1 id: {id(client1)}")
        logger.info(f"Client2 id: {id(client2)}")
        logger.info(f"Are they the same object? {client1 is client2}")
        
        # No need to check the initialization - it's now delayed until _initialize_application is called
        logger.info(f"Instance count: {TelegramClient._instance_count}")
        
        # Reset singleton for future tests
        logger.info("Resetting singleton...")
        TelegramClient.reset_instance()
        
        return client1 is client2
    except Exception as e:
        logger.error(f"Error testing singleton: {e}")
        return False

def check_running_processes():
    """Check for any running Python processes that might conflict."""
    try:
        logger.info("Checking for running Python processes...")
        result = subprocess.run(
            ["ps", "-ef", "|", "grep", "python"], 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        # Filter lines containing 'main.py'
        main_processes = [line for line in result.stdout.splitlines() if 'main.py' in line and 'grep' not in line]
        
        if main_processes:
            logger.warning(f"Found {len(main_processes)} potentially conflicting processes:")
            for process in main_processes:
                logger.warning(f"  {process}")
        else:
            logger.info("No conflicting main.py processes found")
            
        return main_processes
    except Exception as e:
        logger.error(f"Error checking processes: {e}")
        return []

async def main():
    """Main debug function."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("TELEGRAM_BOT_TOKEN environment variable not set!")
        return
    
    try:
        # 0. Check for conflicting processes
        logger.info("=== CHECKING FOR CONFLICTING PROCESSES ===")
        conflicting_processes = check_running_processes()
        if conflicting_processes:
            logger.warning("You may want to kill these processes before testing")
            
        # 1. Check webhook status
        logger.info("\n=== CHECKING WEBHOOK STATUS ===")
        await check_webhook_status(token)
        
        # 2. Test singleton implementation
        logger.info("\n=== TESTING SINGLETON PATTERN ===")
        singleton_works = await test_singleton()
        
        if singleton_works:
            logger.info("Singleton pattern is working correctly ✓")
        else:
            logger.error("Singleton pattern test failed ✗")
        
        # 3. Test bot process
        logger.info("\n=== TESTING BOT PROCESS ===")
        exit_code = test_bot_process()
        
        if exit_code == 0:
            logger.info("Bot process test completed successfully ✓")
        else:
            logger.error(f"Bot process test failed with exit code {exit_code} ✗")
        
        # Summary
        logger.info("\n=== TEST SUMMARY ===")
        logger.info(f"Singleton Pattern: {'✓ WORKING' if singleton_works else '✗ FAILED'}")
        logger.info(f"Bot Process: {'✓ WORKING' if exit_code == 0 else '✗ FAILED'}")
        logger.info(f"Webhook Status: {'✓ CLEAR' if not (await check_webhook_status(token)).url else '✗ SET'}")
        logger.info(f"Conflicting Processes: {'✗ FOUND' if conflicting_processes else '✓ NONE'}")
        
    except Exception as e:
        logger.error(f"Error in main debug function: {e}")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main()) 