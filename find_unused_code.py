#!/usr/bin/env python3
"""
Script to find unused code (functions, classes, methods) in the Python codebase.
This performs static code analysis to identify code that's not referenced elsewhere.
"""

import os
import re
import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


class DefinitionFinder(ast.NodeVisitor):
    """Find all function and class definitions in the code."""
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.module_name = os.path.basename(file_path).replace('.py', '')
        self.definitions = set()
        self.classes = set()
        self.methods = defaultdict(set)
        self.exports = set()  # Names in __all__
        
    def visit_FunctionDef(self, node):
        # Skip if this is a method in a class
        if isinstance(node.parent, ast.ClassDef):
            # Track as a method
            class_name = node.parent.name
            self.methods[class_name].add(node.name)
        else:
            # This is a module-level function
            self.definitions.add(node.name)
        
        # Continue visiting child nodes
        self.generic_visit(node)
        
    def visit_ClassDef(self, node):
        self.classes.add(node.name)
        
        # Continue visiting child nodes (methods)
        self.generic_visit(node)
        
    def visit_Assign(self, node):
        # Check for __all__ = [...] to find explicitly exported names
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == '__all__':
                if isinstance(node.value, ast.List):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Str):
                            self.exports.add(elt.s)
        self.generic_visit(node)


class ReferenceFinder(ast.NodeVisitor):
    """Find all references to functions, classes, and methods in the code."""
    
    def __init__(self):
        self.references = set()
        self.imports = defaultdict(set)  # module -> {names}
        self.from_imports = defaultdict(set)  # module -> {names}
        
    def visit_Name(self, node):
        # Record any name that's being used (not just defined)
        if isinstance(node.ctx, ast.Load):
            self.references.add(node.id)
        self.generic_visit(node)
        
    def visit_Attribute(self, node):
        # Handle attribute access like module.function or class.method
        if isinstance(node.value, ast.Name):
            self.references.add(f"{node.value.id}.{node.attr}")
        self.generic_visit(node)
        
    def visit_Import(self, node):
        # Track standard imports
        for name in node.names:
            self.imports[name.name].add(name.asname or name.name)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        # Track from-imports
        if node.module:
            for name in node.names:
                if name.name == '*':
                    self.from_imports[node.module].add('*')
                else:
                    self.from_imports[node.module].add(name.name)
                    # Also track the imported name as a reference
                    self.references.add(name.asname or name.name)
        self.generic_visit(node)


def add_parent_refs(node, parent=None):
    """Add parent references to all nodes in the AST."""
    node.parent = parent
    for child in ast.iter_child_nodes(node):
        add_parent_refs(child, node)
    return node


def parse_file(file_path):
    """Parse a Python file and return its AST."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        try:
            tree = ast.parse(f.read(), filename=file_path)
            return add_parent_refs(tree)
        except SyntaxError:
            print(f"SyntaxError in {file_path}, skipping")
            return None


def find_all_python_files(directory):
    """Find all Python files in the given directory recursively."""
    python_files = []
    for root, dirs, files in os.walk(directory):
        if "__pycache__" in root or "venv" in root:
            continue
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    return python_files


def find_unused_code(directory="patri_reports"):
    """Find unused functions, classes, and methods in the codebase."""
    # Get all Python files
    python_files = find_all_python_files(directory)
    
    # Gather all definitions and references
    all_definitions = {}  # file_path -> DefinitionFinder
    all_references = {}   # file_path -> ReferenceFinder
    
    # First pass: collect definitions
    for file_path in python_files:
        tree = parse_file(file_path)
        if tree:
            def_finder = DefinitionFinder(file_path)
            def_finder.visit(tree)
            all_definitions[file_path] = def_finder
    
    # Second pass: collect references
    for file_path in python_files:
        tree = parse_file(file_path)
        if tree:
            ref_finder = ReferenceFinder()
            ref_finder.visit(tree)
            all_references[file_path] = ref_finder
    
    # Analyze imports to build a map of possible references
    import_references = defaultdict(set)
    for file_path, ref_finder in all_references.items():
        # For each import, add potential references
        for module, aliases in ref_finder.imports.items():
            # Handle direct imports
            for alias in aliases:
                import_references[module].add(alias)
        
        # For each from-import, add the specific names
        for module, names in ref_finder.from_imports.items():
            # If importing *, all names might be imported
            if '*' in names:
                # Find definitions in that module
                for def_file, def_finder in all_definitions.items():
                    if os.path.basename(def_file).replace('.py', '') == module.split('.')[-1]:
                        for name in def_finder.definitions:
                            import_references[f"{module}.{name}"].add(name)
                        for class_name in def_finder.classes:
                            import_references[f"{module}.{class_name}"].add(class_name)
            else:
                # Only specific names are imported
                for name in names:
                    import_references[f"{module}.{name}"].add(name)
    
    # Find unused definitions
    unused_functions = []
    unused_classes = []
    unused_methods = []
    
    # Check each file's definitions
    for file_path, def_finder in all_definitions.items():
        module_name = def_finder.module_name
        file_relative = os.path.relpath(file_path, directory)
        
        # Get all references across all files
        all_refs = set()
        for ref_data in all_references.values():
            all_refs.update(ref_data.references)
        
        # Check functions
        for func_name in def_finder.definitions:
            # Skip if function name starts with _ (likely private/internal)
            if func_name.startswith('_') and not func_name.startswith('__'):
                continue
                
            # Skip if in __all__
            if func_name in def_finder.exports:
                continue
                
            # Look for references to this function
            is_used = False
            
            # Check direct references
            if func_name in all_refs:
                is_used = True
                
            # Check qualified references (module.function)
            possible_qualnames = [
                f"{module_name}.{func_name}",
                f"{os.path.basename(os.path.dirname(file_path))}.{module_name}.{func_name}"
            ]
            for qualname in possible_qualnames:
                if qualname in all_refs:
                    is_used = True
                    break
            
            # Check if the function might be used via imports
            for import_path, refs in import_references.items():
                if import_path.endswith(f".{func_name}") and not is_used:
                    is_used = True
                    break
            
            if not is_used:
                unused_functions.append((func_name, file_relative))
        
        # Check classes
        for class_name in def_finder.classes:
            # Skip if class name starts with _ (likely private/internal)
            if class_name.startswith('_') and not class_name.startswith('__'):
                continue
                
            # Skip if in __all__
            if class_name in def_finder.exports:
                continue
                
            # Look for references to this class
            is_used = False
            
            # Check direct references
            if class_name in all_refs:
                is_used = True
                
            # Check qualified references (module.class)
            possible_qualnames = [
                f"{module_name}.{class_name}",
                f"{os.path.basename(os.path.dirname(file_path))}.{module_name}.{class_name}"
            ]
            for qualname in possible_qualnames:
                if qualname in all_refs:
                    is_used = True
                    break
            
            # Check if the class might be used via imports
            for import_path, refs in import_references.items():
                if import_path.endswith(f".{class_name}") and not is_used:
                    is_used = True
                    break
            
            if not is_used:
                unused_classes.append((class_name, file_relative))
                
                # Since the class is unused, all its methods are technically unused
                for method_name in def_finder.methods[class_name]:
                    unused_methods.append((f"{class_name}.{method_name}", file_relative))
            else:
                # Check unused methods in used classes
                for method_name in def_finder.methods[class_name]:
                    # Skip methods that start with _ (likely private/internal)
                    if method_name.startswith('_') and not method_name.startswith('__'):
                        continue
                        
                    # Skip standard methods
                    if method_name in ('__init__', '__str__', '__repr__', '__enter__', '__exit__'):
                        continue
                        
                    # Check for method references
                    method_is_used = False
                    possible_method_refs = [
                        f"{class_name}.{method_name}",
                        f"{module_name}.{class_name}.{method_name}"
                    ]
                    
                    for method_ref in possible_method_refs:
                        if method_ref in all_refs:
                            method_is_used = True
                            break
                    
                    if not method_is_used:
                        unused_methods.append((f"{class_name}.{method_name}", file_relative))
    
    return unused_functions, unused_classes, unused_methods


def find_duplicate_code(directory="patri_reports"):
    """Find potential duplicate code in the codebase."""
    # This is a simple implementation - real duplicate detection would be more sophisticated
    python_files = find_all_python_files(directory)
    
    # Extract function bodies
    function_bodies = []
    
    for file_path in python_files:
        tree = parse_file(file_path)
        if not tree:
            continue
            
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Get the source lines for this function
                try:
                    function_lines = []
                    for i in range(node.lineno, node.end_lineno + 1):
                        with open(file_path, 'r') as f:
                            content = f.readlines()
                            if i <= len(content):
                                function_lines.append(content[i-1])
                    
                    # Skip very short functions
                    if len(function_lines) <= 3:
                        continue
                        
                    function_bodies.append({
                        'name': node.name,
                        'file': file_path,
                        'lines': len(function_lines),
                        'content': ''.join(function_lines)
                    })
                except:
                    # Skip if we can't extract the source
                    pass
    
    # Find potential duplicates (simple approach by comparing function lengths)
    potential_duplicates = []
    
    # Group functions by line count
    by_length = defaultdict(list)
    for func in function_bodies:
        by_length[func['lines']].append(func)
    
    # Look for functions with similar content
    for length, funcs in by_length.items():
        if len(funcs) <= 1:
            continue
            
        for i in range(len(funcs)):
            for j in range(i+1, len(funcs)):
                f1, f2 = funcs[i], funcs[j]
                
                # Simplistic similarity check
                similarity = 0
                for line1, line2 in zip(f1['content'].splitlines(), f2['content'].splitlines()):
                    # Ignore whitespace, comments, and imports
                    if line1.strip() == line2.strip() and not line1.strip().startswith('#') and 'import' not in line1:
                        similarity += 1
                
                # If more than 70% similar, consider as potential duplicate
                similarity_ratio = similarity / length
                if similarity_ratio > 0.7:
                    potential_duplicates.append((f1, f2, similarity_ratio))
    
    return potential_duplicates


def find_unused_files(directory="patri_reports"):
    """
    Find files that aren't imported or referenced elsewhere.
    This is a heuristic approach and may have false positives.
    """
    python_files = find_all_python_files(directory)
    module_names = {os.path.basename(f).replace('.py', ''): f for f in python_files}
    
    # Collect imports
    all_imports = set()
    for file_path in python_files:
        tree = parse_file(file_path)
        if not tree:
            continue
        
        ref_finder = ReferenceFinder()
        ref_finder.visit(tree)
        
        for module in ref_finder.imports.keys():
            all_imports.add(module.split('.')[-1])  # Get the last part of the module path
            
        for module in ref_finder.from_imports.keys():
            if module:  # Skip relative imports
                all_imports.add(module.split('.')[-1])
    
    # Find files not imported
    unused_files = []
    for module, file_path in module_names.items():
        # Skip __init__.py files
        if module == '__init__':
            continue
            
        # Skip main entry point files
        if module in ('main', 'app', 'wsgi', 'asgi'):
            continue
            
        if module not in all_imports:
            # Check if the file has a main block
            has_main_block = False
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content:
                    has_main_block = True
            
            if not has_main_block:
                unused_files.append(file_path)
    
    return unused_files


def find_commented_code(directory="patri_reports"):
    """Find commented-out code blocks."""
    python_files = find_all_python_files(directory)
    commented_blocks = []
    
    # Pattern to detect multiple comment lines that might be commented-out code
    code_indicators = [
        r'def\s+\w+',  # function definition
        r'class\s+\w+', # class definition
        r'return\s+', # return statement
        r'if\s+.*:', # if statement
        r'for\s+.*:', # for loop
        r'while\s+.*:', # while loop
        r'import\s+', # import statement
        r'from\s+.*\s+import', # from import
    ]
    
    for file_path in python_files:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        comment_block = []
        in_comment_block = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Check if this is a comment line
            if stripped.startswith('#'):
                if not in_comment_block:
                    in_comment_block = True
                    comment_block = [(i+1, stripped)]
                else:
                    comment_block.append((i+1, stripped))
            else:
                # Not a comment - check if we were in a comment block
                if in_comment_block and len(comment_block) >= 3:  # Require at least 3 comment lines
                    # Check if the comment block might contain code
                    comment_content = '\n'.join(line for _, line in comment_block)
                    for pattern in code_indicators:
                        if re.search(pattern, comment_content):
                            start_line = comment_block[0][0]
                            end_line = comment_block[-1][0]
                            commented_blocks.append((file_path, start_line, end_line, comment_content))
                            break
                
                in_comment_block = False
                comment_block = []
        
        # Check for a comment block at the end of the file
        if in_comment_block and len(comment_block) >= 3:
            comment_content = '\n'.join(line for _, line in comment_block)
            for pattern in code_indicators:
                if re.search(pattern, comment_content):
                    start_line = comment_block[0][0]
                    end_line = comment_block[-1][0]
                    commented_blocks.append((file_path, start_line, end_line, comment_content))
                    break
    
    return commented_blocks


def main():
    """Find unused code in the project."""
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = "patri_reports"
    
    print(f"Analyzing code in directory: {directory}\n")
    
    # Find unused functions, classes, and methods
    print("Searching for unused functions, classes and methods...")
    unused_functions, unused_classes, unused_methods = find_unused_code(directory)
    
    if unused_functions:
        print(f"\n🔍 Found {len(unused_functions)} potentially unused functions:")
        for func_name, file_path in unused_functions:
            print(f"  - {func_name} in {file_path}")
    else:
        print("✓ No unused functions found.")
    
    if unused_classes:
        print(f"\n🔍 Found {len(unused_classes)} potentially unused classes:")
        for class_name, file_path in unused_classes:
            print(f"  - {class_name} in {file_path}")
    else:
        print("✓ No unused classes found.")
    
    if unused_methods:
        print(f"\n🔍 Found {len(unused_methods)} potentially unused methods:")
        for method_name, file_path in unused_methods:
            print(f"  - {method_name} in {file_path}")
    else:
        print("✓ No unused methods found.")
    
    # Find unused files
    print("\nSearching for potentially unused files...")
    unused_files = find_unused_files(directory)
    
    if unused_files:
        print(f"\n🔍 Found {len(unused_files)} potentially unused files:")
        for file_path in unused_files:
            print(f"  - {os.path.relpath(file_path, os.getcwd())}")
    else:
        print("✓ No unused files found.")
    
    # Find commented-out code
    print("\nSearching for commented-out code blocks...")
    commented_blocks = find_commented_code(directory)
    
    if commented_blocks:
        print(f"\n🔍 Found {len(commented_blocks)} blocks of commented-out code:")
        for file_path, start, end, _ in commented_blocks:
            print(f"  - {os.path.relpath(file_path, os.getcwd())} (lines {start}-{end})")
    else:
        print("✓ No commented-out code blocks found.")
    
    # Find duplicate code
    print("\nSearching for potential code duplication...")
    duplicates = find_duplicate_code(directory)
    
    if duplicates:
        print(f"\n🔍 Found {len(duplicates)} potential instances of duplicate code:")
        for f1, f2, ratio in duplicates:
            rel_path1 = os.path.relpath(f1['file'], os.getcwd())
            rel_path2 = os.path.relpath(f2['file'], os.getcwd())
            print(f"  - {f1['name']} in {rel_path1} and {f2['name']} in {rel_path2} ({ratio:.1%} similar)")
    else:
        print("✓ No duplicate code found.")
    
    # Summary
    total_issues = (len(unused_functions) + len(unused_classes) + len(unused_methods) +
                   len(unused_files) + len(commented_blocks) + len(duplicates))
    
    if total_issues > 0:
        print(f"\n⚠️ Found a total of {total_issues} code quality issues to review.")
        print("\nNext steps:")
        print("1. Review each issue to confirm it's actually unused code")
        print("2. Remove or refactor confirmed unused code")
        print("3. Update documentation to reflect changes")
        print("4. Run tests to ensure functionality is preserved")
    else:
        print("\n✅ No code quality issues found!")


if __name__ == "__main__":
    main() 