BODY = r"""
<div class="bezel"><i></i></div>

<header class="hero">
  <div class="hero-in">
    <p class="eyebrow">docs/design · 2026-08-22 · engineering record</p>
    <h1>A workspace macOS <em>will not</em> create.</h1>
    <p class="sub">VESPER's home is a place, not a window — ninety cards, twelve stages,
      seven kinds of window and a face that gets out of the way when the work needs the
      screen. This is what the operating system actually gives it, what it provably does
      not, and the order it gets built in.</p>
    <p class="hand">I checked the headers before I believed the documentation. Two of the
      answers were no.</p>

    <div class="facts">
      <div><b>Checked, not assumed</b><p>No public API creates, names or enumerates a Space.
        <strong>Zero hits</strong> for <code>CGSSpace</code> in public CoreGraphics headers.</p></div>
      <div><b>Checked, not assumed</b><p>Accessibility has <strong>no attribute</strong> for a
        window's Space. Position, size, minimised, fullscreen — nothing else.</p></div>
      <div><b>Buildable today</b><p><strong>56 of 90</strong> home cards need no backend.
        The catalogue's own status field said 26.</p></div>
    </div>
  </div>
</header>

<div class="shell">
  <nav class="rail">@@NAV@@</nav>
  <main>
    <div class="legend">
      <span><span class="pill p-frontend">FRONTEND</span> no producer needed</span>
      <span><span class="pill p-ready">READY</span> producer exists, binding missing</span>
      <span><span class="pill p-blocked">BLOCKED</span> nothing can produce it</span>
      <span><span class="pill p-superseded">SUPERSEDED</span> a decision removes it</span>
    </div>

    @@ARCH@@

    <div class="part">
      <p class="eyebrow">Part two</p>
      <h1>What it can carry</h1>
      <p>Every card, widget, window and stage, with whether it can be hooked up today —
        so that designing a surface and wiring it are separate acts and neither waits on
        the other.</p>
    </div>

    @@CONT@@
  </main>
</div>

<footer>
  <div class="fin">
    <span>Sources: <code>docs/design/HOME-ARCHITECTURE.md</code> · <code>HOME-CONTENT.md</code> ·
      room arithmetic derived by <code>source/home_rooms.py</code></span>
    <span>31/31 checks · 79/79 self-tests · reference + traceability lint PASS</span>
  </div>
</footer>

<button class="themebtn" id="tb" aria-label="Switch between light and dark">◐</button>
<script>
(function(){
  var r=document.documentElement, b=document.getElementById('tb');
  try{ var s=localStorage.getItem('vesper-theme'); if(s) r.setAttribute('data-theme',s); }catch(e){}
  b.addEventListener('click',function(){
    var cur=r.getAttribute('data-theme');
    if(!cur){ cur = matchMedia('(prefers-color-scheme: light)').matches ? 'light':'dark'; }
    var next = cur==='dark' ? 'light':'dark';
    r.setAttribute('data-theme',next);
    try{ localStorage.setItem('vesper-theme',next); }catch(e){}
  });
  // rail: mark the section in view
  var links=[].slice.call(document.querySelectorAll('nav.rail a'));
  var map={}; links.forEach(function(a){ var t=document.getElementById(a.getAttribute('href').slice(1)); if(t) map[a.getAttribute('href').slice(1)]=a; });
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){
      es.forEach(function(e){ var a=map[e.target.id]; if(!a) return;
        if(e.isIntersecting){ links.forEach(function(x){x.classList.remove('on')}); a.classList.add('on'); } });
    },{rootMargin:'-10% 0px -80% 0px'});
    Object.keys(map).forEach(function(id){ io.observe(document.getElementById(id)); });
  }
})();
</script>
"""
