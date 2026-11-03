// S04: two independent classic editors plus the real conflict recovery helper.
// This mock transport never uses a network, real canvas, or API key.
// Run in a checkout: node --test tests/test_canvas_two_tab_conflict.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const canvasSource=fs.readFileSync(path.join(__dirname,'../static/js/canvas.js'),'utf8');
const recoverySource=fs.readFileSync(path.join(__dirname,'../static/js/canvas-conflict-recovery.js'),'utf8');
function extract(start,end){
    const i=canvasSource.indexOf(start),j=canvasSource.indexOf(end,i);
    assert.ok(i>=0&&j>i,'Missing real save function');
    return canvasSource.slice(i,j);
}
const actualFns=extract('function captureCanvasConflictDraft(){','async function loadConfig(){');
function mockServer(){
    const records=new Map([['original',{id:'original',title:'Base',icon:'layers',revision:1,updated_at:100,nodes:[],connections:[],viewport:{},logs:[]}]]);
    let next=0;
    const requests=[];
    const request=async(url,opts={})=>{
        requests.push({url,method:opts.method||'GET'});
        const action=opts.method||'GET';
        if(url==='/api/canvases'&&action==='POST'){
            const meta=JSON.parse(opts.body),id='copy'+(++next);
            const record={id,...meta,nodes:[],connections:[],revision:1,updated_at:110};
            records.set(id,record);
            return response({canvas:structuredClone(record)});
        }
        const id=decodeURIComponent(url.split('/')[3]||'');
        const record=records.get(id);
        if(!record)return response({detail:'missing'},404);
        if(action==='PUT'){
            const body=JSON.parse(opts.body);
            if(body.base_revision!==record.revision)return response({detail:{canvas:structuredClone(record)}},409);
            const changed={...record,...body,revision:record.revision+1,updated_at:record.updated_at+1};
            delete changed.base_revision;delete changed.base_updated_at;
            records.set(id,changed);
            return response({canvas:structuredClone(changed)});
        }
        return response({canvas:structuredClone(record)});
    };
    return {records,requests,request};
}
function response(body,status=200){return {status,ok:status>=200&&status<300,json:async()=>body};}
function tab(server,name){
    const saved=new Map(),dialogs=[],statuses=[];
    const original=structuredClone(server.records.get('original'));
    const ctx={
        canvas:original,nodes:[],connections:[],viewport:{x:0,y:0,scale:1},
        applyingRemoteCanvas:false,canvasConflictPending:false,
        savingCanvasNow:false,saveCanvasAgain:false,localCanvasDirty:true,
        lastCanvasUpdatedAt:original.updated_at,CLIENT_ID:name,
        sanitizeConnections(){},serializableCanvasNodes(){return ctx.nodes.map(x=>({...x}));},
        localStorage:{setItem(k,v){saved.set(k,v)},getItem(k){return saved.get(k)||null}},
        window:{CanvasConflictRecovery:{show(value){dialogs.push(value)}}},
        setStatus(value){statuses.push(value)},currentCanvasTime:null,formatCanvasTime(){},loadCanvasList(){},
        setTimeout(){},console:{error(){}},fetch:server.request
    };
    const actions=new Function('ctx','with(ctx){'+actualFns+';return {saveCanvas,captureCanvasConflictDraft};}')(ctx);
    return {ctx,saved,dialogs,statuses,...actions};
}
function recovery(){
    const win={fetch(){throw Error('Explicit mocked fetch must be supplied')},document:null};
    vm.runInNewContext(recoverySource,{window:win});
    return win.CanvasConflictRecovery;
}
test('two tabs: stale save rejected, remote nodes remain intact, draft retained',async()=>{
    const server=mockServer(),a=tab(server,'A'),b=tab(server,'B');
    a.ctx.nodes=[{id:'node-from-A'}];
    b.ctx.nodes=[{id:'node-from-B'}];
    await a.saveCanvas();await b.saveCanvas();
    assert.equal(server.records.get('original').revision,2);
    assert.equal(server.records.get('original').nodes[0].id,'node-from-A');
    assert.equal(b.ctx.canvasConflictPending,true);
    assert.equal(b.ctx.canvas.revision,1,'stale editor must not accept newer CAS token');
    assert.equal(b.dialogs.length,1);
    const draft=JSON.parse(b.saved.get('canvas_conflict_draft_original'));
    assert.equal(draft.nodes[0].id,'node-from-B');
});
test('stale draft can be saved as a new independent canvas without overwriting original',async()=>{
    const server=mockServer(),a=tab(server,'A'),b=tab(server,'B');
    a.ctx.nodes=[{id:'A'}];b.ctx.nodes=[{id:'B'}];
    await a.saveCanvas();await b.saveCanvas();
    const draft=JSON.parse(b.saved.get('canvas_conflict_draft_original'));
    const copy=await recovery().createIndependentCopy(draft,'classic',server.request);
    assert.equal(copy.id,'copy1');
    assert.equal(server.records.get('original').nodes[0].id,'A');
    assert.equal(server.records.get('copy1').nodes[0].id,'B');
    assert.equal(draft.canvas_id,'original');
    assert.equal(b.saved.has('canvas_conflict_draft_original'),true,'do not delete local recovery source');
});
test('reverse ordering: first B wins, second A must preserve its own draft',async()=>{
    const server=mockServer(),a=tab(server,'A'),b=tab(server,'B');
    a.ctx.nodes=[{id:'A'}];b.ctx.nodes=[{id:'B'}];
    await b.saveCanvas();await a.saveCanvas();
    assert.equal(server.records.get('original').nodes[0].id,'B');
    assert.equal(JSON.parse(a.saved.get('canvas_conflict_draft_original')).nodes[0].id,'A');
    assert.equal(a.ctx.canvasConflictPending,true);
});
