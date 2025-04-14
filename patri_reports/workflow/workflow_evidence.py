"""
Main evidence collection workflow module that re-exports functionality from modular subfiles.
The code was split into multiple modules for maintainability.
"""

__all__ = [
    # Core functionality
    'handle_evidence_collection_state',
    'finish_collection_workflow',
    'cancel_collection_workflow',
    
    # Photo handling
    'process_photo_evidence',
    'process_photo_batch',
    'handle_photo_message',
    'handle_photo_batch_fingerprint_response',
    'request_photo_description',
    'handle_delete_photo',
    'rename_photo_batch',
    
    # Audio handling
    'handle_voice_message',
    'handle_photo_description',
    
    # Location handling
    'handle_location_message',
    
    # Utility functions
    'count_evidence_by_type',
    'send_evidence_prompt'
]

# Core functionality
from .workflow_evidence_core import (
    handle_evidence_collection_state,
    finish_collection_workflow,
    cancel_collection_workflow
)

# Photo handling
from .workflow_evidence_photo import (
    process_photo_evidence,
    process_photo_batch,
    handle_photo_message,
    handle_photo_batch_fingerprint_response,
    request_photo_description,
    handle_delete_photo,
    rename_photo_batch
)

# Audio handling
from .workflow_evidence_audio import (
    handle_voice_message,
    handle_photo_description
)

# Location handling
from .workflow_evidence_location import handle_location_message

# Utility functions
from .workflow_evidence_utils import count_evidence_by_type, send_evidence_prompt