import logging
import os
import time
import asyncio
from typing import Callable, Optional, Any, TypeVar, Coroutine, Dict, Tuple
from functools import wraps

logger = logging.getLogger(__name__)

# Type variables for generic function signatures
T = TypeVar('T')
R = TypeVar('R')

class NetworkError(Exception):
    """Exception raised for network-related errors."""
    pass

class TimeoutError(Exception):
    """Exception raised when an operation times out."""
    pass

class DataError(Exception):
    """Exception raised for data validation or processing errors."""
    pass

class StateError(Exception):
    """Exception raised for application state errors."""
    pass

def with_retry(
    max_retries: int = 3, 
    delay_seconds: int = 2,
    exponential_backoff: bool = True,
    exceptions_to_retry: tuple = (NetworkError, TimeoutError, ConnectionError)
) -> Callable:
    """
    Decorator to retry a function on specific exceptions with backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay_seconds: Initial delay between retries in seconds
        exponential_backoff: Whether to use exponential backoff for delays
        exceptions_to_retry: Tuple of exception classes that should trigger a retry
        
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        logger.info(f"Retry attempt {attempt}/{max_retries} for {func.__name__}")
                    return func(*args, **kwargs)
                except exceptions_to_retry as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Calculate delay with exponential backoff if enabled
                        wait_time = delay_seconds * (2 ** attempt if exponential_backoff else 1)
                        logger.warning(f"Operation {func.__name__} failed with {type(e).__name__}: {e}. "
                                      f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Operation {func.__name__} failed after {max_retries} retries: {e}")
            
            # Re-raise the last exception with additional context
            if last_exception:
                raise type(last_exception)(
                    f"Operation {func.__name__} failed after {max_retries} retries: {last_exception}"
                ) from last_exception
            
            # This should not happen, but as a fallback
            raise RuntimeError(f"Operation {func.__name__} failed for unknown reasons after {max_retries} retries")
            
        return wrapper
    
    return decorator

def with_async_retry(
    max_retries: int = 3, 
    delay_seconds: int = 2,
    exponential_backoff: bool = True,
    exceptions_to_retry: tuple = (NetworkError, TimeoutError, ConnectionError)
) -> Callable:
    """
    Decorator to retry an async function on specific exceptions with backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay_seconds: Initial delay between retries in seconds
        exponential_backoff: Whether to use exponential backoff for delays
        exceptions_to_retry: Tuple of exception classes that should trigger a retry
        
    Returns:
        Decorated async function with retry logic
    """
    def decorator(func: Callable[..., Coroutine]):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        logger.info(f"Async retry attempt {attempt}/{max_retries} for {func.__name__}")
                    return await func(*args, **kwargs)
                except exceptions_to_retry as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Calculate delay with exponential backoff if enabled
                        wait_time = delay_seconds * (2 ** attempt if exponential_backoff else 1)
                        logger.warning(f"Async operation {func.__name__} failed with {type(e).__name__}: {e}. "
                                      f"Retrying in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Async operation {func.__name__} failed after {max_retries} retries: {e}")
            
            # Re-raise the last exception with additional context
            if last_exception:
                raise type(last_exception)(
                    f"Async operation {func.__name__} failed after {max_retries} retries: {last_exception}"
                ) from last_exception
            
            # This should not happen, but as a fallback
            raise RuntimeError(f"Async operation {func.__name__} failed for unknown reasons after {max_retries} retries")
            
        return wrapper
    
    return decorator

def with_timeout(timeout_seconds: int) -> Callable:
    """
    Decorator to add timeout functionality to a function.
    
    Args:
        timeout_seconds: Maximum time in seconds before raising a TimeoutError
        
    Returns:
        Decorated function with timeout logic
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Operation {func.__name__} timed out after {timeout_seconds} seconds")
            
            # Set up the timeout
            original_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)
            
            try:
                return func(*args, **kwargs)
            finally:
                # Reset the alarm and restore the original handler
                signal.alarm(0)
                signal.signal(signal.SIGALRM, original_handler)
                
        return wrapper
    
    return decorator

async def with_async_timeout(func, timeout_seconds: int, *args, **kwargs):
    """
    Execute an async function with a timeout.
    
    Args:
        func: The async function to execute
        timeout_seconds: Maximum time in seconds before raising a TimeoutError
        
    Returns:
        The result of the function
    """
    try:
        return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise TimeoutError(f"Async operation {func.__name__} timed out after {timeout_seconds} seconds")

async def safe_api_call(
    func: Callable, 
    error_message: str = "API call failed", 
    default_return: Optional[Any] = None,
    raise_exception: bool = False,
    *args: Any, 
    **kwargs: Any
) -> Tuple[bool, Any, Optional[Exception]]:
    """
    Safely execute an API call and handle exceptions gracefully.
    
    Args:
        func: The function to call
        error_message: Message to log on error
        default_return: Value to return if the call fails
        raise_exception: Whether to re-raise the exception after handling
        
    Returns:
        Tuple of (success: bool, result: Any, exception: Optional[Exception])
    """
    try:
        if asyncio.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            result = func(*args, **kwargs)
        return True, result, None
    except Exception as e:
        logger.error(f"{error_message}: {str(e)}")
        if raise_exception:
            raise
        return False, default_return, e

def cleanup_old_cases(data_dir: str, max_age_days: int = 30) -> Dict[str, int]:
    """
    Clean up cases older than the specified age.
    
    Args:
        data_dir: Base directory containing case data
        max_age_days: Maximum age in days before a case is considered for cleanup
        
    Returns:
        Dictionary with counts of cases processed and removed
    """
    import shutil
    from datetime import datetime, timedelta
    from pathlib import Path
    
    path = Path(data_dir)
    if not path.exists():
        logger.warning(f"Data directory {data_dir} does not exist")
        return {"processed": 0, "removed": 0}
    
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    cases_processed = 0
    cases_removed = 0
    
    try:
        # Iterate through year directories
        for year_dir in [d for d in path.iterdir() if d.is_dir()]:
            # Iterate through case directories
            for case_dir in [d for d in year_dir.iterdir() if d.is_dir()]:
                cases_processed += 1
                case_info_path = case_dir / "case_info.json"
                
                # Check if case_info.json exists and load it
                if case_info_path.exists():
                    try:
                        with open(case_info_path, 'r') as f:
                            import json
                            case_data = json.load(f)
                        
                        # Check for completed cases
                        is_completed = case_data.get("status") == "COMPLETED"
                        
                        # Check for last modified date
                        created_date = datetime.fromisoformat(case_data.get("created_at", ""))
                        if is_completed and created_date < cutoff_date:
                            logger.info(f"Removing old completed case: {case_dir}")
                            shutil.rmtree(case_dir)
                            cases_removed += 1
                    except (json.JSONDecodeError, IOError, ValueError) as e:
                        logger.error(f"Error processing case info for {case_dir}: {e}")
                else:
                    # If no case_info.json, check directory modification time
                    try:
                        mtime = datetime.fromtimestamp(case_dir.stat().st_mtime)
                        if mtime < cutoff_date:
                            logger.info(f"Removing old case directory without info file: {case_dir}")
                            shutil.rmtree(case_dir)
                            cases_removed += 1
                    except OSError as e:
                        logger.error(f"Error checking modification time for {case_dir}: {e}")
    except Exception as e:
        logger.exception(f"Error during case cleanup: {e}")
    
    logger.info(f"Case cleanup completed: {cases_processed} processed, {cases_removed} removed")
    return {"processed": cases_processed, "removed": cases_removed} 