const fs = require('fs');

const html = fs.readFileSync('frontend/index.html', 'utf8');

// Regex to extract all onclick attributes in html
const regex = /onclick\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
let match;
let count = 0;
let errors = 0;

while ((match = regex.exec(html)) !== null) {
  count++;
  const code = match[1] !== undefined ? match[1] : match[2];
  try {
    new Function('event', code);
  } catch (e) {
    errors++;
    console.error(`ERROR in index.html match ${count}:`, e.message);
    console.error('Code was:', code);
    // find line number
    const line = html.substring(0, match.index).split('\n').length;
    console.error('Line:', line);
  }
}

console.log(`Checked ${count} onclick handlers in index.html, errors: ${errors}`);

// Also check app.js for generated onclick attributes!
const appJs = fs.readFileSync('frontend/app.js', 'utf8');
// Find occurrences of onclick="..." or onclick=\\"...\\" in app.js
const jsRegex = /onclick\s*=\s*(?:\\?"([^"\\]*(?:\\.[^"\\]*)*)\\?"|'([^'\\]*(?:\\.[^'\\]*)*)')/gi;
let jsMatch;
let jsCount = 0;
let jsErrors = 0;

while ((jsMatch = jsRegex.exec(appJs)) !== null) {
  jsCount++;
  const rawCode = jsMatch[1] !== undefined ? jsMatch[1] : jsMatch[2];
  // Replace template interpolations like ${...} with dummy identifier 'val'
  const sanitized = rawCode.replace(/\$\{([^}]+)\}/g, 'val');
  try {
    new Function('event', sanitized);
  } catch (e) {
    jsErrors++;
    const line = appJs.substring(0, jsMatch.index).split('\n').length;
    console.error(`ERROR in app.js around line ${line}:`, e.message);
    console.error('Raw code:', rawCode);
    console.error('Sanitized code:', sanitized);
  }
}
console.log(`Checked ${jsCount} onclick handlers in app.js, errors: ${jsErrors}`);
