#!/usr/bin/env python3
"""
Script to validate production readiness of the Patri Reports project.
Checks for common issues that should be addressed before deploying to production.
"""

import os
import re
import sys
from pathlib import Path
import importlib.util


def check_debug_statements(directory="patri_reports"):
    """
    Check for debug statements (print, logging.debug) in Python files.
    Returns a list of (file_path, line_number, line_content) tuples.
    """
    debug_statements = []
    debug_patterns = [
        r'print\s*\(',
        r'logging\.debug\s*\(',
        r'# DEBUG',
        r'# FIXME',
        r'# TODO',
        r'console\.log\('
    ]
    
    compiled_patterns = [re.compile(pattern) for pattern in debug_patterns]
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for i, line in enumerate(f, 1):
                        for pattern in compiled_patterns:
                            if pattern.search(line):
                                debug_statements.append((file_path, i, line.strip()))
                                break
    
    return debug_statements


def check_env_variables():
    """
    Check if .env file exists and all necessary environment variables are defined.
    Returns a list of missing/empty environment variables.
    """
    required_vars = [
        "TELEGRAM_BOT_TOKEN",
        "ADMIN_CHAT_ID",
        "LLM_API_KEY",
        "LLM_API_URL",
        "WHISPER_API_KEY"
    ]
    
    missing_vars = []
    
    if not os.path.exists(".env"):
        return ["Missing .env file"]
    
    with open(".env", 'r') as f:
        env_content = f.read()
    
    for var in required_vars:
        if var not in env_content or re.search(rf"{var}=\s*$", env_content):
            missing_vars.append(var)
    
    return missing_vars


def check_setup_py():
    """
    Check if setup.py exists and has required fields.
    Returns a list of issues.
    """
    issues = []
    
    if not os.path.exists("setup.py"):
        return ["Missing setup.py file"]
    
    with open("setup.py", 'r') as f:
        setup_content = f.read()
    
    required_fields = [
        "name=",
        "version=",
        "description=",
        "packages=",
        "install_requires=",
    ]
    
    for field in required_fields:
        if field not in setup_content:
            issues.append(f"Missing {field} in setup.py")
    
    return issues


def check_requirements():
    """
    Check if requirements.txt exists and has all required packages.
    Returns a list of issues.
    """
    issues = []
    
    if not os.path.exists("requirements.txt"):
        return ["Missing requirements.txt file"]
    
    with open("requirements.txt", 'r') as f:
        requirements = f.read()
    
    required_packages = [
        "python-dotenv",
        "python-telegram-bot",
        "requests"
    ]
    
    for package in required_packages:
        if package not in requirements:
            issues.append(f"Missing {package} in requirements.txt")
    
    return issues


def check_readme():
    """
    Check if README.md exists and has adequate content.
    Returns a list of issues.
    """
    issues = []
    
    if not os.path.exists("README.md"):
        return ["Missing README.md file"]
    
    with open("README.md", 'r') as f:
        readme = f.read()
    
    min_readme_length = 100  # Characters
    if len(readme) < min_readme_length:
        issues.append(f"README.md is too short ({len(readme)} chars < {min_readme_length})")
    
    required_sections = [
        "# Patri Reports",
        "## Installation",
        "## Usage",
    ]
    
    for section in required_sections:
        if section not in readme:
            issues.append(f"Missing section '{section}' in README.md")
    
    return issues


def check_test_coverage():
    """
    Check if the main modules have corresponding test files.
    Returns a list of modules without tests.
    """
    modules_without_tests = []
    
    # Get all Python modules in patri_reports
    modules = []
    for root, dirs, files in os.walk("patri_reports"):
        if "tests" in root or "__pycache__" in root:
            continue
        
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                module_path = os.path.join(root, file)
                modules.append(module_path)
    
    # Check for corresponding test files
    for module in modules:
        module_name = os.path.basename(module).replace(".py", "")
        test_file = f"patri_reports/tests/test_{module_name}.py"
        
        if not os.path.exists(test_file):
            modules_without_tests.append(module)
    
    return modules_without_tests


def check_imports():
    """
    Check if all imported modules are in requirements.txt.
    Returns a list of potentially missing dependencies.
    """
    # Get requirements from requirements.txt
    if not os.path.exists("requirements.txt"):
        return ["Missing requirements.txt file"]
    
    with open("requirements.txt", 'r') as f:
        requirements = [line.strip().split('==')[0].split('>=')[0] for line in f if line.strip()]
    
    # Add standard library modules to ignore
    standard_libs = [
        "os", "sys", "re", "json", "time", "datetime", "pathlib", 
        "typing", "enum", "abc", "collections", "functools", "itertools",
        "math", "random", "uuid", "hashlib", "base64", "logging", "io",
        "argparse", "configparser", "csv", "pickle", "shutil", "stat",
        "importlib", "inspect", "asyncio", "concurrent", "threading",
        "multiprocessing", "socket", "http", "urllib", "email", "ssl",
        "tempfile", "warnings"
    ]
    
    # Standard library extensions (modules that are part of standard modules)
    standard_extensions = {
        "Path": "pathlib",
        "json.loads": "json",
        "datetime.datetime": "datetime"
    }
    
    # Handle special cases (package name differs from import name)
    special_cases = {
        "telegram": "python-telegram-bot",
        "dotenv": "python-dotenv",
        "pytest": "pytest",
    }
    
    missing_imports = set()
    
    # Check all Python files for imports
    for root, dirs, files in os.walk("patri_reports"):
        if "__pycache__" in root:
            continue
            
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Find all import statements
                import_matches = re.findall(r'^\s*import\s+([^\s]+)', content, re.MULTILINE)
                from_matches = re.findall(r'^\s*from\s+([^\s\.]+)', content, re.MULTILINE)
                
                imports = set(import_matches + from_matches)
                
                # Check each import
                for imp in imports:
                    # Skip if it's a relative import
                    if imp.startswith("."):
                        continue
                        
                    # Skip standard library modules
                    if imp in standard_libs or any(imp.startswith(f"{std_lib}.") for std_lib in standard_libs):
                        continue
                    
                    # Skip standard extensions
                    if imp in standard_extensions:
                        continue
                    
                    # Handle special cases
                    if imp in special_cases:
                        if special_cases[imp] not in requirements:
                            missing_imports.add(f"{imp} (as {special_cases[imp]})")
                        continue
                    
                    # Check if in requirements
                    if imp not in requirements and not any(req.startswith(imp) for req in requirements):
                        # Try to check if it's locally available
                        if not os.path.exists(os.path.join("patri_reports", imp.replace(".", "/"))) and \
                           not os.path.exists(os.path.join("patri_reports", imp.replace(".", "/") + ".py")):
                            # Try to import it to verify it's not a standard library
                            try:
                                importlib.util.find_spec(imp)
                            except ImportError:
                                missing_imports.add(imp)
    
    return list(missing_imports)


def main():
    """Run all validation checks and report results."""
    print("Validating project for production readiness...")
    
    # Define all checks to run with their display names
    checks = [
        ("Debug Statements", check_debug_statements),
        ("Environment Variables", check_env_variables),
        ("Setup.py", check_setup_py),
        ("Requirements.txt", check_requirements),
        ("README.md", check_readme),
        ("Test Coverage", check_test_coverage),
        ("Dependencies", check_imports)
    ]
    
    issues_found = False
    
    for check_name, check_function in checks:
        print(f"\nRunning check: {check_name}...")
        results = check_function()
        
        if results:
            issues_found = True
            print(f"❌ {check_name} check failed. Issues found:")
            for issue in results:
                print(f"  - {issue}")
        else:
            print(f"✅ {check_name} check passed.")
    
    print("\nValidation completed.")
    
    if issues_found:
        print("\n⚠️ Issues were found that should be addressed before deploying to production.")
        print("Run './cleanup_for_production.py' to address some of these issues automatically.")
    else:
        print("\n🎉 All validation checks passed! The project is ready for production.")


if __name__ == "__main__":
    main() 