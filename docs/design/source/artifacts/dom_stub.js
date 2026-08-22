// Minimal DOM stub — enough to actually execute the page's script and catch
// runtime errors. An instrument's self-report is not evidence; this runs it.
const els = {};
function mkEl(id){
  const e = {
    id, _html:'', _attrs:{}, _children:[], _listeners:{},
    style:{ setProperty(k,v){ this[k]=v; }, removeProperty(){}, backgroundImage:'', display:'' },
    classList:{ toggle(){}, add(){}, remove(){}, contains(){return false} },
    set innerHTML(v){ this._html=v; }, get innerHTML(){ return this._html; },
    set textContent(v){ this._text=v; }, get textContent(){ return this._text||''; },
    setAttribute(k,v){ this._attrs[k]=v; }, getAttribute(k){ return this._attrs[k]??null; },
    addEventListener(t,f){ (this._listeners[t]=this._listeners[t]||[]).push(f); },
    querySelectorAll(sel){ return (this._q||[]); },
    querySelector(){ return null; },
    contains(){ return true; },
    closest(){ return null; },
    getBoundingClientRect(){ return {width:900,height:580,top:0,left:0}; },
    getContext(){ return CTX; },
    get offsetWidth(){return 900}, get offsetHeight(){return 580},
    width:0, height:0,
  };
  return e;
}
const CTX = new Proxy({}, { get(t,k){
  if(k==='setTransform'||k==='clearRect'||k==='beginPath'||k==='arc'||k==='fill'||k==='fillRect') return ()=>{};
  if(k==='canvas') return {width:900,height:580};
  return undefined;
}});
const CTXREAL = {
  setTransform(){}, clearRect(){}, beginPath(){}, arc(){}, fill(){}, fillRect(){},
  globalAlpha:1, globalCompositeOperation:'', fillStyle:''
};
function getEl(id){ if(!els[id]) els[id]=mkEl(id); return els[id]; }
// canvases need the real ctx object (properties get assigned)
const canvasIds = ['fld'];
global.document = {
  documentElement: (()=>{ const d=mkEl('html'); d.style={ setProperty(){}, }; return d; })(),
  getElementById(id){
    const e = getEl(id);
    if(id==='fld') e.getContext = ()=>CTXREAL;
    return e;
  },
  querySelectorAll(sel){
    if(sel === '.tier canvas'){
      return [0,1,2,3].map(i=>{ const c=mkEl('tier'+i);
        c.getContext=()=>CTXREAL; c.getAttribute=k=>k==='data-tier'?['centre','attendant','dispersed','absent'][i]:null;
        return c; });
    }
    return [];
  },
  createElement(){ return mkEl('tmp'); },
  addEventListener(){},
};
global.window = {
  devicePixelRatio:2,
  matchMedia(q){ return {matches:false, addEventListener(){}}; },
  requestAnimationFrame(f){ return 0; },
  getComputedStyle(){ return {getPropertyValue(){ return '#D99A52'; }}; },
  addEventListener(){},
};
global.matchMedia = window.matchMedia;
global.requestAnimationFrame = window.requestAnimationFrame;
global.getComputedStyle = window.getComputedStyle;
global.localStorage = { getItem(){return null}, setItem(){} };
global.ResizeObserver = undefined;
