// S04: a remote Smart Canvas revision must not resurrect deleted nodes or
// silently overwrite unsaved local work. Run: node --test tests/test_smart_canvas_remote_merge.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../static/js/smart-canvas.js'), 'utf8');
const start = source.indexOf('function applyMergedServerCanvas(');
const end = source.indexOf('async function mergeReloadCanvasNow(', start);
assert.ok(start >= 0 && end > start, 'expected actual remote merge handler');
const handler = source.slice(start, end);

function fixture(options={}){
    const events = [];
    const ctx = {
        canvasId:'smart-one',
        canvas:{id:'smart-one',revision:4,updated_at:100,title:'Local',connections:[],settings:{}},
        nodes:[{id:'deleted-remotely',type:'smart-image'}],
        settings:{quality:'local'}, canvasDefaultSmartSettings:{},
        smartCanvasLocalDirty:Boolean(options.dirty),
        canvasSyncInFlight:Boolean(options.inFlight),
        smartCanvasConflictPending:false,
        saveCanvas:{queued:Boolean(options.queued)},
        saveTimer:1,
        smartCanvasAnyRunning:()=>Boolean(options.running),
        normalizeLegacySmartNode:x=>x,
        persistSmartConflictDraft(){events.push('draft');return {canvas_id:'smart-one'};},
        clearTimeout(){events.push('cancel-save');},
        window:{CanvasConflictRecovery:{show(){events.push('recovery');}}},
        toast(){events.push('toast');},
        document:{getElementById:()=>null},
        render(){events.push('render');},
        scheduleConnectionLayerRefresh(){},
        resumeSmartPendingTasks(){},
        resumeJimengPendingNodes(){},
        cloneSmartSettings:x=>({...x})
    };
    const apply = new Function('ctx', 'with(ctx){' + handler + 'return applyMergedServerCanvas;}')(ctx);
    return {ctx,events,apply};
}
function remote(revision=5, nodes=[], extra={}){
    return {id:'smart-one',revision,updated_at:200,title:'Remote',
        nodes,connections:[],settings:{quality:'remote'},...extra};
}

test('clean remote deletion removes the deleted node and advances the CAS revision',()=>{
    const x=fixture();
    assert.equal(x.apply(remote()),true);
    assert.deepEqual(x.ctx.nodes,[]);
    assert.equal(x.ctx.canvas.revision,5);
    assert.equal(x.ctx.canvas.title,'Remote');
    assert.equal(x.ctx.settings.quality,'remote');
    assert.equal(x.ctx.smartCanvasConflictPending,false);
});
test('unsaved local edit is preserved as recovery draft instead of auto-merged',()=>{
    const x=fixture({dirty:true});
    assert.equal(x.apply(remote()),false);
    assert.equal(x.ctx.canvas.revision,4);
    assert.deepEqual(x.ctx.nodes.map(n=>n.id),['deleted-remotely']);
    assert.equal(x.ctx.smartCanvasConflictPending,true);
    assert.ok(x.events.includes('draft'));
    assert.ok(x.events.includes('recovery'));
});
test('queued or in-flight save also blocks remote auto-merge',()=>{
    for(const option of [{queued:true},{inFlight:true},{running:true}]){
        const x=fixture(option);
        assert.equal(x.apply(remote()),false);
        assert.equal(x.ctx.canvas.revision,4);
        assert.equal(x.ctx.smartCanvasConflictPending,true);
        assert.ok(x.events.includes('recovery'));
    }
});
test('late stale GET cannot roll back newer local revision',()=>{
    const x=fixture();
    assert.equal(x.apply(remote(3,[])),false);
    assert.equal(x.ctx.canvas.revision,4);
    assert.deepEqual(x.ctx.nodes.map(n=>n.id),['deleted-remotely']);
});
test('touch-only updated_at change does not merge nodes or change revision',()=>{
    const x=fixture();
    assert.equal(x.apply(remote(4,[])),false);
    assert.equal(x.ctx.canvas.updated_at,200);
    assert.equal(x.ctx.canvas.revision,4);
    assert.deepEqual(x.ctx.nodes.map(n=>n.id),['deleted-remotely']);
});
test('remote response for a different canvas is ignored',()=>{
    const x=fixture();
    assert.equal(x.apply(remote(5,[],{id:'another'})),false);
    assert.equal(x.ctx.canvas.revision,4);
    assert.deepEqual(x.ctx.nodes.map(n=>n.id),['deleted-remotely']);
});
