// Drive `showcase.html` with no window server in front of it.
//
// WHY A STUB AND NOT A REAL BROWSER. The same argument `home_sweep.js` makes and
// one more. `--showcase-probe` opens the real window and proves the surface draws
// -- it is the better instrument and it is the one that catches a rendering bug.
// What it CANNOT do is drive the page with forty hostile payloads in a second, or
// run at all on a machine with no display. This gate is the other half: every
// entry point, every kind, every malformed shape, and the properties that are
// about CORRECTNESS rather than pixels -- that a code pane numbers from its own
// first line, that a mark naming an absent pane is reported rather than drawn at
// the origin, that a scene arriving as a broken string does not take the page out.
//
// BOTH LAYERS ARE RUN, from the same file, the way `Showcase.swift` loads them.
// A defect in the marks layer is invisible to any instrument that only runs the
// base one, and the marks layer is where the arrows are.
//
// usage: node showcase_sweep.js <path to showcase.html> [--report]

'use strict';
const fs = require('fs');

const src = fs.readFileSync(process.argv[2], 'utf8');
const REPORT = process.argv.includes('--report');

const problems = [];
let drawn = 0;

function note(where, err) {
  problems.push(`${where}: ${err && err.message ? err.message : err}`);
}
function bad(msg) { problems.push(msg); }

// ---- the DOM stub ---------------------------------------------------------

function El(tag, ns) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    namespaceURI: ns || null,
    children: [], parentNode: null, attrs: {}, handlers: {},
    className: '', _text: '', id: '', value: '', src: '', alt: '',
    controls: false, autoplay: false, muted: false, currentTime: 0,
    scrollTop: 0, scrollHeight: 400, clientHeight: 300, clientWidth: 600,
    offsetTop: 0, width: 600, height: 300, dataset: {},
    style: new Proxy({
      setProperty(k, v) { this[k] = v; },
      removeProperty(k) { delete this[k]; },
      getPropertyValue(k) { return this[k] || ''; },
    }, { get: (t, k) => (k in t ? t[k] : ''), set: (t, k, v) => { t[k] = v; return true; } }),
  };
  el.classList = {
    add(...c) { c.forEach(x => { if (x && !el.className.split(' ').includes(x)) el.className = (el.className + ' ' + x).trim(); }); },
    remove(...c) { el.className = el.className.split(' ').filter(x => x && !c.includes(x)).join(' '); },
    contains(c) { return el.className.split(' ').includes(c); },
  };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text || el.children.map(c => c.textContent).join(''); },
    set(v) { el._text = v == null ? '' : String(v); el.children = []; },
  });
  Object.defineProperty(el, 'innerText', { get() { return el.textContent; } });
  Object.defineProperty(el, 'firstChild', { get() { return el.children[0] || null; } });
  el.appendChild = (c) => { if (c) { c.parentNode = el; el.children.push(c); drawn++; } return c; };
  el.removeChild = (c) => { el.children = el.children.filter(x => x !== c); if (c) c.parentNode = null; return c; };
  el.setAttribute = (k, v) => {
    el.attrs[k] = String(v);
    if (k === 'id') el.id = String(v);
    if (k.startsWith('data-')) el.dataset[k.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = String(v);
  };
  el.getAttribute = (k) => (k in el.attrs ? el.attrs[k] : null);
  el.addEventListener = (type, fn) => { (el.handlers[type] = el.handlers[type] || []).push(fn); };
  el.fire = (type, ev) => {
    (el.handlers[type] || []).forEach(fn => {
      try { fn.call(el, Object.assign({ target: el, offsetX: 10, offsetY: 20, preventDefault() {} }, ev || {})); }
      catch (e) { note(`a ${type} handler on <${el.tagName.toLowerCase()}>`, e); }
    });
  };
  // scrollIntoView RECORDED, NOT IGNORED. "the pane is scrolled to line 120" is
  // the ask; a stub that swallowed the call would let a regression that stops
  // scrolling pass every time.
  el.scrollIntoView = (opts) => { el._scrolled = opts || true; scrolls.push(el); };
  el.getBoundingClientRect = () => ({
    top: el._top || 0, left: el._left || 0, right: (el._left || 0) + 600,
    bottom: (el._top || 0) + 300, width: 600, height: 300,
  });
  el.getContext = (kind) => (kind === '2d' ? ctx2d() : null);
  el.querySelector = (sel) => descendants(el).find(n => matches(n, sel)) || null;
  el.querySelectorAll = (sel) => descendants(el).filter(n => matches(n, sel));
  return el;
}

function ctx2d() {
  const calls = [];
  const rec = (name) => (...a) => { calls.push([name, a]); };
  return {
    calls, lineWidth: 0, lineJoin: '', lineCap: '', strokeStyle: '',
    clearRect: rec('clearRect'), beginPath: rec('beginPath'),
    moveTo: rec('moveTo'), lineTo: rec('lineTo'), stroke: rec('stroke'),
  };
}

const scrolls = [];

function descendants(root) {
  const out = [];
  (function walk(n) { (n.children || []).forEach(c => { out.push(c); walk(c); }); })(root);
  return out;
}

function matches(node, sel) {
  if (!node || !sel) return false;
  return String(sel).split(',').some(one => {
    const part = one.trim().split(/\s+/).pop();
    return part.split(/(?=[.#[])/).every(bit => {
      if (!bit) return true;
      if (bit[0] === '.') return node.classList.contains(bit.slice(1));
      if (bit[0] === '#') return node.id === bit.slice(1);
      if (bit[0] === '[') {
        const m = bit.match(/^\[([^\]=]+)(?:=["']?([^"'\]]*)["']?)?\]$/);
        if (!m) return false;
        const v = node.getAttribute(m[1]);
        return m[2] === undefined ? v !== null : v === m[2];
      }
      return node.tagName === bit.toUpperCase();
    });
  });
}

// ---- one run of the page, in one layer ------------------------------------

function run(layer) {
  const root = El('body');
  const byId = {};
  // The markup the page ships with. Declared here rather than parsed, because
  // showcase.html's body is three elements and a parser would be the only thing
  // that could be wrong.
  ['why', 'grid'].forEach(id => { const e = El('div'); e.id = id; byId[id] = e; root.appendChild(e); });
  const svg = El('svg', 'http://www.w3.org/2000/svg'); svg.id = 'marks';
  byId.marks = svg; root.appendChild(svg);
  drawn = 0;
  scrolls.length = 0;

  const posted = [];
  const doc = {
    body: root,
    activeElement: null,
    createElement: (t) => El(t),
    createElementNS: (ns, t) => El(t, ns),
    createTextNode: (t) => Object.assign(El('#text'), { _text: String(t) }),
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => descendants(root).find(n => matches(n, sel)) || null,
    querySelectorAll: (sel) => descendants(root).filter(n => matches(n, sel)),
    addEventListener: (t, fn) => { if (t === 'DOMContentLoaded') doc._ready = fn; },
  };
  const win = {
    __vesperShowLayer: layer,
    webkit: { messageHandlers: { showcaseSaid: { postMessage: (b) => posted.push(b) } } },
    addEventListener: () => {},
    innerWidth: 1400, innerHeight: 900,
  };

  // The page's own script, evaluated the way the web view evaluates it.
  const blocks = [];
  const re = /<script[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(src)) !== null) blocks.push(m[1]);
  if (!blocks.length) { bad('showcase.html carries no script'); return null; }
  for (const body of blocks) {
    try {
      // eslint-disable-next-line no-new-func
      new Function('window', 'document', 'JSON', 'Math', 'Object', 'String', 'Number',
                   'parseFloat', 'isFinite', 'Array', 'Event', 'KeyboardEvent', body)
        .call(win, win, doc, JSON, Math, Object, String, Number, parseFloat, isFinite,
              Array, function Event() {}, function KeyboardEvent() {});
    } catch (e) { note(`the ${layer} layer's script`, e); }
  }
  if (typeof win.__vesperShow !== 'function') {
    bad(`the ${layer} layer defines no __vesperShow`);
    return null;
  }
  if (doc._ready) { try { doc._ready(); } catch (e) { note('DOMContentLoaded', e); } }
  return { win, doc, root, byId, posted };
}

// ---- the scenes -----------------------------------------------------------

const CODE = 'alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\ntheta';
const FULL = {
  revision: 7,
  why: 'the sweep',
  visible: true,
  desktop: 'vesper',
  panes: [
    { id: 'code', kind: 'code', title: 'a file', path: '/tmp/a b#c.py',
      body: CODE, first_line: 118, total_lines: 900, focus: { line: 120 } },
    { id: 'pic', kind: 'image', path: '/tmp/a picture.png' },
    { id: 'vid', kind: 'video', path: '/tmp/clip.mp4', focus: { at_s: 42 } },
    { id: 'site', kind: 'web', url: 'https://example.com', span: 2 },
    { id: 'board', kind: 'board', title: 'whiteboard', strokes: [[[0.1, 0.1], [0.4, 0.5]]] },
    { id: 'note', kind: 'text', text: 'one two three four', focus: { find: 'three' } },
    { id: 'run', kind: 'run', path: '/tmp/run.log', body: 'line a\nline b' },
  ],
  marks: [
    { kind: 'arrow', pane: 'code', from: [0.05, 0.1], anchor: { pane: 'code', line: 120 } },
    { kind: 'ring', pane: 'pic', at: [0.5, 0.5] },
    { kind: 'ink', pane: 'board', points: [[0.1, 0.1], [0.2, 0.3], [0.4, 0.2]] },
    { kind: 'label', pane: 'note', at: [0.2, 0.2], text: 'here' },
    { kind: 'arrow', pane: 'gone', at: [0.5, 0.5] },
  ],
  cursor: { pane: 'site', x: 0.3, y: 0.7, gesture: 'tap', visible: true },
  rects: {
    code: { x: 0, y: 0, w: 400, h: 300 }, pic: { x: 400, y: 0, w: 400, h: 300 },
    board: { x: 0, y: 300, w: 400, h: 300 }, note: { x: 400, y: 300, w: 400, h: 300 },
    site: { x: 0, y: 600, w: 800, h: 300 },
  },
};

const HOSTILE = [
  null, undefined, 'not json at all', '{"broken":', '[]]', '{}', '[]', 42,
  { panes: null, marks: null },
  { panes: 'not a list' },
  { panes: [{ kind: 'code' }] },                       // no id
  { panes: [{ id: 'x', kind: 'zzz-unknown' }] },
  { panes: [{ id: 'x', kind: 'code', body: null, first_line: 'NaN' }] },
  { panes: [{ id: 'x', kind: 'image', path: null }] },
  { panes: [{ id: 'x', kind: 'text', text: 'x'.repeat(50000) }] },
  { panes: [{ id: 'x', kind: 'board' }], marks: [{ kind: 'ink', pane: 'x' }] },
  { panes: [{ id: 'x', kind: 'text', text: 'y' }],
    marks: [{ kind: 'arrow', pane: 'x', at: ['NaN', null] },
            { kind: 'zzz', pane: 'x', at: [0.1, 0.1] },
            { kind: 'label', pane: 'x', at: [0.1, 0.1] }],
    rects: { x: { x: 0, y: 0, w: 10, h: 10 } },
    cursor: { pane: 'nope', x: 5, y: -2 } },
  { panes: Array.from({ length: 40 }, (_, i) => ({ id: 'p' + i, kind: 'text', text: String(i) })) },
];

// ---- base layer -----------------------------------------------------------

const base = run('base');
let basePanes = [];
if (base) {
  let out;
  try { out = JSON.parse(base.win.__vesperShow(JSON.stringify(FULL))); }
  catch (e) { note('the base layer on a full scene', e); out = {}; }
  basePanes = out.panes || [];

  const want = ['code', 'pic', 'vid', 'site', 'board', 'note', 'run'];
  const missing = want.filter(id => !basePanes.includes(id));
  if (missing.length) bad(`the base layer did not draw: ${missing.join(', ')}`);
  if (out.revision !== 7) bad(`the base layer reported revision ${out.revision}, not 7`);
  for (const id of want) {
    if (!out.rects || !out.rects[id]) bad(`no rect came back for pane ${id}, so nothing can point at it`);
  }
  if ((out.errors || []).length) bad(`the base layer erred on a valid scene: ${out.errors.join(' | ')}`);

  // A CODE PANE NUMBERS FROM ITS OWN FIRST LINE. The whole "at a specific
  // location" claim rests on this one property: a pane that renumbered from 1
  // would highlight the right pixel and the wrong line.
  const codePane = base.doc.querySelector('[data-pane=code]');
  const rows = codePane ? codePane.querySelectorAll('.ln') : [];
  if (rows.length !== 8) bad(`the code pane drew ${rows.length} lines, not 8`);
  const numbers = rows.map(r => (r.children[0] || {}).textContent);
  if (numbers[0] !== '118') bad(`the code pane numbered from ${numbers[0]}, not from its first_line 118`);
  if (numbers[numbers.length - 1] !== '125') bad(`the code pane's last line is ${numbers[numbers.length - 1]}, not 125`);
  const on = rows.filter(r => r.classList.contains('on'));
  if (on.length !== 1) bad(`${on.length} lines are highlighted, not exactly the focused one`);
  else if ((on[0].children[0] || {}).textContent !== '120') bad('the wrong line is highlighted');
  // THE HIGHLIGHTED ROW ITSELF, NOT "SOMETHING SCROLLED".
  //
  // THIS ASSERTION WAS VACUOUS AND ITS OWN RED RUN CAUGHT IT. It read
  // `scrolls.length`, which the TEXT pane also fills when it scrolls to the
  // string it marked -- so removing the code pane's scroll entirely left the
  // gate green. `checks-can-be-alive-and-useless`, on the first day of a new
  // instrument.
  else if (!on[0]._scrolled) {
    bad('the focused code line was not scrolled into view: a pane showing line 1 of 900 has answered a different question');
  }
  if (!scrolls.length) bad('nothing was scrolled into view at all');

  // A LOCAL PATH IS ENCODED PER SEGMENT. `/tmp/a b#c.py` is the case that
  // truncates a naive URL at the hash and breaks at the space.
  const img = base.doc.querySelector('img');
  if (!img || !/^vesper-file:\/\//.test(img.src)) bad('an image pane did not use the vesper-file scheme');
  else if (img.src.indexOf(' ') >= 0 || img.src.indexOf('#') >= 0) {
    bad(`an image URL carries a raw space or hash: ${img.src}`);
  }

  // A VIDEO SEEKS TO THE MOMENT IT WAS ASKED FOR.
  const vid = base.doc.querySelector('video');
  if (!vid) bad('the video pane drew no video');
  else {
    vid.fire('loadedmetadata');
    if (vid.currentTime !== 42) bad(`the video sat at ${vid.currentTime}s instead of seeking to 42s`);
  }

  // THE TEXT PANE MARKS WHAT IT WAS ASKED TO FIND.
  const found = base.doc.querySelector('mark');
  if (!found || found.textContent !== 'three') bad('the text pane did not mark the string it was focused on');

  // THE WHITEBOARD TAKES THE OWNER'S HAND AND TELLS VESPER.
  const canvas = base.doc.querySelector('canvas');
  if (!canvas) bad('the board pane drew no canvas');
  else {
    canvas.fire('mousedown'); canvas.fire('mousemove'); canvas.fire('mouseup');
    const sent = base.posted.filter(p => p && p.board);
    if (!sent.length) bad('drawing on the whiteboard told the host nothing');
    else if (sent[sent.length - 1].board.length < 2) bad('the stroke the owner drew was not kept beside the one vesper drew');
  }
}

// ---- marks layer ----------------------------------------------------------

const marks = run('marks');
if (marks) {
  let out;
  try { out = JSON.parse(marks.win.__vesperShow(JSON.stringify(FULL))); }
  catch (e) { note('the marks layer on a full scene', e); out = {}; }
  // Four drawable marks plus the cursor. The fifth mark names a pane that is
  // not in `rects` and must be REPORTED rather than drawn at the origin.
  if (out.marks !== 5) bad(`the marks layer drew ${out.marks} marks, not the 4 placeable ones plus the cursor`);
  const named = (out.errors || []).some(e => /points at a pane that did not draw/.test(e));
  if (!named) bad('a mark pointing at an absent pane was not reported');
  const svg = marks.byId.marks;
  const kinds = svg.children.map(c => c.tagName.toLowerCase());
  for (const t of ['line', 'circle', 'polyline', 'text', 'g']) {
    if (!kinds.includes(t)) bad(`the marks layer drew no <${t}>: ${kinds.join(',')}`);
  }
  // THE ANCHOR RESOLVES TO THE LINE, NOT TO THE MIDDLE OF THE PANE. Line 120 of
  // a slice starting at 118 with 8 lines is (120-118+0.5)/8 = 0.3125 down.
  const line = svg.children.find(c => c.tagName.toLowerCase() === 'line');
  const y2 = line ? parseFloat(line.getAttribute('y2')) : NaN;
  if (!(Math.abs(y2 - 300 * 0.3125) < 1)) {
    bad(`an anchored arrow ended at y=${y2}, not at the line it names (${300 * 0.3125})`);
  }
  // A SECOND PUSH REPLACES, NEVER ACCUMULATES. Otherwise a demonstration's
  // arrows pile up and the surface is unreadable by step four.
  marks.win.__vesperShow(JSON.stringify({ ...FULL, revision: 8, marks: [], cursor: null }));
  if (svg.children.filter(c => c.tagName.toLowerCase() !== 'defs').length !== 0) {
    bad('a scene with no marks left the previous scene\'s marks on the glass');
  }
}

// ---- and then everything malformed ----------------------------------------

let survived = 0;
for (const layer of ['base', 'marks']) {
  const page = run(layer);
  if (!page) continue;
  for (const payload of HOSTILE) {
    let answer;
    try {
      answer = page.win.__vesperShow(typeof payload === 'string' ? payload : JSON.stringify(payload));
    } catch (e) {
      bad(`the ${layer} layer threw on ${JSON.stringify(payload).slice(0, 60)}: ${e.message}`);
      continue;
    }
    try {
      const got = JSON.parse(answer);
      if (typeof got !== 'object' || got === null) bad(`the ${layer} layer answered ${answer}`);
      if (got.layer !== layer) bad(`the ${layer} layer answered for layer ${got.layer}`);
      survived++;
    } catch (e) {
      bad(`the ${layer} layer answered something that is not json: ${String(answer).slice(0, 60)}`);
    }
  }
}

// ---- verdict --------------------------------------------------------------

console.log(`panes_drawn=${basePanes.join(',')}`);
console.log(`nodes_drawn=${drawn} hostile_payloads_survived=${survived}`);
if (REPORT && base) {
  console.log('\npanes the base layer drew:');
  for (const id of basePanes) console.log(`  ${id}`);
}
if (problems.length) {
  console.log(`\n${problems.length} problem(s):`);
  problems.forEach(p => console.log(`  - ${p}`));
  process.exit(1);
}
console.log('the showcase page drew every kind, pointed at the right line, and survived every malformed scene');
