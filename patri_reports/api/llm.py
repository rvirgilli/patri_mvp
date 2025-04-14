import os
import time
import logging
import requests
from typing import Optional, Dict, Any, List, Union

# Configure logging
logger = logging.getLogger(__name__)

class LLMError(Exception):
    """Base exception for LLM API errors."""
    pass

class TransientError(LLMError):
    """Temporary error that may be resolved by retrying."""
    pass

class PermanentError(LLMError):
    """Permanent error that will not be resolved by retrying."""
    pass

class LLMAPI:
    """Wrapper for OpenAI's API for LLM capabilities (summary and checklist generation)."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, use_dummy_responses: bool = False):
        """Initialize the LLMAPI client.
        
        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY from environment.
            base_url: API base URL. If None, uses the default OpenAI API URL.
            use_dummy_responses: If True, returns dummy responses instead of calling the API.
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.use_dummy_responses = use_dummy_responses
        
        if use_dummy_responses:
            logger.info("LLMAPI initialized in dummy response mode")
        elif not self.api_key:
            logger.warning("No API key provided for LLMAPI. API calls will fail.")
        
        self.base_url = base_url or "https://api.openai.com/v1/chat/completions"
        self.model = "gpt-3.5-turbo"  # Default model
    
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
        """
        # Return dummy response if enabled
        if self.use_dummy_responses:
            logger.info("Using dummy summary response")
            return "Dummy text for summary"
        
        # Real API call
        prompt = self._create_summary_prompt(case_data)
        return self._make_llm_request(prompt, max_retries, initial_backoff)
    
    def generate_checklist(self, 
                          case_data: Dict[str, Any], 
                          max_retries: int = 3, 
                          initial_backoff: float = 1.0) -> Optional[str]:
        """Generate a checklist of tasks based on the case information.
        
        Args:
            case_data: Dictionary containing case information.
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            
        Returns:
            Generated checklist text if successful, None otherwise.
        """
        # Return dummy response if enabled
        if self.use_dummy_responses:
            logger.info("Using dummy checklist response")
            return "Dummy text for checklist"
        
        # Real API call
        prompt = self._create_checklist_prompt(case_data)
        return self._make_llm_request(prompt, max_retries, initial_backoff)
    
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
    
    def _make_llm_request(self, 
                         prompt: str, 
                         max_retries: int = 3, 
                         initial_backoff: float = 1.0) -> Optional[str]:
        """Make the API request to the LLM service.
        
        Args:
            prompt: The prompt text to send to the LLM.
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            
        Returns:
            Generated text if successful, None otherwise.
            
        Raises:
            TransientError: For temporary errors that may be resolved by retrying.
            PermanentError: For permanent errors that will not be resolved by retrying.
        """
        if not self.api_key:
            raise PermanentError("API key not configured for LLM API")
        
        retries = 0
        while retries <= max_retries:
            try:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant specializing in forensic report analysis."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500
                }
                
                logger.debug("Sending LLM API request")
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                
                # Handle response
                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and result["choices"]:
                        message_content = result["choices"][0]["message"]["content"]
                        logger.info("Successfully generated LLM response")
                        return message_content
                    else:
                        raise PermanentError(f"Missing expected data in API response: {result}")
                elif response.status_code in (429, 500, 502, 503, 504):
                    # Rate limiting or server errors - these are transient
                    raise TransientError(f"API returned status {response.status_code}: {response.text}")
                else:
                    # Client errors and other issues - these are permanent
                    raise PermanentError(f"API returned status {response.status_code}: {response.text}")
                
            except TransientError as e:
                retries += 1
                wait_time = initial_backoff * (2 ** (retries - 1))  # Exponential backoff
                logger.warning(f"Transient error on LLM request attempt {retries}/{max_retries}: {e}. Retrying in {wait_time}s")
                
                if retries <= max_retries:
                    time.sleep(wait_time)
                else:
                    logger.error(f"Maximum retries ({max_retries}) reached for LLM request")
                    break
            except PermanentError as e:
                logger.error(f"Permanent error during LLM request: {e}")
                break
            except Exception as e:
                logger.exception(f"Unexpected error during LLM request: {e}")
                break
        
        return None 