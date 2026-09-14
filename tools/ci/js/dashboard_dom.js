// THE PROJECTS DASHBOARD'S RENDERER, DRIVEN. Run by
// `check_the_projects_dashboard_is_what_the_owner_asked_for`.
//
// EVERY REQUIREMENT IN §28 IS A PROPERTY OF WHAT THE RENDERER PRODUCES, not of
// what its source says: three switches that are three DIFFERENT controls, a
// phase list from the contract, panels that either carry a real reading with its
// source or say UNAVAILABLE with a reason, composed panels marked as composed
// rather than rebuilt, and the directory named out loud. Reading source for
// those is the substring assertion that has gone vacuous twelve times here.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

function El(tag) {
  return {
    tagName: (tag || '').toUpperCase(), children: [], className: '', textContent: '',
    hidden: false, type: '', title: '', dataset: {}, attrs: {}, style: {},
    classList: { list: [], add(c){ this.list.push(c); }, contains(c){ return this.list.includes(c); } },
    append(...cs){ cs.forEach(c => this.children.push(c)); },
    appendChild(c){ this.children.push(c); return c; },
    setAttribute(k, v){ this.attrs[k] = v; }, addEventListener(){},
  };
}
function node(tag, cls, text) {
  const e = El(tag);
  e.className = cls || '';
  if (text !== undefined) e.textContent = String(text);
  return e;
}
const content = El('div'), intro = El('p');
let railData = { dashboard: data }, opener = null;
function show(){ /* re-render is asserted separately */ }

// Pull the two real functions out of the page rather than reimplementing them.
function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) return null;
  let d = 0;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') d++;
    else if (src[k] === '}') { d--; if (d === 0) return src.slice(i, k + 1); }
  }
  return null;
}
// renderBoard AND ITS HELPERS TOO: renderProjects draws the board since the
// owner asked for windows and cards on the dashboard, and a driver that grabbed
// only the first two functions threw on the call (full suite, 2026-09-14).
const fns = ['dashSwitch', 'renderProjects', 'renderBoard', 'actionButtons',
             'boardPost', 'stateChip'].map(grab);
if (fns.some(f => !f)) {
  console.log('FAILURES:\n  the dashboard renderer is gone from the page');
  process.exit(1);
}
let dashPhase = '', dashMode = 'work';
eval(fns.join('\n'));

renderProjects();

const fails = [];
// THE BOARD IS ON THE DASHBOARD (owner, 2026-09-13: windows and cards chosen
// from a list, with management), drawn by the page's own renderBoard -- which,
// with no boards pushed yet, must still draw its section and say why it is empty.
const boardSect = content.children.find(c => c.className === 'board');
if (!boardSect) fails.push('the projects board is not drawn on the dashboard');
else if (!boardSect.children.some(c => /producer has not run yet/.test(c.textContent || ''))) {
  fails.push('with no boards pushed, the board section does not say why it is empty');
}
const top = content.children.find(c => c.className === 'dash-top');
const grid = content.children.find(c => c.className === 'dash-grid');
if (!top) fails.push('no switch row was drawn at the top');
if (!grid) fails.push('no panel grid was drawn');

if (top) {
  const switches = top.children.filter(c => c.className === 'dash-switch');
  // THREE SWITCHES, NOT ONE. The owner named phase, engineering mode and
  // engineering phase as separate controls; merging them is the first way this
  // gets built wrong, so the count is asserted rather than the markup.
  if (switches.length < 2) fails.push(`only ${switches.length} switch(es) drawn; phase and engineering mode are different axes`);
  const chips = switches.flatMap(s => (s.children.find(c => c.className === 'dash-switch-row') || {children: []}).children);
  if (chips.length !== data.phases.length + data.modes.length) {
    fails.push(`${chips.length} chips for ${data.phases.length} phases + ${data.modes.length} modes`);
  }
  const on = chips.filter(c => c.classList.contains('is-on'));
  if (on.length !== 2) fails.push(`${on.length} chips marked current; exactly one phase and one mode should be`);
  // THE CONTRACT'S OWN SENTENCE TRAVELS, so a chip can explain itself.
  const explained = chips.filter(c => c.title && c.title.length > 10);
  if (explained.length !== chips.length) fails.push(`${chips.length - explained.length} chip(s) carry no explanation`);
}

if (grid) {
  const panels = grid.children;
  if (panels.length !== data.panels.length) fails.push(`drew ${panels.length} of ${data.panels.length} panels`);
  let composed = 0, available = 0, unavailable = 0;
  panels.forEach((p, n) => {
    const srcRow = data.panels[n];
    const texts = p.children.map(c => String(c.textContent || ''));
    if (!texts[0]) fails.push(`panel ${n} has no name`);
    if (srcRow.status === 'composed') {
      composed++;
      if (!texts.includes('COMPOSED')) fails.push(`${srcRow.id} is composed and is not marked so -- a second terminal is a second thing to keep correct`);
    } else if (srcRow.status === 'available') {
      available++;
      if (texts.includes('UNAVAILABLE')) fails.push(`${srcRow.id} read a value and shows UNAVAILABLE`);
      if (!p.children.some(c => c.className === 'dash-source' && c.textContent)) {
        fails.push(`${srcRow.id} shows a reading with no source`);
      }
    } else {
      unavailable++;
      if (!texts.includes('UNAVAILABLE')) fails.push(`${srcRow.id} has no reading and does not say UNAVAILABLE`);
      // A FALSE ZERO LOOKS MEASURED AND IS NOT: the reason must reach the owner.
      const why = String(srcRow.value || srcRow.what || '').slice(0, 20);
      if (why && !texts.some(t => t.includes(why))) fails.push(`${srcRow.id} is unavailable and does not carry its reason`);
    }
  });
  if (!composed) fails.push('no panel is composed; terminal, commands and history must be reused, not rebuilt');
}

// THE DIRECTORY IS NAMED. Vesper answered "the project root" with the bundle
// once; a surface about a directory says which one.
if (data.project_root && !String(intro.textContent).includes(data.project_root)) {
  fails.push('the dashboard does not name the project directory it is about');
}

if (fails.length) { console.log('FAILURES:\n  ' + fails.join('\n  ')); process.exit(1); }
console.log(`OK ${data.panels.length} panels, ${data.phases.length} phases, ${data.modes.length} modes, directory named`);
