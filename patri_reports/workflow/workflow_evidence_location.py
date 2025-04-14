import logging
from typing import TYPE_CHECKING

from telegram import Location

from .workflow_status import update_case_status_message
from .workflow_evidence_utils import print_debug, send_evidence_prompt, get_evidence_summary_message

if TYPE_CHECKING:
    from .workflow_core import WorkflowManager

logger = logging.getLogger(__name__)

async def handle_location_message(workflow_manager: 'WorkflowManager', user_id: int, case_id: str, location: Location):
    """Handles incoming location messages for a case. Only the most recent location is stored."""
    print_debug(f"ENTER handle_location_message for case {case_id}, user {user_id}")
    if not workflow_manager.telegram_client:
        print_debug(f"EXIT handle_location_message - No telegram_client")
        return
    
    logger.info(f"Processing location for case {case_id}")
    print_debug(f"Location data: latitude={location.latitude}, longitude={location.longitude}")
    
    try:
        # Get location data
        latitude = location.latitude
        longitude = location.longitude
        
        # Check if a previous location was stored
        case_info = workflow_manager.case_manager.load_case(case_id)
        print_debug(f"Case loaded: {case_info is not None}")
        if case_info:
            print_debug(f"Case ID: {case_info.case_id}")
            print_debug(f"Has attendance_location attribute: {hasattr(case_info, 'attendance_location')}")
            
        had_previous_location = hasattr(case_info, 'attendance_location') and case_info.attendance_location is not None
        print_debug(f"Had previous location: {had_previous_location}")
        if had_previous_location:
            print_debug(f"Previous location: {case_info.attendance_location}")
        
        # Update case with location coordinates in the attendance_location field
        print_debug(f"Calling update_case_attendance_location")
        update_result = workflow_manager.case_manager.update_case_attendance_location(case_id, latitude, longitude)
        print_debug(f"update_case_attendance_location result: {update_result}")
        
        if update_result:
            # Reload case info after update
            case_info = workflow_manager.case_manager.load_case(case_id)
            print_debug(f"Case reloaded after update, has attendance_location: {hasattr(case_info, 'attendance_location')}")
            if hasattr(case_info, 'attendance_location'):
                print_debug(f"Updated attendance_location: {case_info.attendance_location}")
            
            # Update the pinned status message
            print_debug(f"Calling update_case_status_message after adding location for {case_id}")
            await update_case_status_message(workflow_manager, user_id, case_id, case_info=case_info)
            
            # Generate location confirmation message
            location_status = "Location updated" if had_previous_location else "Location saved"
            
            # Get evidence summary
            summary_message = await get_evidence_summary_message(case_info)
            confirmation_message = f"📍 {location_status} successfully.\n\n{summary_message}"
            
            # Send confirmation with evidence summary
            await workflow_manager.telegram_client.send_message(user_id, confirmation_message)
        else:
            logger.error(f"Failed to update location for case {case_id} - update_case_attendance_location returned False")
            await workflow_manager.telegram_client.send_message(
                user_id,
                "❌ Failed to save location. Please try again."
            )
    except Exception as e:
        logger.exception(f"Error processing location for case {case_id}: {e}")
        print_debug(f"Exception in handle_location_message: {str(e)}")
        await workflow_manager.telegram_client.send_message(user_id, "An error occurred while saving the location.")
        
    # Remove the duplicate evidence collection prompt
    print_debug(f"EXIT handle_location_message for case {case_id}") 