// S04: exercise exact classic/board deletion handlers, with no network.
// Run from a full checkout: node --test tests/test_canvas_delete_cas.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const classic = fs.readFileSync(path.join(__dirname,'../static/js/canvas.js'),'utf8');
const board = fs.readFileSync(path.join(__dirname,'../static/js/canvas-list.js'),'utf8');

function extract(source,begin,end){
    const start=source.indexOf(begin),stop=source.indexOf(end,start);
    assert.ok(start>=0 && stop>start,'unable to locate actual handler: '+begin);
    return source.slice(start,stop);
}
const classicDelete=extract(classic,'async function deleteCanvas(id, event){','async function restoreCanvas(');
const boardDelete=extract(board,'async function deleteCanvas(id){','/* ===== Trash / recycle bin ===== */');
function testFixture(kind, status=200){
    const calls=[], statuses=[];
    const ctx={
        canvases:[{id:'canvas-one',revision:7}], canvas:null,
        localCanvasDirty:false,savingCanvasNow:false,canvasConflictPending:false,
        pendingDeleteCanvasId:'canvas-one',selected:{clear(){}},
        viewport:{x:0,y:0,scale:1},nodes:[],connections:[],
        tr:s=>s,L:(a)=>a,setStatus:s=>statuses.push(s),
        fetch:async (url,opts)=>{calls.push({url,opts});return {ok:status===200,status};},
        renderCanvasList(){},renderBoard(){},renderProjects(){},refreshTrashCount(){},
        loadCanvasList:async()=>{calls.push({refresh:true});},
        loadAll:async()=>{calls.push({refresh:true});},
        setCanvasMode(){},console:{error(){}},
        captureCanvasConflictDraft(){return {canvas_id:'canvas-one'};},
        window:{CanvasConflictRecovery:{show(){calls.push({recovery:true})}}}
    };
    const code = kind==='classic' ? classicDelete : boardDelete;
    const fn = new Function('ctx','with(ctx){'+code+';return deleteCanvas;}')(ctx);
    return {ctx,calls,statuses,fn};
}
test('classic delete includes observed revision in request',async()=>{
    const x=testFixture('classic');
    await x.fn('canvas-one',null);
    assert.equal(x.calls[0].url,'/api/canvases/canvas-one?base_revision=7');
    assert.equal(x.calls[0].opts.method,'DELETE');
});
test('board delete includes observed revision in request',async()=>{
    const x=testFixture('board');
    await x.fn('canvas-one');
    assert.equal(x.calls[0].url,'/api/canvases/canvas-one?base_revision=7');
    assert.equal(x.calls[0].opts.method,'DELETE');
});
test('stale revision 409 refreshes board without removing canvas',async()=>{
    const x=testFixture('board',409);
    await x.fn('canvas-one');
    assert.equal(x.ctx.canvases.length,1);
    assert.equal(x.calls.filter(c=>c.refresh).length,1);
});
test('stale revision 409 refreshes classic list without removing canvas',async()=>{
    const x=testFixture('classic',409);
    await x.fn('canvas-one',null);
    assert.equal(x.ctx.canvases.length,1);
    assert.equal(x.calls.filter(c=>c.refresh).length,1);
});
test('classic delete refuses unsaved local work',async()=>{
    const x=testFixture('classic');
    x.ctx.canvas={id:'canvas-one',revision:7};
    x.ctx.localCanvasDirty=true;
    await x.fn('canvas-one',null);
    assert.equal(x.calls.some(c=>c.url),false);
    assert.equal(x.calls.some(c=>c.recovery),true);
});
test('missing revision cannot invoke destructive endpoint',async()=>{
    const a=testFixture('classic'),b=testFixture('board');
    delete a.ctx.canvases[0].revision;
    delete b.ctx.canvases[0].revision;
    await a.fn('canvas-one',null);
    await b.fn('canvas-one');
    assert.equal(a.calls.some(c=>c.url),false);
    assert.equal(b.calls.some(c=>c.url),false);
});
