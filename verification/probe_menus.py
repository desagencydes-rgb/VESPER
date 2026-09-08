"""Render the real menu in the copied app, with isolated snapshot injection.

The existing binary always reads the owner's home.json. This harness gives its
unchanged receiver an explicitly supplied snapshot instead, in a temporary copy
of the template. It never rewrites live state or the inline fallback. The audit
reads actual DOM nodes and layout boxes; fixtures are labelled separately from
real observations. No snapshot API or screenshot grant is needed.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
MAX_PROBE_SECONDS=30


def probe(rows,case,*,view='instruments'):
    template=(REPO/'app/home-macos/chrome/home.html').read_text()
    injected=json.dumps(rows,ensure_ascii=True).replace('<','\\u003c')
    js='''<script>
    document.addEventListener('DOMContentLoaded',function(){
      const receiver=window.__vesperMetrics;
      const rows=__ROWS__;
      let calls=0;
      window.__vesperMetrics=function(){
        receiver(JSON.stringify(rows));
        calls++;
        setTimeout(function(){
          if(__CASE__==='narrow bar'){
            document.querySelector('.dockrow').style.width='600px';
            document.querySelector('.bar').style.maxWidth='498px';
            document.querySelector('.bar').scrollLeft=100000;
          }
          if(__CASE__==='palette search'){
            document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',metaKey:true,bubbles:true}));
            const search=document.querySelector('.menu-search');search.value='panic';search.dispatchEvent(new Event('input'));
          }
          if(__CASE__==='onboarding request'){
            const row=document.querySelector('.menu-reading[data-item=\"onboarding-wizard\"]');
            row.querySelector('summary').click();row.querySelector('.menu-action').click();
            document.getElementById('menu-node-id').value='candidate-01';
            Array.from(document.querySelectorAll('.menu-action')).find(b=>b.textContent==='Prepare enrollment request').click();
          }
          if(__CASE__==='before-after fixture'&&calls===1){
            Array.from(document.querySelectorAll('.menu-action')).find(b=>b.textContent==='Before / after').click();
            Array.from(document.querySelectorAll('.menu-action')).find(b=>b.textContent==='Capture baseline').click();
            const row=rows.find(r=>r.id==='memory-headroom');row.data={reclaimable_gib:3};row.at_ms=Date.now();
            window.__vesperMetrics();return;
          }
          if(__CASE__==='before-after fixture'&&calls===2){
            Array.from(document.querySelectorAll('.menu-action')).find(b=>b.textContent==='Compare latest').click();
          }
          const readings=Array.from(document.querySelectorAll('.menu-reading'));
          const slots=Array.from(document.querySelectorAll('.bar .slot'));
          const panel=document.getElementById('menu-panel');
          const bar=document.querySelector('.bar');
          const labels=[];
          if(__CASE__==='hover labels'){
            panel.close();
            slots.forEach(button=>{
              button.dispatchEvent(new Event('pointerenter'));
              const tip=document.getElementById('menu-tooltip');
              labels.push({name:tip.querySelector('strong').textContent,what:tip.querySelector('span').textContent,visible:!tip.hidden});
            });
          }
          const data={case:__CASE__,labels:labels,
            slots:slots.length,enabled:slots.every(b=>!b.disabled),
            rows:readings.length,available:readings.filter(r=>r.dataset.available==='true').length,
            values:readings.map(r=>({id:r.dataset.item,value:r.querySelector('.menu-reading-value').textContent,reason:r.querySelector('.menu-reason').textContent})),
            panelOpen:panel.open,localOutput:(document.querySelector('.menu-content .menu-data')||{}).textContent||'',paletteButtons:Array.from(document.querySelectorAll('.menu-palette button')).map(b=>b.textContent),title:document.getElementById('menu-title').textContent,
            bar:{width:bar.getBoundingClientRect().width,scrollWidth:bar.scrollWidth,viewport:innerWidth,scrollLeft:bar.scrollLeft,lastIconRight:slots[slots.length-1].getBoundingClientRect().right,barRight:bar.getBoundingClientRect().right},
            noInjectedImage:!document.querySelector('[data-probe-injection]'),
            mainNames:slots.map(b=>b.getAttribute('aria-label'))};
          document.getElementById('cmdsum').textContent=JSON.stringify(data);
        },100);
      };
    },{once:true});
    </script>'''.replace('__ROWS__',injected).replace('__CASE__',json.dumps(case))
    with tempfile.TemporaryDirectory(prefix='vesper-menu-dom-') as d:
        path=Path(d)/'app/home-macos/chrome/home.html';path.parent.mkdir(parents=True)
        path.write_text(template+'\n'+js)
        proc=subprocess.run([str(REPO/'app/VESPER.app/Contents/MacOS/VESPER'),
                             '--chrome-probe','--probe-menu',view],cwd=d,
                            capture_output=True,text=True,timeout=MAX_PROBE_SECONDS)
        if proc.returncode:
            raise RuntimeError(f'chrome-probe exited {proc.returncode}: {proc.stderr[-500:]}')
        # The binary may print diagnostics before its JSON report.
        objects=[]
        for line in proc.stdout.splitlines():
            try:objects.append(json.loads(line))
            except ValueError:pass
        report=next((o for o in objects if isinstance(o,dict) and 'menu' in o),None)
        if report is None:raise RuntimeError('no ChromeProbe DOM report')
        if not report.get('summary'):raise RuntimeError(case+': DOM audit did not run; opened '+str(report.get('menu',{}).get('title')))
        audit=json.loads(report['summary'])
        assert audit['slots']==17 and audit['enabled'],audit
        if case!='hover labels':assert audit['panelOpen'],audit
        if view=='instruments':assert audit['rows']==51,audit
        assert audit['noInjectedImage'],audit
        return audit


def main():
    ap=argparse.ArgumentParser();ap.add_argument('snapshot',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();rows=json.loads(args.snapshot.read_text())['rows']
    actual=probe(rows,'live snapshot')
    assert actual['available'] > 0, 'live snapshot expired or receiver dropped every producer'
    expired=json.loads(json.dumps(rows))
    for r in expired:
        if r.get('area') and r.get('status')=='available':r['at_ms']=1
    stale=probe(expired,'expired observations')
    assert stale['available']==0,stale
    hostile=json.loads(json.dumps(rows))
    for r in hostile:
        if r.get('id')=='memory-headroom':
            r['value']='<img data-probe-injection src=x onerror=alert(1)>'
            # This is a deliberately synthetic rendering fixture, never a reading.
            import time
            r['at_ms']=int(time.time()*1000)
    safe=probe(hostile,'markup injection fixture')
    target=next(r for r in safe['values'] if r['id']=='memory-headroom')
    assert target['value']=='<img data-probe-injection src=x onerror=alert(1)>',target
    main=probe(rows,'main destination',view='action-outbox')
    assert main['title']=='Action outbox' and main['rows']==1,main
    labels=probe(rows,'hover labels')
    catalogue=json.loads((REPO/'tools/menu_catalogue.json').read_text())
    assert [(x['name'],x['what']) for x in labels['labels']]==[(x['name'],x['what']) for x in catalogue if x['area']=='main'],labels
    assert all(x['visible'] for x in labels['labels']),labels
    narrow=probe(rows,'narrow bar')
    assert narrow['bar']['scrollWidth']>narrow['bar']['width'],narrow
    assert narrow['bar']['scrollLeft']>0 and narrow['bar']['lastIconRight']<=narrow['bar']['barRight'],narrow
    palette=probe(rows,'palette search',view='command-palette')
    assert palette['paletteButtons']==['Panic revoke'],palette
    onboarding=probe(rows,'onboarding request',view='onboarding-wizard')
    request=json.loads(onboarding['localOutput'])
    assert request['node_id']=='candidate-01' and request['status']=='NOT_ENROLLED',request
    baseline=json.loads(json.dumps(rows))
    for row in baseline:
        if row.get('id')=='memory-headroom':
            row['status']='available';row['at_ms']=int(time.time()*1000)-1000;row['data']={'reclaimable_gib':2}
    comparison=probe(baseline,'before-after fixture',view='before-after')
    comparisons=json.loads(comparison['localOutput'])
    assert any(r['field']=='reclaimable_gib' and r['delta']==1 for r in comparisons),comparisons
    args.out.write_text(json.dumps(dict(live=actual,expired=stale,injection=safe,main=main,labels=labels,narrow=narrow,
                                        palette=palette,onboarding=onboarding,comparison=comparison),indent=2))
    print(f"PASS: native DOM: {actual['slots']} enabled main icons; {actual['rows']} instrument rows; {actual['available']} fresh instrument readings")
    print('PASS: expiry; injection; main destination; all 17 hover labels; narrow-bar scroll; palette search; enrollment request; before/after delta')
    return 0

if __name__=='__main__':raise SystemExit(main())
