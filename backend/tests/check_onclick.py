import re
import glob

def check_file(filepath):
    print(f"--- Checking {filepath} ---")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all inline event handlers: onclick="..." or onclick='...'
    pattern = re.compile(r'\bon[a-z]+\s*=\s*("([^"]*)"|\'([^\']*)\')', re.IGNORECASE)
    for m in pattern.finditer(content):
        attr_full = m.group(0)
        code = m.group(2) if m.group(2) is not None else m.group(3)
        # Check parenthesis
        open_p = code.count('(')
        close_p = code.count(')')
        if open_p != close_p:
            line_no = content[:m.start()].count('\n') + 1
            print(f"Line {line_no}: Parens mismatch ({open_p} vs {close_p}): {attr_full}")
        
        # Check for single/double quotes balance within code
        # In onclick="foo('bar)", single quote might be unclosed
        s_quotes = code.count("'")
        if s_quotes % 2 != 0:
            line_no = content[:m.start()].count('\n') + 1
            print(f"Line {line_no}: Unbalanced single quotes: {attr_full}")

check_file('frontend/index.html')

for js_file in glob.glob('frontend/**/*.js', recursive=True):
    with open(js_file, 'r', encoding='utf-8') as f:
        c = f.read()
    # Check template literals containing onclick
    matches = re.finditer(r'onclick=\\?["\']([^"\'>\\]*(\\.[^"\'>\\]*)*)\\?["\']', c)
    for m in matches:
        code = m.group(1)
        if code.count('(') != code.count(')'):
            line_no = c[:m.start()].count('\n') + 1
            print(f"{js_file}:{line_no}: Parens mismatch in JS string: {m.group(0)[:100]}")

print("Done scanning.")
