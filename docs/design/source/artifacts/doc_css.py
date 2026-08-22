CSS = r"""<style>
/* ── VESPER tokens. Dark-first: the bare :root IS the dark set, because ten of
   the eleven ambience sources are night and the mark is lit matter on black.
   Light is the redefinition, consistently across all three theme states. ── */
:root{
  --pitch:#03141f; --paper:#ffeae3;
  --ground:#03141f; --raised:#072230; --sunk:#010a11;
  --ink:#ffeae3; --ink2:#9db2be; --ink3:#5f7787;
  --accent:#ffaf95; --accent-dim:#c8785f;
  --gold:#C5A35A; --blush:#e8829d; --purple:#81609f; --ember:#B96645;
  --solar:#D99A52; --botanic:#8fa383; --cream:#f0e0c0;
  --line:rgba(255,234,227,.13); --line-2:rgba(255,234,227,.07);
  --glass-fill:rgba(255,255,255,.055); --glass-dock:rgba(255,255,255,.085);
  --spec:inset 0 1px 0 rgba(255,255,255,.16);
  --shadow:0 18px 44px -18px rgba(0,0,0,.75);
  --sheet-blur:blur(24px) saturate(180%); --chip-blur:blur(13px) saturate(160%);
  --dock-blur:blur(42px) saturate(200%);
  --r-chip:11px; --r-sheet:22px; --r-dock:34px;
  /* the real SwiftUI Spring(duration:bounce:) step responses, from springs.py */
  --smooth:linear(0.0000,0.0575,0.1804,0.3209,0.4553,0.5731,0.6712,0.7502,0.8123,0.8602,0.8967,0.9241,0.9445,0.9597,0.9708,0.9789,0.9848,0.9891,0.9922,0.9945,0.9960,0.9972,0.9980,0.9986,1.0000);
  --snappy:linear(0.0000,0.0541,0.1761,0.3225,0.4678,0.5981,0.7076,0.7952,0.8624,0.9121,0.9474,0.9715,0.9873,0.9971,1.0026,1.0053,1.0062,1.0061,1.0055,1.0046,1.0037,1.0028,1.0021,1.0015,1.0000);
  --dur-smooth:735ms; --dur-snappy:697ms;
  --measure:67ch;
}
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    --ground:#ffeae3; --raised:#fff6f2; --sunk:#f6ddd5;
    --ink:#03141f; --ink2:#4c5c66; --ink3:#7d8b93;
    --accent:#B96645; --accent-dim:#8e4c33;
    --purple:#59348a; --botanic:#5b6b53; --gold:#8b7130;
    --line:rgba(3,20,31,.14); --line-2:rgba(3,20,31,.07);
    --glass-fill:rgba(255,255,255,.55); --glass-dock:rgba(255,255,255,.66);
    --spec:inset 0 1px 0 rgba(255,255,255,.9);
    --shadow:0 18px 44px -20px rgba(60,26,14,.28);
  }
}
:root[data-theme="light"]{
  --ground:#ffeae3; --raised:#fff6f2; --sunk:#f6ddd5;
  --ink:#03141f; --ink2:#4c5c66; --ink3:#7d8b93;
  --accent:#B96645; --accent-dim:#8e4c33;
  --purple:#59348a; --botanic:#5b6b53; --gold:#8b7130;
  --line:rgba(3,20,31,.14); --line-2:rgba(3,20,31,.07);
  --glass-fill:rgba(255,255,255,.55); --glass-dock:rgba(255,255,255,.66);
  --spec:inset 0 1px 0 rgba(255,255,255,.9);
  --shadow:0 18px 44px -20px rgba(60,26,14,.28);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Outfit",-apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;
  font-weight:300; font-size:17px; line-height:1.62;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
::selection{background:var(--accent); color:var(--ground)}
a{color:var(--accent); text-decoration-color:color-mix(in oklab,var(--accent) 40%,transparent); text-underline-offset:3px}
a:focus-visible,button:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:4px}

/* ── the notch band. A hairline of hardware at the top of the page: the one
   piece of decoration in the document, and it is the subject's own silhouette ── */
.bezel{position:sticky; top:0; z-index:60; height:26px; background:var(--sunk);
  display:flex; align-items:flex-start; justify-content:center; border-bottom:1px solid var(--line-2)}
.bezel i{display:block; width:185px; height:18px; background:#000; border-radius:0 0 11px 11px}

/* ── hero ── */
.hero{padding:clamp(56px,9vw,116px) 24px clamp(40px,6vw,72px); position:relative; overflow:hidden}
.hero-in{max-width:1080px; margin:0 auto}
.eyebrow{font-family:"IBM Plex Mono",monospace; font-size:11.5px; letter-spacing:.22em;
  text-transform:uppercase; color:var(--ink3); margin:0 0 22px}
.hero h1{font-family:"Instrument Serif",Georgia,serif; font-weight:400;
  font-size:clamp(44px,7.4vw,86px); line-height:1.02; letter-spacing:-.015em;
  margin:0 0 26px; max-width:15ch; text-wrap:balance}
.hero h1 em{font-style:italic; color:var(--accent)}
.hero .sub{font-size:clamp(17px,2vw,21px); color:var(--ink2); max-width:60ch; margin:0; font-weight:300}
.hand{font-family:"Dancing Script",cursive; font-size:23px; color:var(--accent-dim);
  margin:34px 0 0; max-width:44ch; line-height:1.45}

/* the three checked facts — instrument row, not cards */
.facts{display:grid; grid-template-columns:repeat(auto-fit,minmax(228px,1fr));
  gap:1px; background:var(--line-2); border:1px solid var(--line-2); border-radius:var(--r-sheet);
  overflow:hidden; margin:48px 0 0}
.facts div{background:var(--ground); padding:20px 22px}
.facts b{display:block; font-family:"IBM Plex Mono",monospace; font-size:10.5px;
  letter-spacing:.18em; text-transform:uppercase; color:var(--ink3); font-weight:500; margin-bottom:9px}
.facts p{margin:0; font-size:15px; color:var(--ink2); line-height:1.5}
.facts strong{color:var(--ink); font-weight:500}

/* ── shell ── */
.shell{max-width:1240px; margin:0 auto; padding:0 24px 120px;
  display:grid; grid-template-columns:1fr; gap:0}
@media(min-width:1080px){ .shell{grid-template-columns:206px minmax(0,1fr); gap:56px} }

nav.rail{display:none}
@media(min-width:1080px){
  nav.rail{display:block; position:sticky; top:52px; align-self:start; max-height:calc(100vh - 84px);
    overflow-y:auto; padding:12px 0 40px; scrollbar-width:thin}
  nav.rail h6{font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.2em;
    text-transform:uppercase; color:var(--ink3); margin:26px 0 12px; font-weight:500}
  nav.rail .navgroup:first-child h6{margin-top:0}
  nav.rail a{display:flex; gap:10px; align-items:baseline; padding:5px 0; font-size:13.5px;
    color:var(--ink2); text-decoration:none; line-height:1.35}
  nav.rail a:hover{color:var(--accent)}
  nav.rail a b{font-family:"IBM Plex Mono",monospace; font-size:10.5px; color:var(--ink3);
    font-weight:500; min-width:22px; font-variant-numeric:tabular-nums}
  nav.rail a.on{color:var(--accent)} nav.rail a.on b{color:var(--accent)}
}

main{min-width:0; max-width:var(--measure)}
main.wide{max-width:none}

/* ── prose ── */
h2{font-family:"Instrument Serif",Georgia,serif; font-weight:400; font-size:clamp(30px,3.8vw,42px);
  line-height:1.14; letter-spacing:-.012em; margin:84px 0 22px; text-wrap:balance;
  display:flex; gap:16px; align-items:baseline; scroll-margin-top:64px}
h2 .num{font-family:"IBM Plex Mono",monospace; font-size:12px; letter-spacing:.1em;
  color:var(--accent); font-weight:500; flex:none; padding-top:.5em; font-variant-numeric:tabular-nums}
h3{font-family:"Outfit",sans-serif; font-weight:500; font-size:20px; line-height:1.3;
  margin:52px 0 14px; letter-spacing:-.005em; display:flex; gap:14px; align-items:baseline;
  scroll-margin-top:64px}
h3 .num{font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--ink3); font-weight:500; flex:none}
h4{font-family:"Outfit",sans-serif; font-weight:500; font-size:16px; margin:32px 0 10px; color:var(--ink)}
p{margin:0 0 19px}
p.lede{font-size:19px; color:var(--ink); line-height:1.5}
strong{font-weight:500; color:var(--ink)}
em{font-style:italic}
hr{border:0; border-top:1px solid var(--line-2); margin:72px 0}
ul,ol{margin:0 0 22px; padding-left:1.35em} li{margin:0 0 10px; color:var(--ink2)}
li strong{color:var(--ink)}
code{font-family:"IBM Plex Mono",monospace; font-size:.855em; background:color-mix(in oklab,var(--ink) 8%,transparent);
  padding:.14em .42em; border-radius:5px; color:var(--ink); white-space:nowrap}
pre{background:var(--sunk); border:1px solid var(--line-2); border-radius:var(--r-chip);
  padding:20px 22px; overflow-x:auto; margin:0 0 26px; box-shadow:var(--spec)}
pre code{background:none; padding:0; font-size:13px; line-height:1.62; white-space:pre; color:var(--ink2)}

/* owner quotes — the subject's own voice, set apart in the display face */
blockquote{margin:30px 0; padding:0 0 0 26px; border-left:2px solid var(--accent);
  font-family:"Instrument Serif",Georgia,serif; font-size:21px; line-height:1.42; color:var(--ink)}
blockquote p{margin:0} blockquote em{color:var(--accent-dim)}

/* ── tables: instrument panels, glass at Sheet tier ── */
.tw{margin:0 0 30px; overflow-x:auto; border:1px solid var(--line); border-radius:var(--r-sheet);
  background:var(--glass-fill); -webkit-backdrop-filter:var(--sheet-blur); backdrop-filter:var(--sheet-blur);
  box-shadow:var(--spec),var(--shadow)}
@media(min-width:1080px){ .tw{width:min(920px,calc(100vw - 340px))} }
table{border-collapse:collapse; width:100%; font-size:14.5px; line-height:1.5}
thead th{text-align:left; font-family:"IBM Plex Mono",monospace; font-size:10px; font-weight:500;
  letter-spacing:.16em; text-transform:uppercase; color:var(--ink3);
  padding:15px 18px; border-bottom:1px solid var(--line); white-space:nowrap; vertical-align:bottom}
tbody td{padding:14px 18px; border-bottom:1px solid var(--line-2); color:var(--ink2); vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:color-mix(in oklab,var(--ink) 3.5%,transparent)}
tbody td:first-child{color:var(--ink); font-weight:400}
td code,th code{white-space:normal}
tbody td strong{font-weight:500}

/* ── status pills: state in form as well as word ── */
.pill{display:inline-block; font-family:"IBM Plex Mono",monospace; font-size:10px; font-weight:500;
  letter-spacing:.11em; padding:3px 8px 2.5px; border-radius:5px; white-space:nowrap;
  border:1px solid currentColor; line-height:1.35; vertical-align:baseline}
.p-frontend{color:var(--gold)} .p-ready{color:var(--botanic)}
.p-blocked{color:var(--ember)} .p-superseded{color:var(--ink3)}
.p-partial{color:var(--solar)}

/* ── part divider ── */
.part{margin:120px 0 0; padding:44px 0 0; border-top:1px solid var(--line)}
.part .eyebrow{margin-bottom:14px}
.part h1{font-family:"Instrument Serif",Georgia,serif; font-weight:400; font-size:clamp(34px,5vw,54px);
  line-height:1.05; margin:0 0 16px; letter-spacing:-.014em}
.part p{color:var(--ink2); max-width:56ch; margin:0}

/* legend */
.legend{display:flex; flex-wrap:wrap; gap:10px 20px; margin:26px 0 0; padding:18px 20px;
  border:1px solid var(--line-2); border-radius:var(--r-chip); background:var(--glass-fill);
  -webkit-backdrop-filter:var(--chip-blur); backdrop-filter:var(--chip-blur); box-shadow:var(--spec)}
.legend span{font-size:13px; color:var(--ink3); display:flex; align-items:center; gap:9px}

footer{max-width:1240px; margin:0 auto; padding:0 24px 90px; color:var(--ink3); font-size:13.5px}
footer .fin{border-top:1px solid var(--line-2); padding-top:26px;
  display:flex; flex-wrap:wrap; gap:14px 34px; justify-content:space-between}
footer code{font-size:12px}

.themebtn{position:fixed; right:18px; bottom:18px; z-index:70; width:42px; height:42px; border-radius:50%;
  border:1px solid var(--line); background:var(--glass-dock);
  -webkit-backdrop-filter:var(--dock-blur); backdrop-filter:var(--dock-blur);
  color:var(--ink2); cursor:pointer; box-shadow:var(--spec),var(--shadow); font-size:15px;
  transition:color var(--dur-snappy) var(--snappy), transform var(--dur-snappy) var(--snappy)}
.themebtn:hover{color:var(--accent); transform:scale(1.06)}

@media (prefers-reduced-motion: reduce){ *{animation:none!important; transition:none!important} }
@media (prefers-reduced-transparency: reduce){
  .tw,.legend,.themebtn{background:var(--raised); -webkit-backdrop-filter:none; backdrop-filter:none}
}
</style>"""
