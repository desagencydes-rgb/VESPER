// Minimal DOM stub: enough to run the page's load path and catch a throw.
const made = {};
function el(id){
  if (made[id]) return made[id];
  const e = { id, _html:"", _text:"", className:"", style:{}, disabled:false,
    set innerHTML(v){ this._html=v; }, get innerHTML(){ return this._html; },
    set textContent(v){ this._text=v; }, get textContent(){ return this._text; },
    setAttribute(){}, getAttribute(){ return null; }, addEventListener(){},
    querySelectorAll(){ return []; }, appendChild(){}, getContext(){ return {
      drawImage(){}, getImageData(){ return { data:new Uint8ClampedArray(64*48*4) }; } }; } };
  made[id]=e; return e;
}
global.window = { isSecureContext:true, self:{}, top:{} };
global.window.self = global.window; global.window.top = {}; // simulate iframe
global.location = { protocol:"https:" };
global.document = {
  getElementById: el,
  createElement: (t)=> el("_created_"+t+"_"+Math.round(1e6)),
  querySelectorAll: ()=>[],
  featurePolicy: { allowsFeature:(f)=> f==="camera" ? true : false }
};
const NAV = {
  userAgent:"stub",
  permissions:{ query:()=> Promise.resolve({ state:"prompt", onchange:null }) },
  mediaDevices:{
    getUserMedia:()=> Promise.reject(Object.assign(new Error("stub"),{name:"NotFoundError"})),
    enumerateDevices:()=> Promise.resolve([
      { kind:"videoinput", deviceId:"abc123", label:"Front Camera" },
      { kind:"videoinput", deviceId:"def456", label:"Back Camera" },
      { kind:"audioinput", deviceId:"zzz", label:"Mic" }])
  },
  clipboard:{ writeText:()=>Promise.resolve() }
};
// Node ships its own read-only ; a plain assignment is silently
// ignored, which is how the first harness run "proved" the page had no
// getUserMedia when the page was fine and the harness was wrong.
Object.defineProperty(globalThis, 'navigator', { value: NAV, configurable: true, writable: true });
global.HTMLVideoElement = { prototype:{ requestVideoFrameCallback:function(){} } };
global.performance = { now:()=>Date.now() };
global.requestAnimationFrame = ()=>0; global.cancelAnimationFrame = ()=>{};
global.setInterval = ()=>0; global.clearInterval = ()=>{};  // real setTimeout kept: the harness needs it
