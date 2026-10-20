// DOM-level checks without browser dependencies. Run: node tests/test_quotes_view.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor() { this.children = []; this.style = {}; this.classList = {add() {}, remove() {}, toggle() {}}; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text || ''; }
  get childElementCount() { return this.children.length; }
  appendChild(child) { this.children.push(child); }
  addEventListener() {}
}
const nodes = new Map();
const parent = {postMessage() {}};
const document = {
  body: new Element(), documentElement: new Element(),
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); },
  createElement() { return new Element(); },
};
let onMessage;
const window = {parent, addEventListener(name, fn) { if (name === 'message') onMessage = fn; }};
const html = fs.readFileSync(path.join(__dirname, '../mcpcalibre/ui/gallery.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInNewContext(script, {window, document, ResizeObserver: class {observe() {}}, Set, Map, Promise});
const text = '<script>alert("untrusted")</script>\nExact spacing  preserved.';
const send = (params, source = parent) => onMessage({source, data: {
  jsonrpc: '2.0', method: 'ui/notifications/tool-result', params,
}});
send({_meta: {calibreQuotes: {title: 'Quotes', passages: [{
  book_id: 7, format: 'EPUB', offset: 12, end_offset: 72,
  label: '<b>Title</b>', authors: ['Author'], text,
}]}}});
const grid = document.getElementById('grid');
assert.equal(grid.childElementCount, 1);
assert.equal(grid.children[0].children[0].textContent, text);
assert.equal(grid.children[0].children[1].children[0].textContent, '<b>Title</b>');
assert.match(grid.children[0].children[1].children[2].textContent, /\[12, 72\)/);
send({_meta: {calibreQuotes: {passages: []}}}, {});
assert.equal(grid.childElementCount, 1, 'ignore messages from other frames');
send({_meta: {calibreQuotes: {passages: []}}});
assert.equal(grid.childElementCount, 0);
assert.equal(document.getElementById('msg').textContent, 'No quotations to display.');
send({structuredContent: {images: [], errors: []}});
assert.equal(grid.childElementCount, 0, 'existing image view still accepts results');
assert.equal(document.getElementById('title').hidden, true, 'image view clears quotation title');
send({structuredContent: {count: 1, references: [{book_id: 7}]}});
assert.match(document.getElementById('msg').textContent, /did not forward quotation view metadata/);
assert.equal(document.getElementById('msg').hidden, false, 'missing metadata message remains visible after image view');
console.log('PASS quotes: metadata routing, exact text, attribution, frame isolation, empty view, image routing, missing metadata');
