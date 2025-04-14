import logging
from typing import Optional, Tuple, TYPE_CHECKING
import json

from ..utils.error_handler import NetworkError
from ..models.case import CaseInfo
from ..api.anthropic import AnthropicAPI, AnthropicError
from ..utils.text_utils import escape_markdown, format_telegram_markdown

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

def _create_anthropic_api(workflow_manager: 'WorkflowManager') -> AnthropicAPI:
    """Create an AnthropicAPI instance with the correct settings from the workflow manager.
    
    Args:
        workflow_manager: The workflow manager instance with configuration settings
        
    Returns:
        An initialized AnthropicAPI instance
    """
    # Use the workflow_manager's dummy API flag if set
    return workflow_manager.anthropic_api

async def generate_llm_summary(workflow_manager: 'WorkflowManager', user_id: int, case_id: str):
    """Generate and save a summary for the case using Anthropic's Claude 3 Sonnet model."""
    if not workflow_manager.telegram_client:
        return
    
    # Send status message
    status_message = await workflow_manager.telegram_client.send_message(user_id, "⏳ Gerando resumo detalhado do caso com IA...")
    
    try:
        # Get case data
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text="❌ Não foi possível carregar os dados do caso para geração do resumo."
            )
            return
        
        try:
            # Convert case_info to dictionary if it's not already
            if not isinstance(case_info, dict):
                try:
                    # Try to use the to_dict method first
                    case_data = case_info.to_dict()
                except (AttributeError, Exception) as e:
                    logger.warning(f"Failed to convert case_info to dict using to_dict: {e}")
                    # Fallback to model_dump for Pydantic v2 or dict for Pydantic v1
                    if hasattr(case_info, "model_dump"):
                        case_data = case_info.model_dump()
                    else:
                        case_data = case_info.dict()
            else:
                case_data = case_info
                
            # Use the workflow manager's anthropic_api instance which is already configured with use_dummy_apis
            logger.info(f"Generating detailed summary using Anthropic Claude 3 Sonnet for case {case_id}")
            
            # Update status message
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text="⏳ Conectando com a API Anthropic Claude 3 Sonnet..."
            )
            
            summary = workflow_manager.anthropic_api.generate_detailed_summary_pt(case_data)
            
            if not summary:
                logger.error(f"Failed to generate summary with Anthropic API for case {case_id}")
                # Fallback to basic summary generator
                logger.info(f"Falling back to basic summary generator for case {case_id}")
                summary = generate_basic_summary(workflow_manager, case_info)
        except AnthropicError as e:
            logger.exception(f"Error with Anthropic API: {e}")
            # Fallback to basic summary generator
            logger.info(f"Falling back to basic summary generator due to API error for case {case_id}")
            summary = generate_basic_summary(workflow_manager, case_info)
        except Exception as e:
            logger.exception(f"Unexpected error during summary generation with Anthropic: {e}")
            # Fallback to basic summary generator
            logger.info(f"Falling back to basic summary generator due to unexpected error for case {case_id}")
            summary = generate_basic_summary(workflow_manager, case_info)
        
        if not summary:
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text="❌ Falha ao gerar o resumo. Por favor, tente novamente mais tarde."
            )
            return
        
        # Save summary to case
        if not workflow_manager.case_manager.update_llm_data(case_id, summary=summary):
            await workflow_manager.telegram_client.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text="❌ Falha ao salvar o resumo no caso. Por favor, tente novamente."
            )
            return
        
        # Update message with success
        await workflow_manager.telegram_client.edit_message_text(
            chat_id=user_id,
            message_id=status_message.message_id,
            text="✅ Resumo detalhado gerado e salvo com sucesso."
        )
        
        # Send the summary as plain text (no Markdown)
        await workflow_manager.telegram_client.send_message(
            user_id, 
            summary, 
            parse_mode=None
        )
        
        # Update pinned status message
        from .workflow_status import update_case_status_message
        await update_case_status_message(workflow_manager, user_id, case_id)
        
        # Show evidence collection prompt again
        from .workflow_evidence import send_evidence_prompt
        await send_evidence_prompt(workflow_manager, user_id, case_id)
        
    except Exception as e:
        logger.exception(f"Error generating summary for case {case_id}: {e}")
        await workflow_manager.telegram_client.edit_message_text(
            chat_id=user_id,
            message_id=status_message.message_id,
            text="❌ Ocorreu um erro ao gerar o resumo do caso."
        )

async def generate_summary_and_checklist(workflow_manager: 'WorkflowManager', case_info) -> Optional[str]:
    """
    Generate summary for a case with error handling.
    
    Args:
        workflow_manager: The WorkflowManager instance
        case_info: Case information to generate summary from
        
    Returns:
        Generated summary text
        
    Raises:
        NetworkError: If there's a network error with the LLM API
    """
    try:
        # Try to use Anthropic API for summary generation
        if not isinstance(case_info, dict):
            try:
                # Try to use the to_dict method first
                case_data = case_info.to_dict()
            except (AttributeError, Exception) as e:
                logger.warning(f"Failed to convert case_info to dict using to_dict: {e}")
                # Fallback to model_dump for Pydantic v2 or dict for Pydantic v1
                if hasattr(case_info, "model_dump"):
                    case_data = case_info.model_dump()
                else:
                    case_data = case_info.dict()
        else:
            case_data = case_info
            
        try:
            # Use the workflow manager's anthropic_api instance which is already configured with use_dummy_apis
            logger.info("Attempting to generate detailed summary with Anthropic Claude 3 Sonnet")
            summary = workflow_manager.anthropic_api.generate_detailed_summary_pt(case_data)
        except (AnthropicError, Exception) as e:
            logger.warning(f"Failed to generate summary with Anthropic API: {e}")
            logger.info("Falling back to basic summary generator")
            summary = generate_basic_summary(workflow_manager, case_info)
    except Exception as e:
        logger.exception(f"Error in summary generation: {e}")
        summary = generate_basic_summary(workflow_manager, case_info)
    
    return summary

def generate_basic_summary(workflow_manager: 'WorkflowManager', case_info) -> str:
    """Generate a basic summary from case information if LLM summary is not available."""
    summary_parts = []
    
    if isinstance(case_info, dict):
        # Dictionary case
        case_id = case_info.get("case_id", "Unknown")
        location = case_info.get("location", {})
        address = location.get("address", "Unknown")
        metadata = case_info.get("metadata", {})
        title = metadata.get("title", "")
        reference = metadata.get("reference", "")
        
        summary_parts.append(f"📋 CASE SUMMARY: {case_id}")
        
        if "requesting_unit" in case_info:
            # Escape special markdown characters
            requesting_unit = escape_markdown(str(case_info['requesting_unit']))
            summary_parts.append(f"Requesting Unit: {requesting_unit}")
        if "authority" in case_info:
            # Escape special markdown characters
            authority = escape_markdown(str(case_info['authority']))
            summary_parts.append(f"Authority: {authority}")
        if "city" in case_info:
            # Escape special markdown characters
            city = escape_markdown(str(case_info['city']))
            summary_parts.append(f"City: {city}")
        
        # Escape special markdown characters
        address = escape_markdown(str(address))
        summary_parts.append(f"Address: {address}")
        
        if title:
            # Escape special markdown characters
            title = escape_markdown(str(title))
            summary_parts.append(f"Title: {title}")
        if reference:
            # Escape special markdown characters
            reference = escape_markdown(str(reference))
            summary_parts.append(f"Reference: {reference}")
            
    else:
        # CaseInfo object case
        summary_parts.append(f"📋 CASE SUMMARY: {case_info.get_display_id()}")
        
        if case_info.requesting_unit:
            # Escape special markdown characters
            requesting_unit = escape_markdown(str(case_info.requesting_unit))
            summary_parts.append(f"Requesting Unit: {requesting_unit}")
        if case_info.authority:
            # Escape special markdown characters
            authority = escape_markdown(str(case_info.authority))
            summary_parts.append(f"Authority: {authority}")
        if case_info.city:
            # Escape special markdown characters
            city = escape_markdown(str(case_info.city))
            summary_parts.append(f"City: {city}")
        if case_info.address:
            # Escape special markdown characters
            address = escape_markdown(str(case_info.address))
            summary_parts.append(f"Address: {address}")
            
        # Add first history item if available
        if case_info.history and len(case_info.history) > 0:
            first_history = case_info.history[0]
            # Escape special markdown characters
            title = escape_markdown(str(first_history.title))
            content = escape_markdown(str(first_history.content[:200]))
            summary_parts.append(f"\n{title}: {content}...")
            
    return "\n".join(summary_parts)
    
def generate_basic_checklist(workflow_manager: 'WorkflowManager', case_info) -> str:
    """Generate a basic evidence checklist if LLM checklist is not available."""
    checklist_parts = []
    checklist_parts.append("📝 EVIDENCE CHECKLIST:")
    
    # Standard checklist items
    checklist_items = [
        "📷 Photograph the general scene",
        "📷 Close-up photos of relevant items",
        "📝 Record witness statements",
        "🔍 Check for fingerprints"
    ]
    
    # Add specific items based on traces (only for CaseInfo objects)
    if not isinstance(case_info, dict) and hasattr(case_info, 'traces') and case_info.traces:
        for trace in case_info.traces:
            # Escape special markdown characters
            trace_type = escape_markdown(str(trace.type))
            trace_id = escape_markdown(str(trace.id))
            checklist_items.append(f"🔍 Document evidence: {trace_type} (ID: {trace_id})")
    
    # Add standard numbered format
    for i, item in enumerate(checklist_items, 1):
        checklist_parts.append(f"{i}. {item}")
        
    return "\n".join(checklist_parts)

async def generate_case_summary(workflow_manager: 'WorkflowManager', user_id: int, case_id: str) -> Optional[str]:
    """Generate a summary for a case.
    
    Args:
        workflow_manager: The workflow manager instance
        user_id: The Telegram user ID
        case_id: The ID of the case
        
    Returns:
        The generated summary text, or None if there was an error
    """
    try:
        logger.info(f"Generating summary for case {case_id}")
        
        # Load the case
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Failed to load case {case_id} for summary generation")
            return None
            
        # Generate the summary
        summary = await generate_summary_and_checklist(workflow_manager, case_info)
        
        if summary:
            # Save the summary to the case
            workflow_manager.case_manager.update_llm_data(case_id, summary=summary)
            
            logger.info(f"Successfully generated summary for case {case_id}")
            return summary
        else:
            logger.warning(f"Empty summary generated for case {case_id}")
            return None
    except Exception as e:
        logger.exception(f"Error generating summary for case {case_id}: {e}")
        return None

async def generate_case_checklist(workflow_manager: 'WorkflowManager', case_id: str) -> Optional[str]:
    """Generate a checklist for a case.
    
    Args:
        workflow_manager: The workflow manager instance
        case_id: The ID of the case
        
    Returns:
        The generated checklist text, or None if there was an error
    """
    try:
        logger.info(f"Generating checklist for case {case_id}")
        
        # Load the case
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Failed to load case {case_id} for checklist generation")
            return None
            
        # Convert to dictionary if needed for API calls
        if not isinstance(case_info, dict):
            try:
                # Try to use the to_dict method first
                case_data = case_info.to_dict()
            except (AttributeError, Exception) as e:
                logger.warning(f"Failed to convert case_info to dict using to_dict: {e}")
                # Fallback to model_dump for Pydantic v2 or dict for Pydantic v1
                if hasattr(case_info, "model_dump"):
                    case_data = case_info.model_dump()
                else:
                    case_data = case_info.dict()
        else:
            case_data = case_info
            
        # Try to use LLM API for generating a checklist
        try:
            # Use the LLM API already initialized with use_dummy_apis in the workflow manager
            checklist = workflow_manager.llm_api.generate_checklist(case_data)
            
            if checklist:
                logger.info(f"Successfully generated checklist using LLM API for case {case_id}")
                return checklist
            else:
                logger.warning(f"Empty checklist returned by LLM API for case {case_id}")
                # Fall back to basic checklist
                return generate_basic_checklist(workflow_manager, case_info)
        except Exception as e:
            logger.warning(f"Error generating checklist with LLM API: {e}")
            logger.info(f"Falling back to basic checklist for case {case_id}")
            # Fall back to basic checklist generator
            checklist = generate_basic_checklist(workflow_manager, case_info)
            
            if checklist:
                logger.info(f"Successfully generated basic checklist for case {case_id}")
                return checklist
            else:
                logger.warning(f"Empty basic checklist generated for case {case_id}")
                return None
    except Exception as e:
        logger.exception(f"Error generating checklist for case {case_id}: {e}")
        return None

async def send_occurrence_briefing(workflow_manager: 'WorkflowManager', user_id: int, case_id: str) -> bool:
    """
    Generate and send occurrence briefing (summary and checklist) to the user.
    
    Args:
        workflow_manager: The workflow manager instance
        user_id: The user ID to send the briefing to
        case_id: The case ID
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Load the case
        case_info = workflow_manager.case_manager.load_case(case_id)
        if not case_info:
            logger.error(f"Failed to load case {case_id} for briefing")
            return False
            
        # Send case briefing header
        await workflow_manager.telegram_client.send_message(
            user_id,
            "🔍 Relatório do Caso",
            parse_mode=None
        )
        
        # Generate summary
        summary = await generate_case_summary(workflow_manager, user_id, case_id)
        
        # Send summary if available
        if summary:
            # Send summary as plain text
            await workflow_manager.telegram_client.send_message(
                user_id,
                summary,
                parse_mode=None
            )
            
            # Update case with summary
            workflow_manager.case_manager.update_llm_data(case_id, summary=summary)
        
        # Send location information if available
        if case_info and hasattr(case_info, 'address') and case_info.address:
            location_text = f"📍 Localização\n\n{case_info.address}"
            
            # Add city if available
            if hasattr(case_info, 'city') and case_info.city:
                location_text += f"\n{case_info.city}"
                
            # Add coordinates if available
            if hasattr(case_info, 'coordinates') and case_info.coordinates:
                lat, lon = case_info.coordinates
                location_text += f"\n\nCoordenadas: {lat}, {lon}"
                
                # Send location message
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    location_text,
                    parse_mode=None
                )
                
                # Also send map location
                try:
                    await workflow_manager.telegram_client.send_location(
                        user_id,
                        latitude=lat,
                        longitude=lon
                    )
                except Exception as e:
                    logger.warning(f"Failed to send map location for case {case_id}: {e}")
            else:
                # Just send text if no coordinates
                await workflow_manager.telegram_client.send_message(
                    user_id,
                    location_text,
                    parse_mode=None
                )
        
        # Don't send a separate checklist message as it's already included in the summary
        
        return True
    except Exception as e:
        logger.error(f"Error sending occurrence briefing for case {case_id}: {e}")
        return False 