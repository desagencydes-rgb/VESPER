// Transport unit tests, NOT rendering or live acceptance evidence.
// Execute the actual receiver closure without a DOM, geometry, or fake page.
// The mounted app remains the only acceptance surface (menu brief §7.1).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'app/home-macos/chrome/home.html'), 'utf8');
const start = html.indexOf('  var previousMetrics=window.__vesperMetrics;');
const end = html.indexOf('  var previousHistory=', start);
assert(start >= 0 && end > start, 'production receiver must be identifiable');
const source = html.slice(start, end);
const catalogue = JSON.parse(fs.readFileSync(path.join(root, 'tools/menu_catalogue.json'), 'utf8'));
const item = catalogue.find(i => i.area === 'instruments');
const reading = {id:item.id, label:item.name, area:item.area, value:'observed', status:'available'};

function check(code) {
  const delivered = [];
  let failure = false;
  const context = vm.createContext({
    window: {__vesperMetrics: text => delivered.push(text)},
    catalogue: new Map(catalogue.map(i => [i.id, i])),
    rows: new Map(), MAX_MENU_METRIC_ROWS:100, lastMetrics:null, receiveVersion:0,
    refresh: () => {if(failure) throw new Error('menu rendering failed');}
  });
  vm.runInContext(code, context);
  // An unrelated prefix must not displace the catalogue reading. Forward the
  // original bytes, including host/other data, rather than reconstructing them.
  const payload = JSON.stringify([...Array.from({length:150}, (_,i) => ({label:'other '+i})), reading]);
  context.window.__vesperMetrics(payload);
  assert.equal(context.rows.size, 1);
  assert.equal(context.rows.get(item.id).value, 'observed');
  assert.equal(delivered.at(-1), payload);
  assert.equal(context.receiveVersion, 1);
  context.window.__vesperMetrics(payload);
  assert.equal(context.receiveVersion, 1, 'identical payload is not a new observation');
  assert.equal(delivered.length, 2, 'host still receives identical pushes');

  context.window.__vesperMetrics(JSON.stringify([{...reading,area:'host'}]));
  assert.equal(context.rows.size, 0, 'matching names/IDs do not override a wrong producer tag');
  context.window.__vesperMetrics(JSON.stringify([{...reading,label:'other'}]));
  assert.equal(context.rows.size, 0, 'mismatched catalogue identity is rejected');
  context.window.__vesperMetrics('not json');
  assert.equal(context.rows.size, 0, 'malformed input clears earlier menu data');
  assert.equal(delivered.at(-1), 'not json', 'host handles its own malformed input');

  failure = true;
  const before = delivered.length;
  assert.throws(() => context.window.__vesperMetrics(payload), /menu rendering failed/);
  assert.equal(delivered.length, before + 1, 'menu failure must not silence host');
  assert.equal(delivered.at(-1), payload);
}
check(source);
for (const [name,from,to] of [
  ['host payload discarded', 'previousMetrics(json);', "previousMetrics('[]');"],
  ['wrong producer accepted', 'r.area===item.area&&', ''],
  ['menu failure silences host', '}finally{', '}catch(e){throw e;} {']
]) {
  assert(source.includes(from), 'control must modify production code: '+name);
  const mutated = source.replace(from,to);
  new vm.Script(mutated); // A syntax error would test nothing about transport.
  assert.throws(() => check(mutated), {code:'ERR_ASSERTION'}, 'control escaped: '+name);
  console.log('Detected negative control: '+name);
}
const missing = vm.createContext({window:{},catalogue:new Map(),rows:new Map(),
  MAX_MENU_METRIC_ROWS:100,lastMetrics:null,receiveVersion:0,refresh:()=>{}});
vm.runInContext(source,missing);
assert.throws(() => missing.window.__vesperMetrics('[]'), /HOST metrics receiver is missing/);
console.log('PASS: production receiver transport; three faults detected. NOT live rendering evidence.');
