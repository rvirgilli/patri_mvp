import re

def escape_markdown(text: str) -> str:
    """
    Escape Markdown characters in text to make it safe for Telegram.
    
    Escapes characters that have special meaning in Markdown: 
    * _ ` [ ]
    
    Args:
        text: Text string to escape
        
    Returns:
        Text with Markdown characters properly escaped
    """
    if not text:
        return ""
        
    # Characters that need escaping in Telegram Markdown
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    
    # Create a pattern matching any of these characters
    pattern = f"([{re.escape(escape_chars)}])"
    
    # Replace each special character with a backslash followed by the character
    escaped_text = re.sub(pattern, r'\\\1', text)
    
    return escaped_text

def format_telegram_markdown(text: str) -> str:
    """
    Format text for Telegram by removing unsupported formatting and making it safe.
    
    For text coming from LLMs or other sources with potentially incompatible
    Markdown, this function removes or fixes formatting issues for Telegram.
    
    Args:
        text: Text to format for Telegram
        
    Returns:
        Markdown text safe for Telegram
    """
    if not text:
        return ""
    
    # First, prepare lines by stripping trailing whitespace that can cause issues
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    # Handle '#' header formatting (Telegram doesn't have header styles)
    # Replace Markdown headers with bold text
    processed_lines = []
    for line in text.split('\n'):
        # Convert headers to bold text
        if line.startswith('# '):
            line = f"*{line[2:]}*"
        elif line.startswith('## '):
            line = f"*{line[3:]}*"
        elif line.startswith('### '):
            line = f"*{line[4:]}*"
        elif line.startswith('#### '):
            line = f"*{line[5:]}*"
        # Make section titles bold
        elif ':' in line and not line.startswith(' ') and not line.startswith('-') and not line.startswith('*'):
            parts = line.split(':', 1)
            if len(parts) == 2 and parts[0] and not parts[0].startswith('http'):
                line = f"*{parts[0]}*:{parts[1]}"
                
        processed_lines.append(line)
    
    text = '\n'.join(processed_lines)
    
    # Handle tables (Telegram doesn't support tables)
    if '|' in text:
        lines = text.split('\n')
        new_lines = []
        for line in lines:
            if '|' in line:
                # Skip separator lines (---|---|---)
                if re.match(r'^[\s\-\|]+$', line):
                    continue
                # Remove pipes and format cells
                cells = [cell.strip() for cell in line.split('|')]
                cells = [cell for cell in cells if cell]  # Remove empty cells
                new_lines.append('  '.join(cells))
            else:
                new_lines.append(line)
        text = '\n'.join(new_lines)
    
    # Handle lists - make sure list items have a space after the marker
    lines = text.split('\n')
    for i in range(len(lines)):
        if re.match(r'^\s*[-*•]([^\s])', lines[i]):
            marker = re.match(r'^\s*([-*•])', lines[i]).group(1)
            lines[i] = lines[i].replace(marker, f"{marker} ", 1)
    text = '\n'.join(lines)
    
    # Simplify markup to avoid nesting issues that cause parse errors
    # Convert ** to * for bold
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    
    # Convert __ to _ for italic
    text = re.sub(r'__(.+?)__', r'_\1_', text)
    
    # Handle common problematic patterns
    # Fix nested formatting which Telegram doesn't handle well
    text = re.sub(r'\*([^*\n]+)_([^*\n]+)_([^*\n]+)\*', r'*\1\2\3*', text)
    text = re.sub(r'_([^_\n]+)\*([^_\n]+)\*([^_\n]+)_', r'_\1\2\3_', text)
    
    # Remove backticks as Telegram often has issues with them
    text = text.replace('```', '')
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Escape characters that could cause parsing problems
    # This is a more aggressive approach for reliability
    text = text.replace('*', '\\*')
    text = text.replace('_', '\\_')
    text = text.replace('[', '\\[')
    text = text.replace(']', '\\]')
    text = text.replace('(', '\\(')
    text = text.replace(')', '\\)')
    text = text.replace('~', '\\~')
    text = text.replace('`', '\\`')
    text = text.replace('>', '\\>')
    text = text.replace('#', '\\#')
    text = text.replace('+', '\\+')
    text = text.replace('-', '\\-')
    text = text.replace('=', '\\=')
    text = text.replace('|', '\\|')
    text = text.replace('{', '\\{')
    text = text.replace('}', '\\}')
    text = text.replace('.', '\\.')
    text = text.replace('!', '\\!')
    
    # Re-add basic formatting using Telegram's formatting
    # Make section headers bold
    lines = text.split('\n')
    for i in range(len(lines)):
        if lines[i].endswith('\\:') and not lines[i].startswith(' '):
            # This is likely a section header, make it bold
            title = lines[i][:-2]  # Remove \:
            lines[i] = f"*{title}*\\:"
    
    # Join lines back together
    text = '\n'.join(lines)
    
    return text 