#!/usr/bin/env python3
"""
Script to clean up the project for production packaging.
This script removes debug files, __pycache__ directories, and other development-only items.
"""

import os
import shutil
import re
from pathlib import Path


def clean_debug_code():
    """
    Clean debug code based on debug.txt entries.
    Removes lines marked with DEBUG_ADD comments from source files.
    """
    debug_entries = []
    try:
        with open("debug.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEBUG_ADD:") and "#" in line:
                    parts = line.split("#", 1)[0].strip()
                    if ":" in parts:
                        file_path, line_num = parts.replace("DEBUG_ADD:", "").strip().rsplit(":", 1)
                        try:
                            debug_entries.append((file_path.strip(), int(line_num)))
                        except ValueError:
                            print(f"Invalid line number in entry: {line}")
    except FileNotFoundError:
        print("debug.txt not found, skipping debug code cleanup")
        return

    for file_path, line_num in debug_entries:
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                lines = f.readlines()
            
            if 0 < line_num <= len(lines):
                print(f"Removing debug line {line_num} from {file_path}")
                # Check if line contains debug code marker
                if "DEBUG" in lines[line_num - 1] or "debug" in lines[line_num - 1].lower() or "print(" in lines[line_num - 1]:
                    lines[line_num - 1] = ""  # Remove the line
                else:
                    print(f"Warning: Line {line_num} in {file_path} doesn't look like debug code, skipping")
            
                with open(file_path, "w") as f:
                    f.writelines(lines)


def remove_debug_files():
    """Remove debug-specific files that shouldn't be included in production."""
    debug_files = [
        "debug.txt",
        "debug_state.json",
        "debug_telegram.py",
        "check_fix.py",
        "run_tests.py",
        "trace_bot.py"
    ]
    
    for file in debug_files:
        if os.path.exists(file):
            print(f"Removing debug file: {file}")
            os.remove(file)
    
    # Remove debug directories
    debug_dirs = ["debug_data", ".pytest_cache", ".history"]
    for directory in debug_dirs:
        if os.path.exists(directory) and os.path.isdir(directory):
            print(f"Removing debug directory: {directory}")
            shutil.rmtree(directory)


def clean_pycache():
    """Remove all __pycache__ directories."""
    for root, dirs, files in os.walk(".", topdown=True):
        if root.startswith("./venv"):  # Skip venv folder
            continue
            
        for dir in dirs:
            if dir == "__pycache__":
                pycache_path = os.path.join(root, dir)
                print(f"Removing __pycache__: {pycache_path}")
                shutil.rmtree(pycache_path)


def clean_test_files():
    """
    Identify and handle test files.
    For production, we'll keep the test files but ensure they're not in the main package.
    """
    # We'll keep tests in the patri_reports/tests directory
    # but remove any test_*.py files outside that directory
    for root, dirs, files in os.walk(".", topdown=True):
        if root.startswith("./venv") or "/tests/" in root:  # Skip venv folder and dedicated test directories
            continue
            
        for file in files:
            if file.startswith("test_") and file.endswith(".py"):
                file_path = os.path.join(root, file)
                print(f"Removing test file outside tests directory: {file_path}")
                os.remove(file_path)


def update_gitignore():
    """
    Check and update .gitignore to include common production patterns.
    """
    gitignore_patterns = [
        "__pycache__/",
        "*.py[cod]",
        "*$py.class",
        "*.so",
        ".env",
        "venv/",
        "ENV/",
        ".venv",
        "env/",
        ".pytest_cache/",
        "dist/",
        "build/",
        "*.egg-info/",
    ]
    
    try:
        with open(".gitignore", "r") as f:
            existing_patterns = f.read()
        
        with open(".gitignore", "a") as f:
            f.write("\n# Added for production\n")
            for pattern in gitignore_patterns:
                if pattern not in existing_patterns:
                    f.write(pattern + "\n")
    except FileNotFoundError:
        print("Creating new .gitignore for production")
        with open(".gitignore", "w") as f:
            f.write("# Python production patterns\n")
            for pattern in gitignore_patterns:
                f.write(pattern + "\n")


def create_manifest():
    """
    Create a MANIFEST.in file for proper package distribution.
    """
    with open("MANIFEST.in", "w") as f:
        f.write("include README.md\n")
        f.write("include requirements.txt\n")
        f.write("recursive-include patri_reports/prompts *.json *.txt\n")
        f.write("recursive-exclude patri_reports/tests *\n")
        f.write("recursive-exclude * __pycache__\n")
        f.write("recursive-exclude * *.py[cod]\n")
        f.write("recursive-exclude * *$py.class\n")
        f.write("recursive-exclude * *.so\n")


def create_setup_py():
    """
    Create a setup.py file if it doesn't exist.
    """
    if not os.path.exists("setup.py"):
        print("Creating setup.py for packaging")
        with open("setup.py", "w") as f:
            f.write("""from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = fh.read().splitlines()

setup(
    name="patri_reports",
    version="1.0.0",
    author="Patri Team",
    description="Patri Reports Telegram Assistant",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    include_package_data=True,
)
""")


def main():
    """Run all cleanup functions."""
    print("Starting project cleanup for production...")
    
    # Clean up debug code
    clean_debug_code()
    
    # Remove debug files
    remove_debug_files()
    
    # Clean __pycache__ directories
    clean_pycache()
    
    # Handle test files
    clean_test_files()
    
    # Update or create .gitignore
    update_gitignore()
    
    # Create MANIFEST.in for packaging
    create_manifest()
    
    # Create setup.py if it doesn't exist
    create_setup_py()
    
    print("Project cleanup completed successfully!")
    print("\nNext steps:")
    print("1. Review the changes to ensure nothing important was removed")
    print("2. Update version number in setup.py if needed")
    print("3. Build the package with: python setup.py sdist bdist_wheel")
    print("4. Deploy to your production environment")


if __name__ == "__main__":
    main() 