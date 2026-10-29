const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync('static/js/canvas.js', 'utf8');
const fn = src.slice(src.indexOf('async function saveCanvas(){'), src.indexOf('async function loadConfig(){'));
const queue = [], requests = [];
let server = {id:'demo', title:'Demo', updated_at:2, nodes:[{id:'remote-added'}]};
const ctx = {
  canvas:{id:'demo', title:'Demo', updated_at:1}, applyingRemoteCanvas:false,
  savingCanvasNow:false, saveCanvasAgain:false, localCanvasDirty:true,
  lastCanvasUpdatedAt:1, connections:[], viewport:{}, CLIENT_ID:'local',
  currentCanvasTime:null, console,
  sanitizeConnections(){}, serializableCanvasNodes(){return [{id:'local-added'}]},
  setStatus(){}, loadCanvasList(){}, setTimeout(fn){queue.push(fn)},
  applyRemoteCanvasData(){throw Error('Unexpected remote merge')},
  async fetch(url, options){
    const p = JSON.parse(options.body); requests.push(p);
    if(p.base_updated_at < server.updated_at) return {status:409,ok:false,json:async()=>({detail:{canvas:server,updated_at:server.updated_at}})};
    server = {...p, updated_at:3};
    return {status:200,ok:true,json:async()=>({canvas:server})};
  }
};
vm.createContext(ctx); vm.runInContext(fn,ctx);
(async()=>{
  await ctx.saveCanvas();
  assert.equal(queue.length,1);
  await queue.shift()();
  assert.deepEqual(requests.map(p=>p.base_updated_at),[1,2]);
  assert.equal(server.nodes.some(n=>n.id==='remote-added'),false);
  console.log(JSON.stringify({finding:'R1',requests:requests.map(p=>({base:p.base_updated_at,nodes:p.nodes})),final_nodes:server.nodes,confirmed:true},null,2));
})().catch(e=>{console.error(e);process.exitCode=1});

