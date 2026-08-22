/* Drive the previews page instead of trusting it.
 *
 * There is no browser automation on this machine, and `node --check` only
 * proves the file parses. This extracts the page's script, runs it against a
 * DOM stub, renders every stage x desk x ambience mode, and asserts the output.
 *
 * IT CARRIES ITS OWN NEGATIVE CONTROLS. `--controls` mutates the page three
 * ways and requires each mutation to go red. A harness nobody has seen fail
 * proves nothing -- the standing rule in MEMORY.md.
 *
 *   ~/.local/node/bin/node docs/design/source/artifacts/test_previews.js
 *   ~/.local/node/bin/node docs/design/source/artifacts/test_previews.js --controls
 */
const fs = require('fs'), path = require('path'), vm = require('vm');
const HERE = __dirname;
const PAGE = path.join(HERE, 'home-previews.html');

function pageScript() {
  const html = fs.readFileSync(PAGE, 'utf8');
  const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  if (!blocks.length) throw new Error('no <script> found in ' + PAGE);
  return blocks.join('\n');
}

function run(src) {
  const stub = fs.readFileSync(path.join(HERE, 'dom_stub.js'), 'utf8');
  const i = src.lastIndexOf('})();');
  const exposed = src.slice(0, i) +
    'global.__t={render:render,state:state,stages:STAGES,modes:MODES};\n' + src.slice(i);
  const harness = `
    var fails = 0, checks = 0;
    function ok(c, m) { checks++; if (!c) { fails++; console.log('  FAIL: ' + m); } }
    var pw = document.getElementById('planeWork'), pf = document.getElementById('planeFloat'),
        ro = document.getElementById('readout'), dk = document.getElementById('dockbar'),
        cp = document.getElementById('capstate'), pn = document.getElementById('pins');
    Object.keys(__t.stages).forEach(function (s) {
      var st = __t.stages[s];
      __t.state.desk = 'vesper'; __t.state.stage = s; __t.state.mode = st.amb; __t.render();
      ok(pw.innerHTML.length >= (st.win.length ? 40 : 0), s + ': work plane empty, expected ' + st.win.length + ' windows');
      ok(!/undefined|NaN|\\[object/.test(pw.innerHTML), s + ': work plane carries undefined/NaN');
      ok(!/undefined|NaN|\\[object/.test(pf.innerHTML), s + ': float plane carries undefined/NaN');
      ok(!/undefined|NaN/.test(ro.innerHTML), s + ': readout carries undefined/NaN');
      ok(ro.innerHTML.indexOf(st.face) > -1, s + ': readout omits the face tier ' + st.face);
      ok(dk.innerHTML.indexOf(st.label) > -1, s + ': main menu omits the stage label');
      ok(pn.innerHTML.indexOf('<b>7</b>') > -1, s + ': annotation pins incomplete');
    });
    __t.state.desk = 'owner'; __t.render();
    ok(pw.innerHTML.indexOf('foreign') > -1, 'owner Desktop draws no foreign window');
    ok(ro.innerHTML.indexOf('Shoulders') > -1, 'owner Desktop readout does not report the island');
    ok(cp.innerHTML.indexOf('Your Desktop') > -1, 'owner Desktop caption wrong');
    __t.modes.forEach(function (m) {
      __t.state.desk = 'vesper'; __t.state.mode = m.k; __t.render();
      ok(ro.innerHTML.indexOf(m.k) > -1, 'ambience ' + m.k + ' not reflected in the readout');
      ok(/^#[0-9a-f]{6}$/i.test(m.g) && /^#[0-9a-f]{6}$/i.test(m.a), 'ambience ' + m.k + ' has a malformed hex');
    });
    global.__result = { checks: checks, fails: fails };
  `;
  const ctx = { console, process };
  ctx.global = ctx;
  vm.createContext(ctx);
  vm.runInContext(stub + exposed + harness, ctx, { filename: 'previews.js' });
  return ctx.__result;
}

if (process.argv.includes('--controls')) {
  const src = pageScript();
  const controls = [
    ['a malformed ambience hex',      s => s.replace('{k:"Alert",g:"#061016"', '{k:"Alert",g:"#06101"')],
    ['the face tier dropped from the readout', s => s.replace('esc(S.face)', "'--'")],
    ['the work plane rendering nothing', s => s.replace('pw.innerHTML = wins.map', 'pw.innerHTML = [].map')],
  ];
  let bad = 0;
  for (const [name, mutate] of controls) {
    let red = false, r = null;
    try { r = run(mutate(src)); red = r.fails > 0; } catch (e) { red = true; }
    console.log((red ? '  red   ' : '  GREEN ') + ' control: ' + name);
    if (!red) bad++;
  }
  if (bad) { console.log('\n' + bad + ' control(s) PASSED. A control that passes is the defect.'); process.exit(1); }
  console.log('\n3/3 controls went red, as required.');
  process.exit(0);
}

const r = run(pageScript());
console.log(r.checks + ' assertions, ' + r.fails + ' failures');
process.exit(r.fails ? 1 : 0);
