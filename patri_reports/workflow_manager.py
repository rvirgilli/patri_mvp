"""
Main workflow manager module for the Patri Reports Telegram bot.
This file re-exports the WorkflowManager class from the modular implementation.
"""

from .workflow.workflow_core import WorkflowManager

# Re-export the WorkflowManager class
__all__ = ['WorkflowManager']