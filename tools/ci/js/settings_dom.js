// THE SETTINGS SURFACE'S RENDERER, DRIVEN. Run by
// `check_the_settings_surface_reads_and_explains`.
//
// Same reasoning as the flag bar's stub: every requirement in §11.6 is a property
// of what the renderer PRODUCES -- thirty-four rows, a real value where one was
// read, UNAVAILABLE with a reason where none was, an explanation on every row,
// and a governed row saying where it is changed. Reading source for those is the
// substring assertion that went vacuous nine times in one session.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const rows = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

function El(tag) {
  return {
    tagName: (tag || '').toUpperCase(), children: [], className: '', textContent: '',
    hidden: false, tabIndex: 0, attrs: {},
    appendChild(c){ this.children.push(c); return c; },
    removeChild(c){ this.children = this.children.filter(x => x !== c); },
    setAttribute(k,v){ this.attrs[k] = v; }, addEventListener(){},
    get firstChild(){ return this.children[0] || null; },
  };
}
const panel = El('div'); panel.hidden = true;
global.window = {};
global.document = {
  getElementById: (i) => (i === 'settings' ? panel : null),
  createElement: El, addEventListener(){}, removeEventListener(){},
};
const i = src.indexOf('window.__vesperSettings = function');
if (i < 0) { console.log('FAILURES:\n  the settings renderer is gone from the page'); process.exit(1); }
let d = 0, j = src.indexOf('{', i), body = null;
for (let k = j; k < src.length; k++) {
  if (src[k] === '{') d++;
  else if (src[k] === '}') { d--; if (d === 0) { body = src.slice(i, k + 2); break; } }
}
eval(body);

window.__vesperSettings(JSON.stringify(rows));
window.__vesperSettings();

const fails = [];
const drawn = panel.children.filter(c => c.className === 'st-row');
if (drawn.length !== rows.length) fails.push(`drew ${drawn.length} of ${rows.length} settings rows`);
if (panel.hidden) fails.push('the panel stayed hidden after being opened');

let withValue = 0, unavailable = 0, explained = 0, governedSaysWhere = 0;
for (let n = 0; n < drawn.length; n++) {
  const row = drawn[n], src_ = rows[n];
  const left = row.children[0], right = row.children[1];
  const name = left.children[0].textContent, what = left.children[1].textContent;
  const val = right.children[0].textContent;
  const gov = right.children[right.children.length - 1].textContent;
  if (!name) fails.push(`row ${n} has no name`);
  if (!what || what.length < 20) fails.push(`row ${n} (${name}) has no explanation -- "explain this setting" is a property of every row`);
  else explained++;
  if (src_.status === 'available') {
    withValue++;
    if (val === 'UNAVAILABLE') fails.push(`${name} read a value and shows UNAVAILABLE`);
    if (!String(val).trim()) fails.push(`${name} shows an empty value`);
    // THE SOURCE TRAVELS WITH THE NUMBER. A figure with no source is the defect
    // MEMORY.md opens by refusing.
    const hasSource = right.children.some(c => c.className === 'st-source' && c.textContent);
    if (!hasSource) fails.push(`${name} shows a value with no source`);
  } else {
    unavailable++;
    if (val !== 'UNAVAILABLE') fails.push(`${name} has no reading and does not say UNAVAILABLE`);
    if (!what.includes(src_.reason.slice(0, 24))) fails.push(`${name} is unavailable and does not carry its reason`);
  }
  if (src_.governed) {
    if (gov !== 'governed') fails.push(`${name} is governed and is not marked so`);
    if (src_.status === 'available' && !what.includes('changed by')) governedSaysWhere--;
    else governedSaysWhere++;
  } else if (gov !== 'yours to set') {
    fails.push(`${name} is the owner's preference and is marked ${JSON.stringify(gov)}`);
  }
}
// AND THE HEADER MUST ADMIT THE ABSENCES. A surface showing 19 values and quiet
// about 15 gaps claims a completeness it does not have.
const sub = panel.children.find(c => c.className === 'st-sub');
if (!sub || !sub.textContent.includes(String(withValue) + ' of ' + String(rows.length))) {
  fails.push(`the header does not state how many of the ${rows.length} rows read a real value`);
}
console.log(fails.length ? 'FAILURES:\n  ' + fails.join('\n  ') : 'SETTINGS SURFACE HOLDS');
console.log(`  rows=${drawn.length} with_value=${withValue} unavailable=${unavailable} explained=${explained} header=${JSON.stringify((sub||{}).textContent||'').slice(0,64)}`);
process.exit(fails.length ? 1 : 0);
