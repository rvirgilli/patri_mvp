import os
import json
import logging
from pathlib import Path
from typing import Optional, Tuple
import time
import asyncio

from ..models.case import CaseInfo
from .error_handler import with_retry, TimeoutError, NetworkError, with_timeout

logger = logging.getLogger(__name__)


def create_case_directory_structure(base_data_dir: str, case_id: str, year: Optional[int] = None) -> Optional[Path]:
    """Creates the directory structure for a new case.

    Args:
        base_data_dir: The root directory for all case data (e.g., './data').
        case_id: The unique identifier for the case.
        year: The year for organizing cases. If None, uses the current year.

    Returns:
        The Path object for the created case directory, or None if creation failed.
    """
    # Determine the year directory
    if year is None:
        from datetime import datetime
        year = datetime.now().year
    
    year_dir = Path(base_data_dir) / str(year)
    case_path = year_dir / case_id
    photos_path = case_path / "photos"
    audio_path = case_path / "audio"

    try:
        # Create all directories
        case_path.mkdir(parents=True, exist_ok=True)
        photos_path.mkdir(exist_ok=True)
        audio_path.mkdir(exist_ok=True)
        logger.info(f"Created directory structure for case {case_id} at {case_path}")
        return case_path
    except OSError as e:
        logger.error(f"Failed to create directory structure for case {case_id}: {e}")
        return None

def get_case_info_path(case_path: Path) -> Path:
    """Returns the expected path for the case_info.json file."""
    return case_path / "case_info.json"

@with_retry(max_retries=2, delay_seconds=1)
def save_case_info(case_info: CaseInfo, case_path: Path):
    """Saves the CaseInfo object to case_info.json in the case directory.

    Uses atomic write (write to temp file, then rename).
    """
    json_path = get_case_info_path(case_path)
    temp_path = json_path.with_suffix(".json.tmp")

    try:
        # Use Pydantic's serialization method which handles datetime etc.
        json_data = case_info.model_dump_json(indent=4)
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(json_data)
        # Atomically replace the old file with the new one
        os.replace(temp_path, json_path)
        logger.debug(f"Saved case info for case {case_info.case_id} to {json_path}")
    except IOError as e:
        logger.error(f"Failed to save case info for case {case_info.case_id} to {json_path}: {e}")
        # Clean up temp file if it exists
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError as remove_e:
                logger.error(f"Failed to remove temporary file {temp_path}: {remove_e}")
        raise # Re-raise the exception so the caller knows saving failed
    except Exception as e:
        logger.exception(f"An unexpected error occurred while saving case info for {case_info.case_id}")
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError as remove_e:
                logger.error(f"Failed to remove temporary file {temp_path}: {remove_e}")
        raise

@with_retry(max_retries=2, delay_seconds=1)
def load_case_info(case_path: Path) -> Optional[CaseInfo]:
    """Loads CaseInfo from case_info.json in the case directory."""
    json_path = get_case_info_path(case_path)

    if not json_path.exists():
        logger.warning(f"Case info file not found at {json_path}")
        return None

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        case_info = CaseInfo.model_validate(data)
        logger.debug(f"Loaded case info for case {case_info.case_id} from {json_path}")
        return case_info
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load or parse case info from {json_path}: {e}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred while loading case info from {json_path}")
        return None

@with_retry(max_retries=2, delay_seconds=1)
@with_timeout(timeout_seconds=30)
def save_evidence_file(file_data: bytes, target_path: Path) -> bool:
    """Saves raw file data to the specified target path with timeout detection.
    
    Args:
        file_data: Raw bytes of the file to save
        target_path: Path where the file should be saved
        
    Returns:
        Boolean indicating success
        
    Raises:
        TimeoutError: If the operation takes longer than the timeout limit
    """
    try:
        # Ensure target directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use temp file and atomic rename for safety
        temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        
        # Track operation time for large files
        start_time = time.time()
        
        # Write to temporary file
        with open(temp_path, 'wb') as f:
            f.write(file_data)
            
        # Atomic rename
        os.replace(temp_path, target_path)
        
        elapsed = time.time() - start_time
        logger.debug(f"Saved evidence file to {target_path} ({len(file_data)/1024:.1f} KB) in {elapsed:.2f}s")
        return True
    except IOError as e:
        logger.error(f"Failed to save evidence file to {target_path}: {e}")
        # Clean up temp file if it exists
        if temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError as remove_e:
                logger.error(f"Failed to remove temporary file {temp_path}: {remove_e}")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred saving evidence file to {target_path}")
        # Clean up temp file if it exists
        if 'temp_path' in locals() and temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False

async def async_save_evidence_file(file_data: bytes, target_path: Path, chunk_size: int = 1024*1024) -> Tuple[bool, float]:
    """Saves large file data asynchronously with progress tracking.
    
    Splits large files into chunks to prevent blocking the event loop
    and allows for progress monitoring and cancellation.
    
    Args:
        file_data: Raw bytes of the file to save
        target_path: Path where the file should be saved
        chunk_size: Size of chunks to write at once
        
    Returns:
        Tuple of (success: bool, elapsed_time: float)
    """
    temp_path = None
    start_time = time.time()
    
    try:
        # Ensure target directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use temp file for atomic operation
        temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        
        # Open file for writing
        with open(temp_path, 'wb') as f:
            # Process file in chunks to avoid blocking event loop
            total_size = len(file_data)
            bytes_written = 0
            
            while bytes_written < total_size:
                end_pos = min(bytes_written + chunk_size, total_size)
                chunk = file_data[bytes_written:end_pos]
                f.write(chunk)
                bytes_written = end_pos
                
                # Yield to event loop periodically
                if bytes_written < total_size:
                    progress = bytes_written / total_size * 100
                    logger.debug(f"File write progress: {progress:.1f}% ({bytes_written}/{total_size} bytes)")
                    await asyncio.sleep(0.01)  # Brief pause to allow other tasks to run
        
        # Atomic rename
        os.replace(temp_path, target_path)
        
        elapsed = time.time() - start_time
        logger.debug(f"Async saved evidence file to {target_path} ({total_size/1024:.1f} KB) in {elapsed:.2f}s")
        return True, elapsed
    except asyncio.CancelledError:
        logger.warning(f"Async file save operation was cancelled for {target_path}")
        # Clean up temp file
        if temp_path and temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, time.time() - start_time
    except Exception as e:
        logger.exception(f"Error during async file save to {target_path}: {e}")
        # Clean up temp file
        if temp_path and temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, time.time() - start_time

def is_corrupted_pdf(file_path: Path) -> bool:
    """Checks if a PDF file is corrupted.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        True if the PDF appears to be corrupted, False otherwise
    """
    # Simple check - can be extended with more sophisticated PDF validation
    try:
        # Check file size first (very small PDFs are suspicious)
        file_size = file_path.stat().st_size
        if file_size < 100:  # Arbitrary small size
            logger.warning(f"PDF file {file_path} is suspiciously small ({file_size} bytes)")
            return True
            
        # Check for PDF header
        with open(file_path, 'rb') as f:
            header = f.read(5)
            if header != b'%PDF-':
                logger.warning(f"PDF file {file_path} does not have a valid PDF header")
                return True
                
        # Optional: More thorough check with a PDF library if needed
        # This would require adding a dependency like PyPDF2 or pikepdf
        
        return False
    except Exception as e:
        logger.error(f"Error checking if PDF is corrupted: {e}")
        return True  # Assume corrupted if we can't check 