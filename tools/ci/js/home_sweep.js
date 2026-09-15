// THE WHOLE HOME PAGE, DRIVEN. Owner, 2026-09-15: "go sweep the whole frontend,
// and fix all bugs, do not ruin anything".
//
// Reading a 3 000-line page for defects finds the ones a reader can see. This
// runs it: every script block is evaluated against a DOM stub, every entry point
// the Swift host calls is handed the payload it really sends (taken live from
// the producers), and then EVERY BUTTON THE PAGE DREW IS CLICKED. A renderer
// that throws, a handler that dies on a missing field, a control that reaches no
// message handler -- each is a defect the owner would see as "it does nothing"
// and none of them is visible in the source.
//
// usage: node home_sweep.js <home.html> <payloads.json>
'use strict';
const fs = require('fs');

const src = fs.readFileSync(process.argv[2], 'utf8');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const problems = [];
const posted = [];          // every message the page sent to the host
let clicks = 0, drawn = 0;

function note(where, err) {
  const msg = (err && err.stack ? String(err.stack).split('\n').slice(0, 3).join(' | ')
                                : String(err));
  problems.push(`${where}: ${msg}`);
}

// ---- the DOM stub ---------------------------------------------------------
function El(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    children: [], parentNode: null, attrs: {}, handlers: {},
    className: '', _text: '', hidden: false, id: '', type: '', value: '',
    checked: false, disabled: false, title: '', tabIndex: 0, min: '', max: '',
    step: '', href: '', scrollTop: 0, scrollHeight: 100, offsetWidth: 200,
    dataset: {},
    style: new Proxy({
      cssText: '',
      setProperty(k, v) { this[k] = v; },
      removeProperty(k) { delete this[k]; },
      getPropertyValue(k) { return this[k] || ''; },
    }, { get: (t, k) => (k in t ? t[k] : ''), set: (t, k, v) => { t[k] = v; return true; } }),
    // <dialog>: the menu panel is one, and the page opens and closes it.
    open: false,
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
  el.classList = {
    add(...c) { c.forEach(x => { if (x && !el.className.split(' ').includes(x)) el.className = (el.className + ' ' + x).trim(); }); },
    remove(...c) { el.className = el.className.split(' ').filter(x => x && !c.includes(x)).join(' '); },
    toggle(c, on) { const has = el.classList.contains(c); const want = on === undefined ? !has : !!on; if (want) el.classList.add(c); else el.classList.remove(c); return want; },
    contains(c) { return el.className.split(' ').includes(c); },
  };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text || el.children.map(c => c.textContent).join(''); },
    set(v) { el._text = v == null ? '' : String(v); el.children = []; },
  });
  // innerHTML IS PARSED, NOT STORED. The history renderer builds its rows as
  // markup and then walks `querySelectorAll('.htext')` to set the text safely;
  // a stub that only remembered the string would find no cells and report the
  // page as broken -- an instrument failing and blaming the thing it measures.
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html || ''; },
    set(v) {
      el._html = String(v == null ? '' : v);
      el.children = [];
      if (el._html) parseInto(el, el._html);
    },
  });
  Object.defineProperty(el, 'firstChild', { get() { return el.children[0] || null; } });
  Object.defineProperty(el, 'lastChild', { get() { return el.children[el.children.length - 1] || null; } });
  Object.defineProperty(el, 'childNodes', { get() { return el.children; } });
  el.appendChild = (c) => { if (c) { c.parentNode = el; el.children.push(c); drawn++; } return c; };
  el.append = (...cs) => { cs.forEach(c => { if (c && typeof c === 'object') el.appendChild(c); else if (c != null) el.appendChild(Object.assign(El('span'), { _text: String(c) })); }); };
  el.prepend = (c) => { if (c) { c.parentNode = el; el.children.unshift(c); } return c; };
  el.insertBefore = (c, ref) => { const i = el.children.indexOf(ref); if (c) { c.parentNode = el; el.children.splice(i < 0 ? el.children.length : i, 0, c); } return c; };
  el.removeChild = (c) => { el.children = el.children.filter(x => x !== c); if (c) c.parentNode = null; return c; };
  el.replaceChild = (n, o) => { const i = el.children.indexOf(o); if (i >= 0) el.children[i] = n; if (n) n.parentNode = el; return o; };
  el.remove = () => { if (el.parentNode) el.parentNode.removeChild(el); };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); if (k === 'id') el.id = String(v); if (k.startsWith('data-')) el.dataset[k.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = String(v); };
  el.getAttribute = (k) => (k in el.attrs ? el.attrs[k] : null);
  el.hasAttribute = (k) => k in el.attrs;
  el.removeAttribute = (k) => { delete el.attrs[k]; };
  el.addEventListener = (type, fn) => { (el.handlers[type] = el.handlers[type] || []).push(fn); };
  el.removeEventListener = (type, fn) => { el.handlers[type] = (el.handlers[type] || []).filter(f => f !== fn); };
  el.fire = (type, ev) => {
    (el.handlers[type] || []).forEach(fn => {
      try { fn.call(el, Object.assign({ target: el, currentTarget: el, preventDefault() {}, stopPropagation() {}, key: '', keyCode: 0 }, ev || {})); }
      catch (e) { note(`a ${type} handler on <${el.tagName.toLowerCase()} class="${el.className}">`, e); }
    });
  };
  el.click = () => { clicks++; el.fire('click'); };
  el.focus = () => {};
  el.blur = () => {};
  el.scrollIntoView = () => {};
  el.getBoundingClientRect = () => ({ top: 0, left: 0, right: 200, bottom: 40, width: 200, height: 40 });
  el.closest = (sel) => { let n = el; while (n) { if (matches(n, sel)) return n; n = n.parentNode; } return null; };
  el.matches = (sel) => matches(el, sel);
  el.querySelector = (sel) => descendants(el).find(n => matches(n, sel)) || null;
  el.querySelectorAll = (sel) => descendants(el).filter(n => matches(n, sel));
  return el;
}

function descendants(root) {
  const out = [];
  (function walk(n) { (n.children || []).forEach(c => { out.push(c); walk(c); }); })(root);
  return out;
}

// Enough selector for what the page uses: tag, .class, #id, [attr], and
// comma-separated lists. Descendant combinators are matched on the last part,
// which over-matches rather than under-matches -- a sweep must not miss nodes.
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

const byId = {};
const root = El('body');
function getById(id) {
  if (!byId[id]) { const e = El('div'); e.id = id; byId[id] = e; root.appendChild(e); }
  return byId[id];
}

// ---- the page's own markup, so the script finds what it looks for ----------
//
// WITHOUT THIS THE SWEEP PROVES NOTHING. The menu script begins by collecting
// `document.querySelectorAll('[data-menu-view]')` and reading `.menu-back` out
// of the panel; against an empty document those are empty and every later
// assertion is about a page that drew nothing. Only the body is parsed -- style
// and script are skipped -- and it is deliberately a small parser: the page is
// hand-written HTML with no exotic constructs, and a real parser would be a
// dependency this repo does not take.
function parseBody(html) {
  const bodyAt = html.indexOf('<body');
  let text = bodyAt < 0 ? html : html.slice(html.indexOf('>', bodyAt) + 1);
  text = text.replace(/<!--[\s\S]*?-->/g, '')
             .replace(/<style[\s\S]*?<\/style>/gi, '')
             .replace(/<script[\s\S]*?<\/script>/gi, '');
  parseInto(root, text);
  drawn = 0;                       // markup is not something the page drew
}

function parseInto(container, text) {
  const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link', 'path', 'circle',
                        'rect', 'line', 'polyline', 'polygon', 'ellipse', 'use', 'stop']);
  const stack = [container];
  const token = /<\/?([a-zA-Z][\w:-]*)((?:[^<>"']|"[^"]*"|'[^']*')*)>|([^<]+)/g;
  let m;
  while ((m = token.exec(text)) !== null) {
    const [whole, tag, rawAttrs, chunk] = m;
    const top = stack[stack.length - 1];
    if (chunk !== undefined) {
      const t = chunk.replace(/\s+/g, ' ').trim();
      if (t) top._text = (top._text || '') + t;
      continue;
    }
    if (whole[1] === '/') { if (stack.length > 1) stack.pop(); continue; }
    const el = El(tag);
    const attr = /([\w:-]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|[^\s>]+))?/g;
    let a;
    while ((a = attr.exec(rawAttrs || '')) !== null) {
      const name = a[1], value = a[3] !== undefined ? a[3] : (a[4] !== undefined ? a[4] : (a[2] || ''));
      if (name === 'class') el.className = value;
      else if (name === 'id') { el.id = value; byId[value] = el; }
      else if (name === 'hidden') el.hidden = true;
      else if (name === 'value') el.value = value;
      else if (name === 'type') el.type = value;
      else if (name === 'title') el.title = value;
      el.setAttribute(name, value);
    }
    top.appendChild(el);
    if (!VOID.has(tag.toLowerCase()) && !/\/$/.test(rawAttrs || '')) stack.push(el);
  }
}

const timers = [];
global.window = {
  innerWidth: 1440, innerHeight: 900,
  webkit: { messageHandlers: new Proxy({}, { get: (_, name) => ({ postMessage: (m) => posted.push({ name: String(name), message: m }) }) }) },
  getComputedStyle: () => new Proxy({}, { get: () => '' }),
  addEventListener() {}, removeEventListener() {},
  localStorage: { _v: {}, getItem(k) { return this._v[k] === undefined ? null : this._v[k]; }, setItem(k, v) { this._v[k] = String(v); }, removeItem(k) { delete this._v[k]; } },
  setTimeout: (fn, ms) => { timers.push(fn); return timers.length; },
  clearTimeout() {}, setInterval: () => 1, clearInterval() {},
};
global.localStorage = window.localStorage;
global.setTimeout = window.setTimeout;
global.clearTimeout = window.clearTimeout;
global.setInterval = window.setInterval;
global.clearInterval = window.clearInterval;
global.getComputedStyle = window.getComputedStyle;
global.document = {
  body: root, documentElement: El('html'), hidden: false, activeElement: null,
  getElementById: getById,
  createElement: El,
  createTextNode: (t) => Object.assign(El('span'), { _text: String(t) }),
  addEventListener(type, fn) { (this._h = this._h || {})[type] = (this._h[type] || []).concat(fn); },
  removeEventListener() {},
  querySelector: (sel) => descendants(root).find(n => matches(n, sel)) || null,
  querySelectorAll: (sel) => descendants(root).filter(n => matches(n, sel)),
};

// ---- the page's own script ------------------------------------------------
const blocks = [];
let at = 0;
for (;;) {
  const open = src.indexOf('<script>', at);
  if (open < 0) break;
  const close = src.indexOf('</script>', open);
  blocks.push(src.slice(open + 8, close));
  at = close + 9;
}
if (!blocks.length) { console.log('FAILURES:\n  the page has no script at all'); process.exit(1); }
parseBody(src);
blocks.forEach((b, i) => {
  try { (0, eval)(b); } catch (e) { note(`script block ${i + 1} would not even load`, e); }
});
// THE PAGE'S WHOLE MENU LIVES INSIDE A `DOMContentLoaded` HANDLER, so a sweep
// that never fires it is a sweep of three helper functions.
((document._h && document._h.DOMContentLoaded) || []).forEach(fn => {
  try { fn({ type: 'DOMContentLoaded' }); } catch (e) { note('the page setting itself up on DOMContentLoaded', e); }
});

// ---- every entry point, with what the host really sends --------------------
const calls = [
  ['__vesperCards', [JSON.stringify(data.cards || [])]],
  ['__vesperSettings', [JSON.stringify(data.settings || [])]],
  ['__vesperRail', ['research', JSON.stringify(data.research || [])]],
  ['__vesperRail', ['projects', JSON.stringify(data.projects || [])]],
  ['__vesperRail', ['boards', JSON.stringify(data.boards || {})]],
  ['__vesperRail', ['dashboard', JSON.stringify(data.dashboard || {})]],
  ['__vesperMetrics', [JSON.stringify(data.metrics || [])]],
  ['__vesperHistory', [JSON.stringify(data.history || [])]],
  ['__vesperWork', [JSON.stringify(data.work || {})]],
  ['__vesperFlags', [JSON.stringify(data.flags || [])]],
  ['__vesperFlagHistory', [JSON.stringify(data.flagHistory || [])]],
  ['__vesperChanges', [JSON.stringify(data.changes || {})]],
  ['__vesperStage', [String(data.stage || 'a sentence VESPER said'), 'vesper']],
  ['__vesperTermOut', [String(data.term || 'ready\n')]],
  ['__vesperActResult', [JSON.stringify(data.actResult || {})]],
];
for (const [name, args] of calls) {
  const fn = window[name];
  if (typeof fn !== 'function') { problems.push(`the page defines no ${name}, which the host calls`); continue; }
  try { fn.apply(window, args); } catch (e) { note(`${name} with the host's own payload`, e); }
}

// AND WHAT A HOST CAN ACTUALLY SEND. Every payload crosses as a template
// literal built in Swift: a truncated write, a stray backtick in a window title
// or a model's own output arrives here as text this page must survive. A
// renderer that throws on it takes the whole surface down with it.
const nasty = ['not json at all', '{"broken":', '[]]', '{"rows":null}',
               JSON.stringify([{ text: '</script><img src=x onerror=1>' }]),
               JSON.stringify([{ text: 'x'.repeat(200000) }]),
               JSON.stringify([{ text: '\u0000\u2028\u202e ok' }]),
               JSON.stringify({ rows: [{}], panels: [{}], cards: [{}] })];
for (const [name, args] of calls) {
  const fn = window[name];
  if (typeof fn !== 'function') continue;
  for (const bad of nasty) {
    try { fn.apply(window, args.map((a, i) => (i === args.length - 1 ? bad : a))); }
    catch (e) { note(`${name} handed ${JSON.stringify(bad).slice(0, 40)}`, e); }
  }
}

// AND THE EMPTY CASE, which is what a fresh machine sends before anything has
// happened. A renderer that only works with data is a renderer that breaks on
// first light.
for (const [name, args] of calls) {
  const fn = window[name];
  if (typeof fn !== 'function') continue;
  const empty = args.map(a => (a && a[0] === '[' ? '[]' : a && a[0] === '{' ? '{}' : ''));
  try { fn.apply(window, empty); } catch (e) { note(`${name} with nothing to show`, e); }
  try { fn.apply(window, args.map(() => undefined)); } catch (e) { note(`${name} called with no argument at all`, e); }
}

// ---- and then every button on the page ------------------------------------
for (const [name, args] of calls) {
  const fn = window[name];
  if (typeof fn === 'function') { try { fn.apply(window, args); } catch (e) { /* reported above */ } }
}
// EVERY DESTINATION, OPENED, AND THEN EVERYTHING INSIDE IT PRESSED. The rail
// and the tile draw their content only when clicked, so a sweep that collects
// buttons once and clicks them has swept the resting page and nothing else --
// which is precisely where the owner's "it shows and does nothing" lives.
const content = byId['menu-content'];
const views = descendants(root).filter(n => n.getAttribute('data-menu-view'));
const empty = [];
const report = [];
views.forEach(t => {
  const view = t.getAttribute('data-menu-view');
  try { t.click(); } catch (e) { note(`opening ${view}`, e); }
  const inside = content ? descendants(content) : [];
  const text = inside.map(n => n._text || '').join(' ').trim();
  if (!inside.length || !text) empty.push(view);
  if (/^\s*UNAVAILABLE\s*$/i.test(text)) empty.push(view + ' (UNAVAILABLE and nothing else)');
  // WHAT THE OWNER WOULD READ ON THAT SCREEN, so a sweep can be looked at as
  // well as passed. A destination that renders without throwing and says
  // nothing useful is the defect this whole surface was rebuilt to remove.
  report.push({
    view,
    nodes: inside.length,
    buttons: inside.filter(n => n.tagName === 'BUTTON').length,
    inputs: inside.filter(n => n.tagName === 'INPUT' || n.tagName === 'SELECT').length,
    unavailable: (text.match(/UNAVAILABLE/g) || []).length,
    says: text.replace(/\s+/g, ' ').slice(0, 150),
  });
  // A PICKER WITH NOTHING PICKED POSTS NOTHING, by design -- `if(!sel.value)return;`
  // guards every one of them. So the sweep chooses before it presses, which is what
  // the owner does; without this the board controls look dead and the sweep agrees.
  inside.filter(n => n.tagName === 'SELECT').forEach(s => {
    if (!s.value && s.children.length) s.value = s.children[0].value || s.children[0].textContent;
    s.fire('input'); s.fire('change');
  });
  inside.filter(n => n.tagName === 'INPUT' && (n.type === 'text' || n.type === 'search' || !n.type))
        .forEach(i => { if (!i.value) i.value = 'sweep'; i.fire('input'); i.fire('change'); });
  inside.filter(n => n.tagName === 'BUTTON' || n.tagName === 'INPUT' || n.tagName === 'SELECT')
        .slice(0, 120)
        .forEach(b => { if (b.tagName === 'BUTTON') b.click(); else { b.fire('input'); b.fire('change'); } });
});
// Two more rounds over the whole page: a click that reveals a control is only
// tested when the control it revealed is pressed too.
for (let round = 0; round < 2; round++) {
  descendants(root).filter(n => n.tagName === 'BUTTON' || n.handlers.click).forEach(b => b.click());
  descendants(root).filter(n => n.tagName === 'INPUT' || n.tagName === 'SELECT')
    .forEach(i => { i.fire('input'); i.fire('change'); });
}
if (empty.length) problems.push(`destinations that drew nothing a reader could use: ${empty.join(', ')}`);
(document._h && document._h.keydown || []).forEach(fn => {
  try { fn({ key: 'Escape', keyCode: 27, target: root, preventDefault() {}, stopPropagation() {} }); }
  catch (e) { note('the page-wide keydown handler on Escape', e); }
});
timers.splice(0).forEach(fn => { try { fn(); } catch (e) { note('a deferred callback', e); } });

// Anything the page itself recorded as an error is a defect, by its own account.
(window.__vesperErrs || []).forEach(e => problems.push(`the page recorded: ${e}`));

if (process.argv.includes('--report')) {
  console.log('  destination            nodes btn inp UNAV  what it says');
  report.forEach(r => console.log(
    `  ${r.view.padEnd(24)}${String(r.nodes).padStart(4)}${String(r.buttons).padStart(4)}` +
    `${String(r.inputs).padStart(4)}${String(r.unavailable).padStart(5)}  ${r.says}`));
}
console.log(problems.length ? 'FAILURES:\n  ' + problems.join('\n  ') : 'HOME PAGE HOLDS');
console.log(`  nodes_drawn=${drawn} buttons_clicked=${clicks} messages_to_host=${posted.length}`);
const kinds = {};
posted.forEach(p => { try { kinds[JSON.parse(p.message).action || p.name] = 1; } catch (e) { kinds[p.name] = 1; } });
console.log('  actions reached the host: ' + Object.keys(kinds).sort().join(', '));
process.exit(problems.length ? 1 : 0);
