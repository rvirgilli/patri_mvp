import os
import time
import logging
import requests
import json
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Custom JSON encoder to handle datetime objects and other non-serializable types
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, set):
            return list(obj)
        elif hasattr(obj, "__dict__"):
            # For objects with __dict__, convert to dictionary
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        # Let the base class raise the TypeError for other types
        return super().default(obj)

class AnthropicError(Exception):
    """Base exception for Anthropic API errors."""
    pass

class TransientError(AnthropicError):
    """Temporary error that may be resolved by retrying."""
    pass

class PermanentError(AnthropicError):
    """Permanent error that will not be resolved by retrying."""
    pass

class AnthropicAPI:
    """Wrapper for Anthropic's API for LLM capabilities (summary and checklist generation)."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, use_dummy_responses: bool = False):
        """Initialize the AnthropicAPI client.
        
        Args:
            api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY from environment.
            base_url: API base URL. If None, uses the default Anthropic API URL.
            use_dummy_responses: If True, returns dummy responses instead of calling the API.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.use_dummy_responses = use_dummy_responses
        
        if use_dummy_responses:
            logger.info("AnthropicAPI initialized in dummy response mode")
        elif not self.api_key:
            logger.warning("No API key provided for AnthropicAPI. API calls will fail.")
        
        self.base_url = base_url or "https://api.anthropic.com/v1/messages"
        
        # Parse model from environment, stripping any comments
        model_env = os.environ.get("MODEL", "claude-3-haiku-20240307")
        if "#" in model_env:
            model_env = model_env.split("#")[0].strip()
        self.model = model_env
        
        # Load prompts
        self.prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
        self.portuguese_summary_prompt = self._load_prompt("case_summary_pt.txt")

    def _load_prompt(self, filename: str) -> str:
        """Load a prompt template from file.
        
        Args:
            filename: The filename of the prompt in the prompts directory.
            
        Returns:
            The content of the prompt file as a string.
        """
        try:
            with open(os.path.join(self.prompt_dir, filename), "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Prompt file {filename} not found")
            return ""
    
    def generate_summary(self, 
                        case_data: Dict[str, Any], 
                        max_retries: int = 3, 
                        initial_backoff: float = 1.0) -> Optional[str]:
        """Generate a summary of the case from the provided data.
        
        Args:
            case_data: Dictionary containing case information (history, observations, etc.).
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            
        Returns:
            Generated summary text if successful, None otherwise.
            
        Raises:
            PermanentError: When API key is missing or other permanent errors occur.
        """
        # Return dummy response if enabled
        if self.use_dummy_responses:
            logger.info("Using dummy Anthropic summary response")
            return "Dummy text for summary"
        
        # Real API call
        if not self.api_key:
            logger.error("API key not configured for Anthropic API")
            raise PermanentError("API key not configured for Anthropic API")
            
        prompt = self._create_summary_prompt(case_data)
        return self._make_anthropic_request(prompt, max_retries, initial_backoff)
    
    def generate_detailed_summary_pt(self,
                                   case_data: Dict[str, Any],
                                   max_retries: int = 3,
                                   initial_backoff: float = 1.0) -> Optional[str]:
        """Generate a detailed Portuguese summary using the Sonnet model with structured format.
        
        Args:
            case_data: Dictionary containing case information.
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            
        Returns:
            Generated Portuguese summary text if successful, None otherwise.
            
        Raises:
            PermanentError: When API key is missing or other permanent errors occur.
        """
        # Return dummy response if enabled
        if self.use_dummy_responses:
            logger.info("Using dummy Anthropic Portuguese summary response")
            return "Texto simulado para resumo em português"
        
        # Real API call
        if not self.api_key:
            logger.error("API key not configured for Anthropic API")
            raise PermanentError("API key not configured for Anthropic API")
        
        if not self.portuguese_summary_prompt:
            logger.error("Portuguese summary prompt template not found")
            raise PermanentError("Portuguese summary prompt template not found")
        
        # Convert case_data to JSON string to pass to the prompt
        # Use custom encoder to handle datetime objects
        try:
            case_json = json.dumps(case_data, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
            
            # Format the prompt with the case data JSON
            prompt = f"{self.portuguese_summary_prompt}\n\nJSON do caso:\n```json\n{case_json}\n```"
            
            # Use the model loaded from environment variables (self.model)
            return self._make_anthropic_request(prompt, max_retries, initial_backoff)
        except Exception as e:
            logger.exception(f"Error serializing case data to JSON: {e}")
            raise PermanentError(f"Error serializing case data: {e}")
    
    def generate_checklist(self, 
                          case_data: Dict[str, Any], 
                          max_retries: int = 3, 
                          initial_backoff: float = 1.0) -> Optional[str]:
        """Generate a checklist of tasks based on the case information using Anthropic's Claude.
        
        Args:
            case_data: Dictionary containing case information.
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            
        Returns:
            Generated checklist text if successful, None otherwise.
            
        Raises:
            PermanentError: When API key is missing or other permanent errors occur.
        """
        # Return dummy response if enabled
        if self.use_dummy_responses:
            logger.info("Using dummy Anthropic checklist response")
            return "Dummy text for checklist"
        
        # Real API call
        if not self.api_key:
            logger.error("API key not configured for Anthropic API")
            raise PermanentError("API key not configured for Anthropic API")
            
        prompt = self._create_checklist_prompt(case_data)
        return self._make_anthropic_request(prompt, max_retries, initial_backoff)
    
    def _create_summary_prompt(self, case_data: Dict[str, Any]) -> str:
        """Create a prompt for generating a summary.
        
        Args:
            case_data: Dictionary containing case information.
            
        Returns:
            Formatted prompt string for the LLM.
        """
        # Extract relevant information for the summary
        history_text = ""
        if "history" in case_data and case_data["history"]:
            for item in case_data["history"]:
                history_text += f"- {item['title']}: {item['content']}\n"
        
        evidence_text = ""
        if "evidence" in case_data and case_data["evidence"]:
            for item in case_data["evidence"]:
                if item.get("type") == "note":
                    evidence_text += f"- Note: {item.get('content', '')}\n"
                elif item.get("type") == "photo":
                    evidence_text += f"- Photo evidence recorded\n"
        
        address = case_data.get("address", "")
        complement = case_data.get("address_complement", "")
        full_address = f"{address} {complement}".strip()
        
        prompt = f"""You are a police report assistant. Create a concise summary (maximum 300 words) of this forensic case based on the information provided.
        
Case Information:
- Case ID: {case_data.get('case_number', '')}/{case_data.get('case_year', '')}
- Location: {full_address}
- Requesting Unit: {case_data.get('requesting_unit', '')}

Case History:
{history_text}

Field Notes and Evidence:
{evidence_text}

Format your response as a professional, factual summary that could be included in an official report. Focus on the key facts, observations, and findings. Do not include any speculative information or personal opinions. The summary should be written in third person and in past tense.
"""
        return prompt
    
    def _create_checklist_prompt(self, case_data: Dict[str, Any]) -> str:
        """Create a prompt for generating a checklist.
        
        Args:
            case_data: Dictionary containing case information.
            
        Returns:
            Formatted prompt string for the LLM.
        """
        # Extract data about traces for the checklist
        traces_text = ""
        if "traces" in case_data and case_data["traces"]:
            for trace in case_data["traces"]:
                traces_text += f"- {trace.get('type', '')} (ID: {trace.get('id', '')}): {trace.get('examinations', '')}\n"
        
        history_text = ""
        if "history" in case_data and case_data["history"]:
            for item in case_data["history"]:
                history_text += f"- {item['title']}: {item['content']}\n"
        
        prompt = f"""You are a forensic expert. Create a detailed checklist of recommended follow-up tasks for this forensic case based on the information provided.
        
Case Information:
- Case ID: {case_data.get('case_number', '')}/{case_data.get('case_year', '')}
- Requesting Unit: {case_data.get('requesting_unit', '')}

Case History:
{history_text}

Identified Traces:
{traces_text}

Generate a checklist with 5-10 specific, actionable items that should be followed up on for this case. Each item should be clear and specific. Format the response as a numbered list with brief explanations for each item.
"""
        return prompt
    
    def _make_anthropic_request(self, 
                         prompt: str, 
                         max_retries: int = 3, 
                         initial_backoff: float = 1.0,
                         model_override: Optional[str] = None) -> Optional[str]:
        """Make the API request to the Anthropic Claude service.
        
        Args:
            prompt: The prompt text to send to Claude.
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            model_override: Override the default model if specified.
            
        Returns:
            Generated text if successful, None otherwise.
            
        Raises:
            TransientError: For temporary errors that may be resolved by retrying.
            PermanentError: For permanent errors that will not be resolved by retrying.
        """
        if not self.api_key:
            logger.error("API key not configured for Anthropic API")
            raise PermanentError("API key not configured for Anthropic API")
        
        # Use the specified model or fall back to the default
        model = model_override or self.model
        
        retries = 0
        while retries <= max_retries:
            try:
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01"
                }
                
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 2000,  # Increase max tokens for the detailed summary
                    "temperature": 0.7
                }
                
                logger.debug(f"Sending Anthropic API request using model: {model}")
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=60  # Increase timeout for longer responses
                )
                
                # Handle response
                if response.status_code == 200:
                    result = response.json()
                    if "content" in result and result["content"]:
                        for content_block in result["content"]:
                            if content_block.get("type") == "text":
                                message_content = content_block.get("text", "")
                                logger.info("Successfully generated Anthropic response")
                                return message_content
                        error_msg = "Response did not contain expected text content"
                        logger.error(error_msg)
                        raise PermanentError(error_msg)
                    else:
                        error_msg = f"Missing expected data in API response: {result}"
                        logger.error(error_msg)
                        raise PermanentError(error_msg)
                elif response.status_code in (429, 500, 502, 503, 504):
                    # Rate limiting or server errors - these are transient
                    error_msg = f"API returned status {response.status_code}: {response.text}"
                    logger.warning(error_msg)
                    raise TransientError(error_msg)
                else:
                    # Client errors and other issues - these are permanent
                    error_msg = f"API returned status {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    raise PermanentError(error_msg)
                
            except TransientError as e:
                retries += 1
                wait_time = initial_backoff * (2 ** (retries - 1))  # Exponential backoff
                logger.warning(f"Transient error on Anthropic request attempt {retries}/{max_retries}: {e}. Retrying in {wait_time}s")
                time.sleep(wait_time)
            except requests.exceptions.RequestException as e:
                # Network errors
                retries += 1
                wait_time = initial_backoff * (2 ** (retries - 1))
                logger.warning(f"Network error on Anthropic request attempt {retries}/{max_retries}: {e}. Retrying in {wait_time}s")
                time.sleep(wait_time)
            except Exception as e:
                # Other unexpected errors
                logger.exception(f"Unexpected error on Anthropic request: {e}")
                raise PermanentError(f"Unexpected error: {e}")
        
        # If we've exhausted retries
        logger.error(f"Failed to get Anthropic response after {max_retries} retries")
        return None 