// THE FLAG BAR'S RENDERER, DRIVEN. Run by `check_the_flag_bar_is_what_the_owner_asked_for`.
//
// WHY NODE AND NOT A GREP. Every property the owner asked for is a property of
// what the renderer PRODUCES -- nine flags shown rather than eight, a chip that
// carries words, a width taken from the menu's own rectangle, a panel with three
// states, a button that ASKS rather than acts. Reading the source for those is
// exactly the substring assertion that has gone vacuous a dozen times in this
// tree. This executes the real functions out of the real page.
//
// WHY A STUB AND NOT A BROWSER. The preview pane refuses scripts on local files
// (CSP), and `MEMORY.md` already records the answer: verify web instruments with a
// Node DOM stub. It is deliberately minimal, so a renderer reaching for something
// it does not implement fails loudly rather than being quietly satisfied.

// A DOM STUB, NOT A BROWSER. The pane blocks scripts on local files (CSP), and
// `MEMORY.md` already records the answer for that: verify web instruments with a
// Node DOM stub. This one is deliberately small -- it implements only what the
// flag renderer touches, so a function reaching for something else fails loudly
// rather than being quietly satisfied.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function El(tag) {
  return {
    tagName: (tag || '').toUpperCase(), children: [], className: '', textContent: '',
    hidden: false, style: { setProperty(){}, },  attrs: {}, type: '', disabled: false,
    classList: { _s: new Set(), add(c){ this._s.add(c); }, contains(c){ return this._s.has(c); } },
    appendChild(c){ this.children.push(c); return c; },
    insertBefore(c){ this.children.push(c); return c; },
    removeChild(c){ this.children = this.children.filter(x => x !== c); },
    addEventListener(){}, setAttribute(k,v){ this.attrs[k] = v; },
    getBoundingClientRect(){ return { width: this._w || 0 }; },
    get firstChild(){ return this.children[0] || null; },
    contains(){ return false; },
  };
}
const ids = {};
for (const id of ['flagbar','flags','flag-tip','flaghist']) ids[id] = El('div');
// THE REAL MARKUP STARTS THESE HIDDEN, and the stub must too: the history panel
// TOGGLES, so a stub that starts it visible closes it on the first click and the
// assertions below then measure an empty panel. The page is right; the stub was
// modelling a state the page never has.
ids['flaghist'].hidden = true; ids['flagbar'].hidden = true; ids['flag-tip'].hidden = true;
const dock = El('div'); dock._w = 742;          // the measured main-menu width
const posted = [];
global.window = {
  webkit: { messageHandlers: { vesperSay: { postMessage(m){ posted.push(m); } } } },
};
global.document = {
  getElementById: (i) => ids[i] || null,
  querySelector: (s) => (s === '.dockrow' ? dock : null),
  createElement: El,
  addEventListener(){}, removeEventListener(){},
  documentElement: { style: { _p: {}, setProperty(k,v){ this._p[k] = v; } } },
};
global.setTimeout = (f) => f();

// Pull the two renderers out of the real page and evaluate them.
function grab(name) {
  const i = src.indexOf('window.' + name + ' = function');
  if (i < 0) throw new Error('missing ' + name);
  let d = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') d++;
    else if (src[k] === '}') { d--; if (d === 0) return src.slice(i, k + 2); }
  }
  throw new Error('unbalanced ' + name);
}
eval(grab('__vesperFlags'));
eval(grab('__vesperFlagHistory'));

const flags = [
  {id:'a', text:'vesper has not been granted control of that application, and asking for it needs the owner'},
  {id:'b', text:'vesper opened a window and the system placed it on another desktop', carried:true},
  {id:'c', text:'vesper has no desktop of its own yet: 1 of your windows are on the one showing'},
  {id:'d', text:'vesper could not read a window interface'},
  {id:'e', text:'a fifth thing'}, {id:'f', text:'a sixth'}, {id:'g', text:'a seventh'},
  {id:'h', text:'an eighth'}, {id:'i', text:'a NINTH, which the old cap of 8 dropped'},
];
window.__vesperFlags(JSON.stringify(flags));

const chips = ids['flags'].children.filter(c => c.tagName === 'BUTTON');
const fails = [];
if (chips.length !== flags.length) fails.push(`bar shows ${chips.length} of ${flags.length} flags -- the owner asked for ALL live flags`);
if (chips.some(c => !c.textContent || !c.textContent.trim())) fails.push('a chip has no title text -- the owner asked for titles, not icons');
if (chips.some(c => c.textContent.length > 48)) fails.push('a title is not trimmed to a title');
const carried = chips.filter(c => c.classList.contains('carried'));
if (carried.length !== 1) fails.push(`${carried.length} chips marked carried, expected 1`);
if (!String(carried[0] && carried[0].attrs['aria-label']).includes('not re-checked')) fails.push('a carried flag does not say it has not been re-checked');
const w = document.documentElement.style._p['--flagbar-max'];
if (w !== '742px') fails.push(`width cap is ${w}, not the measured main-menu width 742px`);
if (typeof ids['flags'].onclick !== 'function') fails.push('clicking the bar does not open the history');

// the history panel
const hist = [
  {id:'a', text:'still wrong', at_s:1789090000, seen:3, state:'open'},
  {id:'z', text:'was wrong, now fixed', at_s:1789091000, resolved_at_s:1789091400, seen:1, state:'resolved'},
  {id:'b', text:'inherited across a restart', at_s:1789092000, seen:1, state:'carried'},
];
window.__vesperFlagHistory(JSON.stringify(hist));
ids['flags'].onclick();
const rows = ids['flaghist'].children.filter(c => c.className === 'fh-row');
if (rows.length !== hist.length) fails.push(`history shows ${rows.length} of ${hist.length} rows`);
const states = rows.map(r => r.children[2].textContent);
for (const want of ['open','resolved','carried']) {
  if (!states.includes(want)) fails.push(`history has no ${want} row -- 'fixed or not' is three states, not a boolean`);
}
const whens = rows.map(r => r.children[0].textContent);
if (whens.some(t => !/^\d{1,2}:\d{2}/.test(t))) fails.push(`a row has no timestamp: ${JSON.stringify(whens)}`);
function deep(el, out) {
  for (const c of (el.children || [])) { if (c.className === 'fh-fix') out.push(c); deep(c, out); }
  return out;
}
const fixBtns = deep(ids['flaghist'], []);
console.log('  row shapes:', rows.map(r => r.children.map(c => c.className || c.tagName).join('/')).join(' | '));
if (fixBtns.length !== 2) fails.push(`${fixBtns.length} 'fix this' buttons, expected 2 (not on the resolved row)`);
fixBtns[0].onclick({ stopPropagation(){} });
if (posted.length !== 1) fails.push('asking vesper to fix it posted nothing');
if (!String(posted[0]).startsWith('about this flag')) fails.push(`the fix request is not phrased as a question: ${posted[0]}`);
if (!String(posted[0]).includes('still wrong')) fails.push('the fix request does not carry the flag text');

console.log(fails.length ? 'FAILURES:\n  ' + fails.join('\n  ') : 'ALL FLAG BAR REQUIREMENTS HOLD');
console.log(`  chips=${chips.length} carried=${carried.length} width=${w} rows=${rows.length} states=${states.join(',')} fix_buttons=${fixBtns.length} posted=${JSON.stringify(posted[0]).slice(0,60)}`);
process.exit(fails.length ? 1 : 0);
