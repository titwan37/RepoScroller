const fs = require('fs');

// We simulate what the browser does when parsing HTML into elements and reading .onclick
function testHtmlForOnclickSyntax(htmlSnippet) {
  // Extract all inline event handlers
  const regex = /on([a-z]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
  let match;
  while ((match = regex.exec(htmlSnippet)) !== null) {
    const eventName = match[1];
    let code = match[2] !== undefined ? match[2] : match[3];
    // In real browser, HTML entities like &#039; &quot; &amp; are decoded by HTML parser when attribute is set
    code = code.replace(/&#039;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
    try {
      new Function('event', code);
      console.log(`[PASS] ${eventName}="${code}"`);
    } catch (e) {
      console.error(`[FAIL] ${eventName}="${code}": ${e.message}`);
      process.exit(1);
    }
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const doc = {
  sha256_hash: 'ba0758e75f410c91816aec085e0b815638ebfd932f24df9e579b1ea8d2aeb18c',
  canonical_filename: "RO 2020 4085 - FR - Loi federale sur l'expropriation.pdf"
};

const primaryPath = "C:\\docs\\RO 2020 4085 - FR - Loi federale sur l'expropriation.pdf";

// Test row snippet from renderLedgerTable
const snippet1 = `
  <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem;" data-sha="${escapeHtml(doc.sha256_hash)}" onclick="selectDocument(this.getAttribute('data-sha'))">View</button>
  <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem; color: #38bdf8; border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.1);" data-sha="${escapeHtml(doc.sha256_hash)}" data-filename="${escapeHtml(doc.canonical_filename)}" onclick="event.stopPropagation(); visualizeDocumentIn3D(this.getAttribute('data-sha'), this.getAttribute('data-filename'))" title="Visualize document node and connected entity links in 3D Knowledge Universe">
    🌐 3D
  </button>
`;
console.log('Testing snippet 1 (ledger row):');
testHtmlForOnclickSyntax(snippet1);

// Test detail snippet
const snippet2 = `
  <button class="btn btn-secondary btn-block" style="..." data-sha="${escapeHtml(doc.sha256_hash)}" data-filename="${escapeHtml(doc.canonical_filename)}" onclick="visualizeDocumentIn3D(this.getAttribute('data-sha'), this.getAttribute('data-filename'))">
    <span>🌐</span> Visualize in 3D Knowledge Universe ➔
  </button>
`;
console.log('Testing snippet 2 (detail button):');
testHtmlForOnclickSyntax(snippet2);

// Test candidate snippet
const snippet3 = `
  <button class="btn btn-outline btn-xs" style="color: #38bdf8; border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.08);" data-sha="${escapeHtml(doc.sha256_hash)}" data-filename="${escapeHtml(doc.canonical_filename)}" onclick="visualizeDocumentIn3D(this.getAttribute('data-sha'), this.getAttribute('data-filename'))" title="Locate document vertex and visualize connected knowledge graph in 3D Universe">
    🌐 View in 3D
  </button>
  <button class="btn btn-outline btn-xs" data-sha="${escapeHtml(doc.sha256_hash)}" onclick="selectDocument(this.getAttribute('data-sha')); switchWorkspace('ledger');" title="Inspect full document in ledger">
    🗄️ Ledger
  </button>
  <button class="btn btn-primary btn-xs" data-sha="${escapeHtml(doc.sha256_hash)}" data-filename="${escapeHtml(doc.canonical_filename)}" onclick="interrogateAboutDocument(this.getAttribute('data-sha'), this.getAttribute('data-filename'))" title="Ask AI about this specific document">
    💬 Ask AI
  </button>
`;
console.log('Testing snippet 3 (candidates):');
testHtmlForOnclickSyntax(snippet3);

// Test inspector doc item
const snippet4 = `
  <div class="insp-doc-item"
       data-sha="${escapeHtml(doc.sha256_hash)}"
       data-filename="${escapeHtml(doc.canonical_filename)}"
       onclick="visualizeDocumentIn3D(this.getAttribute('data-sha'), this.getAttribute('data-filename'))"
       title="Visualize in 3D: ${escapeHtml(doc.canonical_filename)}">
    <span class="insp-doc-name">📄 ${escapeHtml(doc.canonical_filename)}</span>
  </div>
`;
console.log('Testing snippet 4 (inspector doc item):');
testHtmlForOnclickSyntax(snippet4);

console.log('ALL TESTS PASSED SUCCESSFULLY!');
