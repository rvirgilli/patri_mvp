#!/usr/bin/env python
"""
Test runner for the Patri Reports project.
This script runs all tests for the project and generates a report.

Features:
- Runs all tests by default
- Supports options for specific test groups (LLM, Whisper)
- Provides coverage reporting option
- Configures Anthropic API integration for testing
"""

import os
import sys
import subprocess
import argparse


def run_tests(verbose=False, coverage=False, specific_test=None, skip_failing=False):
    """Run the tests with the specified options."""
    # Construct the base command
    if coverage:
        cmd = ["coverage", "run", "-m", "pytest"]
    else:
        cmd = ["pytest"]
    
    # Add verbosity if requested
    if verbose:
        cmd.append("-v")
    
    # Skip failing tests if requested
    if skip_failing:
        cmd.append("-k")
        cmd.append("not test_collection_state_handles_finish_button and "
                   "not test_collection_state_handles_finish_button_wrong_case and "
                   "not test_collection_state_handles_text_evidence and "
                   "not test_collection_state_handles_photo_evidence and "
                   "not test_collection_state_handles_voice_evidence and "
                   "not test_finish_collection_workflow_success and "
                   "not test_finish_collection_workflow_state_fails")
    
    # Add specific test if provided
    if specific_test:
        # Handle multiple test files separated by spaces
        test_files = specific_test.split()
        cmd.extend(test_files)
    
    # Run the tests
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    
    # Generate coverage report if requested
    if coverage and result.returncode == 0:
        print("\nGenerating coverage report...")
        subprocess.run(["coverage", "report", "-m"], capture_output=False)
    
    return result.returncode


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Run tests for the Patri Reports project.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Run tests with verbose output")
    parser.add_argument("-c", "--coverage", action="store_true", help="Run tests with coverage")
    parser.add_argument("-t", "--test", type=str, help="Specific test file(s) or method(s) to run (space-separated)")
    parser.add_argument("--anthropic", action="store_true", help="Enable Anthropic API tests (requires ANTHROPIC_API_KEY)")
    parser.add_argument("--skip-failing", action="store_true", help="Skip known failing tests")
    parser.add_argument("--whisper", action="store_true", help="Run only Whisper API tests")
    parser.add_argument("--llm", action="store_true", help="Run only LLM API tests")
    args = parser.parse_args()
    
    # Set environment variables based on arguments
    if args.anthropic:
        os.environ["USE_ANTHROPIC"] = "true"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Warning: ANTHROPIC_API_KEY environment variable not set. Only mock tests will work.")
    else:
        os.environ["USE_ANTHROPIC"] = "false"
    
    # Handle specific test groups
    specific_test = args.test
    if args.whisper:
        specific_test = "patri_reports/tests/test_whisper.py"
    elif args.llm:
        specific_test = "patri_reports/tests/test_llm_api.py patri_reports/tests/test_anthropic_api.py patri_reports/tests/test_workflow_manager_llm.py"
    
    # Run the tests
    exit_code = run_tests(
        verbose=args.verbose, 
        coverage=args.coverage, 
        specific_test=specific_test,
        skip_failing=args.skip_failing
    )
    
    # Exit with the test result code
    sys.exit(exit_code)


if __name__ == "__main__":
    main() 