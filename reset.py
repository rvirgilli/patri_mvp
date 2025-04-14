"""
Reset script for Patri Reports Assistant.
This script resets the application state to IDLE and removes all case data.
"""

import os
import json
import shutil
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def reset_app_state(state_file="app_state.json"):
    """Reset the application state to IDLE with no active case."""
    try:
        # Create or overwrite the state file with default IDLE state
        default_state = {
            "current_mode": "IDLE",
            "active_case_id": None
        }
        
        with open(state_file, 'w') as f:
            json.dump(default_state, f, indent=4)
            
        logger.info(f"Reset application state to IDLE in {state_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to reset application state: {e}")
        return False

def remove_case_data(data_dir="data"):
    """Remove all case data files."""
    try:
        # Check if the data directory exists
        data_path = Path(data_dir)
        if data_path.exists():
            # Remove the entire data directory
            shutil.rmtree(data_path)
            logger.info(f"Removed all case data from {data_dir}")
            
            # Recreate an empty data directory
            data_path.mkdir(exist_ok=True)
            logger.info(f"Created empty data directory: {data_dir}")
        else:
            logger.info(f"Data directory {data_dir} doesn't exist, nothing to remove")
            # Create the data directory
            data_path.mkdir(exist_ok=True)
            logger.info(f"Created data directory: {data_dir}")
            
        return True
    except Exception as e:
        logger.error(f"Failed to remove case data: {e}")
        return False

def remove_log_files(log_pattern="*.log"):
    """Remove log files."""
    try:
        count = 0
        # Find and remove all log files in the current directory
        for log_file in Path('.').glob(log_pattern):
            os.remove(log_file)
            count += 1
            logger.info(f"Removed log file: {log_file}")
            
        if count > 0:
            logger.info(f"Removed {count} log files")
        else:
            logger.info(f"No log files matching {log_pattern} found")
            
        return True
    except Exception as e:
        logger.error(f"Failed to remove log files: {e}")
        return False

def update_env_file(env_file=".env"):
    """Update the .env file to disable API calls or reset problematic settings."""
    try:
        # Check if .env file exists
        env_path = Path(env_file)
        if env_path.exists():
            # Read existing .env file
            with open(env_path, 'r') as f:
                lines = f.readlines()
            
            # Process lines, comment out OpenAI API keys to avoid quota issues
            new_lines = []
            for line in lines:
                if "OPENAI_API_KEY" in line and not line.strip().startswith('#'):
                    new_lines.append(f"# {line}")
                    logger.info("Commented out OPENAI_API_KEY to avoid quota issues")
                elif "USE_FIXED_CASE_ID" in line:
                    new_lines.append("USE_FIXED_CASE_ID=false\n")
                    logger.info("Set USE_FIXED_CASE_ID to false")
                # Removed ADMIN_CHAT_ID handling as it's now passed via command line
                else:
                    new_lines.append(line)
            
            # Write updated .env file
            with open(env_path, 'w') as f:
                f.writelines(new_lines)
            
            logger.info(f"Updated {env_file} file")
        else:
            # Create a basic .env file with no API keys
            with open(env_path, 'w') as f:
                f.write("# API keys\n")
                f.write("# OPENAI_API_KEY=\n")
                f.write("# ANTHROPIC_API_KEY=\n")
                f.write("\n")
                f.write("# Configuration\n")
                f.write("USE_FIXED_CASE_ID=false\n")
            
            logger.info(f"Created new {env_file} file")
        
        return True
    except Exception as e:
        logger.error(f"Failed to update {env_file}: {e}")
        return False

def main():
    """Run all reset functions."""
    logger.info("Starting factory reset of Patri Reports Assistant...")
    
    # Reset application state
    if reset_app_state():
        logger.info("✅ Application state reset successfully")
    else:
        logger.error("❌ Failed to reset application state")
    
    # Remove case data
    if remove_case_data():
        logger.info("✅ Case data removed successfully")
    else:
        logger.error("❌ Failed to remove case data")
    
    # Remove log files
    if remove_log_files():
        logger.info("✅ Log files removed successfully")
    else:
        logger.error("❌ Failed to remove log files")
    
    # Update environment file
    if update_env_file():
        logger.info("✅ Environment file updated successfully")
    else:
        logger.error("❌ Failed to update environment file")
    
    logger.info("Factory reset completed")

if __name__ == "__main__":
    main() 