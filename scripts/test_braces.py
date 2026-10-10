with open('../frontend/style.css', 'r', encoding='utf-8') as f:
    text = f.read()

# Strip comments and strings
import re
cleaned = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
open_b = cleaned.count('{')
close_b = cleaned.count('}')
print(f'Open braces: {open_b}, Close braces: {close_b}')
assert open_b == close_b, 'Mismatched braces!'
print('CSS brace validation passed successfully!')