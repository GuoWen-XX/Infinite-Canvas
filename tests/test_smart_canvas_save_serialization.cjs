// S04: offline regression for Smart Canvas concurrent saves and recoverable drafts.
// Run from a full checkout: node --test tests/test_smart_canvas_save_serialization.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/smart-canvas.js'), 'utf8');
const start = source.indexOf('function persistSmartConflictDraft(');
const end = source.indexOf('function imageMetaFromNode(', start);
assert.ok(start >= 0 && end > start, 'expected real Smart Canvas save functions');
const handlers = source.slice(start, end);

function fixture(){
    const calls = [], pending = [], drafts = [], timers = [], panels = [], toasts = [];
    const ctx = {
        canvasId:'smart-one',
        canvas:{id:'smart-one',title:'Smart',revision:4,updated_at:100,nodes:[],settings:{}},
        nodes:[{id:'old'}], viewport:{x:0,y:0,scale:1}, settings:{},
        initialSmartSettings:{}, canvasDefaultSmartSettings:{},
        smartClientId:'offline-test', smartCanvasConflictPending:false,
        canvasSyncInFlight:false, saveTimer:null,
        savePromptDraftForCurrent(){},
        mediaItemForStorage:x=>x, stripImageGenerationMeta:x=>x,
        settingsForStorage:x=>x,
        canvasForStorage:()=>JSON.parse(JSON.stringify({...ctx.canvas,nodes:ctx.nodes})),
        clearTimeout(){}, setTimeout(fn){timers.push(fn);return 1;},
        localStorage:{setItem(key,value){drafts.push({key,record:JSON.parse(value)});}},
        window:{CanvasConflictRecovery:{show(details){panels.push(details);}}},
        toast(message){toasts.push(message);}, tr:x=>x,
        fetch(url,opts){
            calls.push({url,body:JSON.parse(opts.body)});
            return new Promise(resolve=>pending.push(resolve));
        },
        console:{error(){}}
    };
    const api = new Function('ctx','with(ctx){' + handlers + ';return {saveCanvas,scheduleSave};}')(ctx);
    return {ctx,calls,pending,drafts,timers,panels,toasts,...api};
}
function response(revision,status=200){
    return {ok:status===200,status,json:async()=>({canvas:{id:'smart-one',revision,updated_at:100+revision}})};
}
test('two overlapping Smart Canvas saves are serialized and queued CAS uses acknowledged revision',async()=>{
    const x=fixture();
    const first=x.saveCanvas();
    x.ctx.nodes=[{id:'newer'}];
    x.scheduleSave();
    await x.saveCanvas();
    assert.equal(x.calls.length,1,'no second PUT while first is pending');
    x.pending[0](response(5));
    await first;
    assert.equal(x.timers.length,1,'queued edits must be retried');
    const second=x.timers.pop()();
    assert.equal(x.calls.length,2);
    assert.equal(x.calls[1].body.base_revision,5);
    assert.equal(x.calls[1].body.nodes[0].id,'newer');
    x.pending[1](response(6));
    await second;
    assert.equal(x.ctx.canvas.revision,6);
});
test('409 conflict draft captures edits made during in-flight save, not stale request snapshot',async()=>{
    const x=fixture();
    const first=x.saveCanvas();
    x.ctx.nodes=[{id:'edited-during-request'}];
    x.pending[0](response(9,409));
    await first;
    assert.equal(x.ctx.smartCanvasConflictPending,true);
    assert.equal(x.drafts[0].record.canvas.nodes[0].id,'edited-during-request');
    assert.equal(x.panels.length,1);
});
test('404 deleted canvas preserves local Smart Canvas draft',async()=>{
    const x=fixture();
    const first=x.saveCanvas();
    x.pending[0](response(0,404));
    await first;
    assert.equal(x.ctx.smartCanvasConflictPending,true);
    assert.equal(x.drafts.length,1);
    assert.equal(x.panels[0].kind,'smart');
});
test('response for a previous canvas does not mutate newly opened canvas',async()=>{
    const x=fixture();
    const first=x.saveCanvas();
    x.ctx.canvasId='other';
    x.ctx.canvas={id:'other',revision:1,updated_at:20};
    x.pending[0](response(5));
    await first;
    assert.equal(x.ctx.canvas.revision,1);
});
test('transport failure leaves a local recovery draft',async()=>{
    const x=fixture();
    const first=x.saveCanvas();
    x.pending[0]({ok:false,status:503});
    await first;
    assert.equal(x.drafts.length,1);
    assert.equal(x.ctx.smartCanvasConflictPending,false,'transient failure should permit retry');
});
