import os
import sys
import json
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add the parent directory to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent))

from patri_reports.api.anthropic import AnthropicAPI

def test_anthropic_summary():
    """Test generating a summary using the Anthropic API with Claude 3 Sonnet model."""
    try:
        # Check if API key is available
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY environment variable not set")
            return False
            
        # Load test case data
        test_file = Path(__file__).parent / "files" / "request1_expected.json"
        with open(test_file, "r", encoding="utf-8") as f:
            case_data = json.load(f)
            
        # Create Anthropic API instance
        anthropic_api = AnthropicAPI()
        
        # Generate Portuguese detailed summary
        logger.info("Generating detailed summary using Anthropic Claude 3 Sonnet...")
        summary = anthropic_api.generate_detailed_summary_pt(case_data)
        
        if not summary:
            logger.error("Failed to generate summary")
            return False
            
        logger.info("\n" + "-" * 80)
        logger.info("Generated Summary:")
        logger.info("-" * 80)
        logger.info(summary)
        logger.info("-" * 80 + "\n")
        
        return True
        
    except Exception as e:
        logger.exception(f"Error in test_anthropic_summary: {e}")
        return False

if __name__ == "__main__":
    success = test_anthropic_summary()
    sys.exit(0 if success else 1) 