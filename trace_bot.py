#!/usr/bin/env python3
"""
Tracing script to debug Telegram bot issues, specifically 409 Conflict errors.
This script monitors running processes, logs detailed information about bot operations,
and detects potential conflicts.
"""

import os
import sys
import time
import logging
import subprocess
import threading
import psutil
import asyncio
import signal
from datetime import datetime
from dotenv import load_dotenv

# Adjust path to import from patri_reports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Configure logging for trace script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [PID:%(process)d] - %(message)s',
    handlers=[
        logging.FileHandler("bot_trace.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("bot_tracer")

# Load environment variables
load_dotenv()

class BotTracer:
    """Traces Telegram bot processes and monitors for conflicts"""
    
    def __init__(self):
        self.trace_id = f"{int(time.time())}"
        self.running = False
        self.monitor_thread = None
        self.bot_process = None
        self.start_time = None
        
    def trace_running_python_processes(self):
        """Find all running Python processes"""
        python_processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                if 'python' in proc.info['name'].lower():
                    cmd = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                    
                    # Calculate process uptime
                    create_time = datetime.fromtimestamp(proc.info['create_time'])
                    uptime = datetime.now() - create_time
                    
                    python_processes.append({
                        'pid': proc.info['pid'],
                        'cmdline': cmd,
                        'create_time': create_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'uptime': str(uptime),
                        'connections': len(proc.connections()) if hasattr(proc, 'connections') else 'N/A'
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        return python_processes
        
    def check_telegram_connections(self):
        """Check for active connections to api.telegram.org"""
        telegram_connections = []
        
        for conn in psutil.net_connections():
            try:
                if conn.status == 'ESTABLISHED':
                    if conn.raddr and conn.laddr:
                        process = psutil.Process(conn.pid) if conn.pid else None
                        
                        # Process cmdline may be None or empty for some processes
                        cmdline = ' '.join(process.cmdline()) if process and process.cmdline() else 'Unknown'
                        
                        conn_info = {
                            'pid': conn.pid,
                            'local': f"{conn.laddr.ip}:{conn.laddr.port}",
                            'remote': f"{conn.raddr.ip}:{conn.raddr.port}",
                            'status': conn.status,
                            'process': cmdline
                        }
                        
                        # Check if connecting to Telegram servers
                        if 'telegram' in conn_info['remote'].lower():
                            telegram_connections.append(conn_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        return telegram_connections
    
    def check_for_conflict_indicators(self):
        """Check for indicators that might suggest 409 Conflict causes"""
        indicators = {
            'multiple_bot_processes': False,
            'multiple_telegram_connections': False,
            'suspected_cause': 'Unknown'
        }
        
        # Check for multiple Python processes running main.py or similar bot scripts
        python_processes = self.trace_running_python_processes()
        bot_processes = [p for p in python_processes if 'main.py' in p['cmdline']]
        
        if len(bot_processes) > 1:
            indicators['multiple_bot_processes'] = True
            indicators['bot_processes'] = bot_processes
            indicators['suspected_cause'] = 'Multiple bot instances detected'
        
        # Check for multiple connections to Telegram API
        telegram_connections = self.check_telegram_connections()
        if len(telegram_connections) > 1:
            indicators['multiple_telegram_connections'] = True
            indicators['telegram_connections'] = telegram_connections
            indicators['suspected_cause'] = 'Multiple Telegram API connections detected'
        
        return indicators
    
    def monitor_process(self, process):
        """Monitor a specific process for issues"""
        try:
            proc = psutil.Process(process.pid)
            
            while self.running and proc.is_running():
                try:
                    # Log process stats
                    mem_info = proc.memory_info()
                    cpu_percent = proc.cpu_percent(interval=1)
                    
                    logger.info(f"Bot process stats: CPU={cpu_percent}%, Memory={mem_info.rss / (1024 * 1024):.2f}MB")
                    
                    # Check for conflict indicators
                    indicators = self.check_for_conflict_indicators()
                    if indicators['multiple_bot_processes'] or indicators['multiple_telegram_connections']:
                        logger.warning(f"Potential conflict detected: {indicators['suspected_cause']}")
                        logger.warning(f"Conflict indicators: {indicators}")
                    
                    time.sleep(2)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    logger.error("Lost access to process")
                    break
                    
            # Process ended
            if not proc.is_running():
                logger.info(f"Process {proc.pid} has terminated")
                exitcode = proc.wait() if hasattr(proc, 'wait') else 'Unknown'
                logger.info(f"Exit code: {exitcode}")
                self.running = False
        except psutil.NoSuchProcess:
            logger.error(f"Process {process.pid} no longer exists")
            self.running = False
    
    def start_monitoring(self):
        """Start the monitoring thread"""
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def _monitoring_loop(self):
        """Main monitoring loop that runs in background thread"""
        while self.running:
            # Periodically log system state
            logger.info("--- System State Check ---")
            
            # Log all Python processes
            python_processes = self.trace_running_python_processes()
            logger.info(f"Found {len(python_processes)} Python processes:")
            for proc in python_processes:
                logger.info(f"PID: {proc['pid']}, Cmd: {proc['cmdline']}, Uptime: {proc['uptime']}")
            
            # Log Telegram connections
            telegram_connections = self.check_telegram_connections()
            logger.info(f"Found {len(telegram_connections)} Telegram connections:")
            for conn in telegram_connections:
                logger.info(f"PID: {conn['pid']}, {conn['local']} -> {conn['remote']}, Process: {conn['process']}")
            
            # Check for conflict indicators
            indicators = self.check_for_conflict_indicators()
            if indicators['multiple_bot_processes'] or indicators['multiple_telegram_connections']:
                logger.warning(f"Potential conflict detected: {indicators['suspected_cause']}")
            
            time.sleep(5)
    
    def start_bot(self):
        """Start the bot process and monitor it"""
        logger.info(f"Starting bot with trace ID: {self.trace_id}")
        
        # Kill any existing bot processes first
        self._kill_existing_bots()
        
        # Start monitoring
        self.start_monitoring()
        
        # Start the bot process
        self.start_time = datetime.now()
        logger.info(f"Starting bot process at {self.start_time}")
        
        try:
            self.bot_process = subprocess.Popen(
                ["python", "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                env=dict(os.environ, BOT_TRACE_ID=self.trace_id)  # Pass trace ID to bot
            )
            
            logger.info(f"Bot process started with PID: {self.bot_process.pid}")
            
            # Start separate thread to monitor this process
            threading.Thread(target=self.monitor_process, args=(self.bot_process,)).start()
            
            # Handle output in real-time
            threading.Thread(target=self._handle_output, args=(self.bot_process.stdout, "STDOUT")).start()
            threading.Thread(target=self._handle_output, args=(self.bot_process.stderr, "STDERR")).start()
            
            # Wait for the process to complete
            self.bot_process.wait()
            
            # Calculate runtime
            end_time = datetime.now()
            runtime = end_time - self.start_time
            logger.info(f"Bot process exited with code: {self.bot_process.returncode}")
            logger.info(f"Total runtime: {runtime}")
            
            # Stop monitoring
            self.running = False
            
        except Exception as e:
            logger.error(f"Error starting or monitoring bot: {e}")
            self.running = False
    
    def _handle_output(self, pipe, name):
        """Handle process output streams"""
        for line in pipe:
            logger.info(f"{name}: {line.strip()}")
    
    def _kill_existing_bots(self):
        """Kill any existing bot processes"""
        python_processes = self.trace_running_python_processes()
        bot_processes = [p for p in python_processes if 'main.py' in p['cmdline']]
        
        if bot_processes:
            logger.warning(f"Found {len(bot_processes)} existing bot processes. Killing them...")
            
            for proc in bot_processes:
                try:
                    logger.info(f"Killing process PID: {proc['pid']}")
                    os.kill(proc['pid'], signal.SIGTERM)
                    
                    # Give it a chance to terminate gracefully
                    time.sleep(2)
                    
                    # Check if still running
                    try:
                        process = psutil.Process(proc['pid'])
                        if process.is_running():
                            logger.warning(f"Process {proc['pid']} didn't terminate gracefully. Force killing...")
                            os.kill(proc['pid'], signal.SIGKILL)
                    except psutil.NoSuchProcess:
                        logger.info(f"Process {proc['pid']} terminated successfully")
                        
                except (ProcessLookupError, PermissionError) as e:
                    logger.error(f"Error killing process {proc['pid']}: {e}")
        else:
            logger.info("No existing bot processes found to kill")

async def check_telegram_api():
    """
    Check if the Telegram API is accessible and if the bot token is valid
    """
    from telegram import Bot
    
    logger.info("Checking Telegram API and bot token...")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error("No TELEGRAM_BOT_TOKEN found in environment variables")
        return False
    
    try:
        bot = Bot(bot_token)
        me = await bot.get_me()
        logger.info(f"Successfully connected to Telegram API. Bot username: @{me.username}")
        
        # Check webhook status
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Current webhook settings: {webhook_info.to_dict()}")
        
        # Delete any webhook
        if webhook_info.url:
            logger.warning(f"Found existing webhook URL: {webhook_info.url}. Removing...")
            await bot.delete_webhook()
            logger.info("Webhook deleted")
        
        return True
    except Exception as e:
        logger.error(f"Error checking Telegram API: {e}")
        return False

def main():
    """Main entry point"""
    logger.info("===== Bot Tracer Started =====")
    
    # Check Telegram API first
    asyncio.run(check_telegram_api())
    
    tracer = BotTracer()
    
    # Log system state before starting
    logger.info("Initial system state:")
    python_processes = tracer.trace_running_python_processes()
    logger.info(f"Found {len(python_processes)} Python processes")
    
    # Start tracing and run the bot
    tracer.start_bot()
    
    logger.info("===== Bot Tracer Completed =====")

if __name__ == "__main__":
    main() 