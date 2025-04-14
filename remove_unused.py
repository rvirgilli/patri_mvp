#!/usr/bin/env python3
"""
Script to remove unused code and files from the codebase.
This script uses the output from find_unused_code.py to allow the user to
selectively remove unused functions, classes, methods, and files.
"""

import os
import re
import sys
import ast
import shutil
import tempfile
from pathlib import Path
from collections import defaultdict


def parse_file(file_path):
    """Parse a Python file and extract its AST."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        try:
            return ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            print(f"SyntaxError in {file_path}, skipping")
            return None


def remove_function(file_path, function_name):
    """Remove a function from a Python file."""
    tree = parse_file(file_path)
    if not tree:
        return False
    
    # Find the function node
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            # Get the start and end lines
            start_line = node.lineno
            end_line = node.end_lineno
            
            # Read the file
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Remove the function
            with open(file_path, 'w', encoding='utf-8') as f:
                for i, line in enumerate(lines, 1):
                    if i < start_line or i > end_line:
                        f.write(line)
            
            print(f"✅ Removed function '{function_name}' from {file_path}")
            return True
    
    print(f"⚠️ Function '{function_name}' not found in {file_path}")
    return False


def remove_class(file_path, class_name):
    """Remove a class from a Python file."""
    tree = parse_file(file_path)
    if not tree:
        return False
    
    # Find the class node
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # Get the start and end lines
            start_line = node.lineno
            end_line = node.end_lineno
            
            # Read the file
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Remove the class
            with open(file_path, 'w', encoding='utf-8') as f:
                for i, line in enumerate(lines, 1):
                    if i < start_line or i > end_line:
                        f.write(line)
            
            print(f"✅ Removed class '{class_name}' from {file_path}")
            return True
    
    print(f"⚠️ Class '{class_name}' not found in {file_path}")
    return False


def remove_method(file_path, class_name, method_name):
    """Remove a method from a class in a Python file."""
    tree = parse_file(file_path)
    if not tree:
        return False
    
    # Find the class node
    class_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break
    
    if not class_node:
        print(f"⚠️ Class '{class_name}' not found in {file_path}")
        return False
    
    # Find the method node in the class
    for node in ast.walk(class_node):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            # Get the start and end lines
            start_line = node.lineno
            end_line = node.end_lineno
            
            # Read the file
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Remove the method
            with open(file_path, 'w', encoding='utf-8') as f:
                for i, line in enumerate(lines, 1):
                    if i < start_line or i > end_line:
                        f.write(line)
            
            print(f"✅ Removed method '{method_name}' from class '{class_name}' in {file_path}")
            return True
    
    print(f"⚠️ Method '{method_name}' not found in class '{class_name}' in {file_path}")
    return False


def remove_commented_code(file_path, start_line, end_line):
    """Remove a block of commented-out code from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Remove the commented code
        with open(file_path, 'w', encoding='utf-8') as f:
            for i, line in enumerate(lines, 1):
                if i < start_line or i > end_line:
                    f.write(line)
        
        print(f"✅ Removed commented code block (lines {start_line}-{end_line}) from {file_path}")
        return True
    except Exception as e:
        print(f"⚠️ Error removing commented code from {file_path}: {e}")
        return False


def remove_file(file_path):
    """Remove a file from the filesystem."""
    try:
        # Create a backup first
        backup_dir = os.path.join(tempfile.gettempdir(), "code_cleanup_backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_file = os.path.join(backup_dir, os.path.basename(file_path))
        shutil.copy2(file_path, backup_file)
        
        # Now remove the file
        os.remove(file_path)
        print(f"✅ Removed file {file_path} (backup at {backup_file})")
        return True
    except Exception as e:
        print(f"⚠️ Error removing file {file_path}: {e}")
        return False


def get_file_path(relative_path, base_dir="patri_reports"):
    """Convert a relative path to an absolute path."""
    # If it's already an absolute path or starts with the base directory, return as is
    if os.path.isabs(relative_path) or relative_path.startswith(base_dir):
        return relative_path
    
    # Otherwise, join with the base directory
    return os.path.join(base_dir, relative_path)


def interactive_cleanup():
    """Run an interactive cleanup process."""
    base_dir = "patri_reports"
    if not os.path.exists(base_dir):
        base_dir = input("Enter the base directory of your project: ").strip()
        if not os.path.exists(base_dir):
            print(f"Directory {base_dir} does not exist.")
            return
    
    print("\n===== INTERACTIVE CODE CLEANUP =====")
    print(f"Project directory: {base_dir}")
    print("This tool allows you to selectively remove unused code and files.")
    print("First, run find_unused_code.py to identify potentially unused code.")
    print("\nSelect an action:")
    print("1. Remove unused functions")
    print("2. Remove unused classes")
    print("3. Remove unused methods")
    print("4. Remove unused files")
    print("5. Remove commented-out code blocks")
    print("6. Exit")
    
    action = input("\nEnter your choice (1-6): ").strip()
    
    if action == "1":  # Remove unused functions
        file_path = input("Enter the file path containing the function: ").strip()
        function_name = input("Enter the function name to remove: ").strip()
        
        file_path = get_file_path(file_path, base_dir)
        
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            return
        
        confirm = input(f"Confirm removal of function '{function_name}' from {file_path}? (y/n): ").strip().lower()
        if confirm == 'y':
            remove_function(file_path, function_name)
    
    elif action == "2":  # Remove unused classes
        file_path = input("Enter the file path containing the class: ").strip()
        class_name = input("Enter the class name to remove: ").strip()
        
        file_path = get_file_path(file_path, base_dir)
        
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            return
        
        confirm = input(f"Confirm removal of class '{class_name}' from {file_path}? (y/n): ").strip().lower()
        if confirm == 'y':
            remove_class(file_path, class_name)
    
    elif action == "3":  # Remove unused methods
        file_path = input("Enter the file path containing the class: ").strip()
        class_and_method = input("Enter the class and method as 'ClassName.method_name': ").strip()
        
        if '.' not in class_and_method:
            print("Invalid format. Please use 'ClassName.method_name'.")
            return
        
        class_name, method_name = class_and_method.split('.', 1)
        
        file_path = get_file_path(file_path, base_dir)
        
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            return
        
        confirm = input(f"Confirm removal of method '{method_name}' from class '{class_name}' in {file_path}? (y/n): ").strip().lower()
        if confirm == 'y':
            remove_method(file_path, class_name, method_name)
    
    elif action == "4":  # Remove unused files
        file_path = input("Enter the file path to remove: ").strip()
        
        file_path = get_file_path(file_path, base_dir)
        
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            return
        
        confirm = input(f"Confirm removal of file {file_path}? (y/n): ").strip().lower()
        if confirm == 'y':
            remove_file(file_path)
    
    elif action == "5":  # Remove commented-out code blocks
        file_path = input("Enter the file path containing commented code: ").strip()
        line_range = input("Enter the line range as 'start-end': ").strip()
        
        if '-' not in line_range:
            print("Invalid format. Please use 'start-end'.")
            return
        
        try:
            start_line, end_line = map(int, line_range.split('-'))
        except ValueError:
            print("Invalid line numbers. Please use integers.")
            return
        
        file_path = get_file_path(file_path, base_dir)
        
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            return
        
        confirm = input(f"Confirm removal of commented code (lines {start_line}-{end_line}) from {file_path}? (y/n): ").strip().lower()
        if confirm == 'y':
            remove_commented_code(file_path, start_line, end_line)
    
    elif action == "6":  # Exit
        print("Exiting...")
        return
    
    else:
        print("Invalid action. Please choose a number from 1-6.")


def batch_cleanup(input_file):
    """
    Run a batch cleanup process from a file containing items to remove.
    
    File format:
    FUNCTION:file_path:function_name
    CLASS:file_path:class_name
    METHOD:file_path:class_name.method_name
    FILE:file_path
    COMMENT:file_path:start_line-end_line
    """
    try:
        with open(input_file, 'r') as f:
            items = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        if not items:
            print("No items found in the input file.")
            return
        
        print(f"Found {len(items)} items to process.")
        
        base_dir = "patri_reports"
        if not os.path.exists(base_dir):
            base_dir = input("Enter the base directory of your project: ").strip()
            if not os.path.exists(base_dir):
                print(f"Directory {base_dir} does not exist.")
                return
        
        for item in items:
            parts = item.split(':', 2)
            if len(parts) < 2:
                print(f"Invalid item format: {item}")
                continue
            
            item_type = parts[0].upper()
            
            if item_type == "FUNCTION" and len(parts) == 3:
                file_path, function_name = parts[1:3]
                file_path = get_file_path(file_path, base_dir)
                if os.path.exists(file_path):
                    remove_function(file_path, function_name)
                else:
                    print(f"File not found: {file_path}")
            
            elif item_type == "CLASS" and len(parts) == 3:
                file_path, class_name = parts[1:3]
                file_path = get_file_path(file_path, base_dir)
                if os.path.exists(file_path):
                    remove_class(file_path, class_name)
                else:
                    print(f"File not found: {file_path}")
            
            elif item_type == "METHOD" and len(parts) == 3:
                file_path, class_method = parts[1:3]
                if '.' not in class_method:
                    print(f"Invalid method format: {class_method}. Use 'ClassName.method_name'.")
                    continue
                
                class_name, method_name = class_method.split('.', 1)
                file_path = get_file_path(file_path, base_dir)
                if os.path.exists(file_path):
                    remove_method(file_path, class_name, method_name)
                else:
                    print(f"File not found: {file_path}")
            
            elif item_type == "FILE" and len(parts) >= 2:
                file_path = parts[1]
                file_path = get_file_path(file_path, base_dir)
                if os.path.exists(file_path):
                    remove_file(file_path)
                else:
                    print(f"File not found: {file_path}")
            
            elif item_type == "COMMENT" and len(parts) == 3:
                file_path, line_range = parts[1:3]
                if '-' not in line_range:
                    print(f"Invalid line range format: {line_range}. Use 'start-end'.")
                    continue
                
                try:
                    start_line, end_line = map(int, line_range.split('-'))
                except ValueError:
                    print(f"Invalid line numbers in range: {line_range}")
                    continue
                
                file_path = get_file_path(file_path, base_dir)
                if os.path.exists(file_path):
                    remove_commented_code(file_path, start_line, end_line)
                else:
                    print(f"File not found: {file_path}")
            
            else:
                print(f"Invalid item type or format: {item}")
    
    except Exception as e:
        print(f"Error during batch cleanup: {e}")


def main():
    """Main function to run the script."""
    print("Unused Code Removal Tool")
    print("========================")
    
    if len(sys.argv) > 1:
        # Batch mode
        input_file = sys.argv[1]
        if os.path.exists(input_file):
            print(f"Running in batch mode with input file: {input_file}")
            batch_cleanup(input_file)
        else:
            print(f"Input file not found: {input_file}")
    else:
        # Interactive mode
        interactive_cleanup()


if __name__ == "__main__":
    main() 