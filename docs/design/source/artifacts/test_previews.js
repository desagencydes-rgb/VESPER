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
// The BUILT page, not the source: the source carries a <!--WALLPAPERS--> marker
// where the data URIs go, so testing it would test a page with no wallpapers and
// the ambience assertions would be vacuous. A test that passes because the thing
// it checks is absent is the failure mode this file exists to avoid.
const PAGE = path.join(HERE, 'home-previews.built.html');

function pageScript() {
  if (!fs.existsSync(PAGE)) {
    console.error('no ' + path.basename(PAGE) + ' — run build_home_previews.py first');
    process.exit(2);
  }
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
        cp = document.getElementById('capstate'), pn = document.getElementById('pins'),
        pd = document.getElementById('planeDeco'), rl = document.getElementById('rail'),
        tx = document.getElementById('transcript'), sc = document.getElementById('scr');
    Object.keys(__t.stages).forEach(function (s) {
      var st = __t.stages[s];
      __t.state.desk = 'vesper'; __t.state.stage = s; __t.state.mode = st.amb; __t.render();
      ok(pw.innerHTML.length >= (st.win.length ? 40 : 0), s + ': work plane empty, expected ' + st.win.length + ' windows');
      ok(!/undefined|NaN|\\[object/.test(pw.innerHTML), s + ': work plane carries undefined/NaN');
      ok(!/undefined|NaN|\\[object/.test(pf.innerHTML), s + ': float plane carries undefined/NaN');
      ok(!/undefined|NaN/.test(ro.innerHTML), s + ': readout carries undefined/NaN');
      ok(ro.innerHTML.indexOf(st.face) > -1, s + ': readout omits the face tier ' + st.face);
      ok(dk.innerHTML.indexOf(st.label) > -1, s + ': main menu omits the stage label');
      ok(pn.innerHTML.indexOf('<b>9</b>') > -1, s + ': annotation pins incomplete');
      // the surfaces the owner's reference added, 2026-08-22
      ok((pd.innerHTML.match(/class="art/g) || []).length === (st.deco || []).filter(function (d) { return d.t === 'art'; }).length,
         s + ': artifact count does not match the stage');
      ok(!/undefined|NaN/.test(pd.innerHTML), s + ': deco plane carries undefined/NaN');
      ['projects', 'research', 'history', 'settings'].forEach(function (n) {
        ok(rl.innerHTML.indexOf(n) > -1, s + ': rail is missing ' + n);
      });
      ok(tx.textContent === (st.tr || ''), s + ': transcript does not match the stage');
      ok(String(sc.style.backgroundImage || '').indexOf('data:image') > -1,
         s + ': no wallpaper set for ambience ' + st.amb);
    });
    __t.state.desk = 'owner'; __t.render();
    ok(pw.innerHTML.indexOf('foreign') > -1, 'owner Desktop draws no foreign window');
    ok(ro.innerHTML.indexOf('Shoulders') > -1, 'owner Desktop readout does not report the island');
    ok(cp.innerHTML.indexOf('Your Desktop') > -1, 'owner Desktop caption wrong');
    ok(pd.innerHTML === '', 'owner Desktop draws VESPER decorations');
    ok(tx.textContent === '', 'owner Desktop shows a transcript');
    ok(String(sc.style.backgroundImage) === 'none', 'owner Desktop is painted with a VESPER wallpaper');
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
    ['the rail losing a destination', s => s.replace("['projects','research','history','settings']", "['projects','research','history']")],
    ['the wallpaper never being set', s => s.replace("scr.style.backgroundImage = (!owner && wp)", "scr.style.backgroundImage = (false && wp)")],
  ];
  let bad = 0;
  for (const [name, mutate] of controls) {
    let red = false, r = null;
    try { r = run(mutate(src)); red = r.fails > 0; } catch (e) { red = true; }
    console.log((red ? '  red   ' : '  GREEN ') + ' control: ' + name);
    if (!red) bad++;
  }
  if (bad) { console.log('\n' + bad + ' control(s) PASSED. A control that passes is the defect.'); process.exit(1); }
  console.log('\n' + controls.length + '/' + controls.length + ' controls went red, as required.');
  process.exit(0);
}

const r = run(pageScript());
console.log(r.checks + ' assertions, ' + r.fails + ' failures');
process.exit(r.fails ? 1 : 0);
