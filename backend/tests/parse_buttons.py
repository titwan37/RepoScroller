from bs4 import BeautifulSoup
import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')

buttons = soup.find_all('button')
print(f"Total buttons: {len(buttons)}")

for i, btn in enumerate(buttons):
    onclick = btn.get('onclick')
    if onclick:
        # Check if there's any obvious issue
        lines = str(btn).split('\n')
        # Let's test with node if node is available, or check syntax
        print(f"Button {i}: id={btn.get('id')} class={btn.get('class')}")
        print(f"  onclick={repr(onclick)}")

# Also check other elements with onclick: a, div, span, etc.
all_onclick = soup.find_all(attrs={"onclick": True})
print(f"\nTotal elements with onclick: {len(all_onclick)}")
for el in all_onclick:
    if el.name != 'button':
        print(f"El {el.name} id={el.get('id')} onclick={repr(el.get('onclick'))}")
