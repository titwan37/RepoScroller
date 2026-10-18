const fs = require('fs');
const html = fs.readFileSync('frontend/index.html', 'utf8');

// match all <button ...>
const btnRegex = /<button\b([^>]*)>/gi;
let m;
while ((m = btnRegex.exec(html)) !== null) {
  const attrs = m[1];
  const onclickMatch = attrs.match(/onclick\s*=\s*(?:"([^"]*)"|'([^']*)')/i);
  if (onclickMatch) {
    const code = onclickMatch[1] || onclickMatch[2];
    try {
      new Function('event', code);
    } catch(err) {
      console.log('Error in static button:', m[0], err.message);
    }
  }
}
console.log('Static button check complete.');
