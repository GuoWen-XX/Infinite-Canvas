// S04: a touch response must not upgrade the CAS revision of an older GET snapshot.
// Offline regression: node --test tests/test_canvas_open_touch_race.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/canvas.js'), 'utf8');
const start = source.indexOf('function preserveDraftBeforeCanvasSwitch(){');
const end = source.indexOf('function applyRemoteCanvasData(', start);
assert.ok(start >= 0 && end > start, 'expected real classic openCanvas function');
const openSource = source.slice(start, end);

function fixture(touchRevision) {
    const gets = [];
    const versions = [
        {id:'canvas-one',kind:'classic',revision:4,updated_at:100,nodes:[{id:'stale'}],connections:[]},
        {id:'canvas-one',kind:'classic',revision:5,updated_at:200,nodes:[{id:'remote-new'}],connections:[]}
    ];
    const ctx = {
        canvas:null,nodes:[],connections:[],viewport:{x:0,y:0,scale:1},
        localCanvasDirty:false,savingCanvasNow:false,saveCanvasAgain:false,canvasConflictPending:false,
        lastCanvasUpdatedAt:0,saveTimer:null,selected:new Set(),
        tr:x=>x,setStatus(){},console:{error(){}},
        window:{CanvasConflictRecovery:{showSaved(){},show(){}},location:{replace(){}}},
        fetch:async url=>{
            gets.push(url);
            const version = versions[Math.min(gets.length-1,versions.length-1)];
            return {ok:true,json:async()=>({canvas:JSON.parse(JSON.stringify(version))})};
        },
        touchCanvasOpened:async()=>({updated_at:101,canvas:{revision:touchRevision}}),
        resetCascadeRuntimeState(){},rememberCanvasListProject(){},
        localViewportForCanvas:(id,view)=>view,resetTransientRunState(){},
        sanitizeConnections(){},pruneMissingComfyWorkflows(){},
        refreshMissingCanvasAssets:async()=>{},setCanvasMode(){},renderCanvasList(){},render(){},
        resumeCanvasImageTasks(){},startCanvasRemotePolling(){},openSmartCanvasPage(){},
        canvasListUrlForProject:()=>'/list',requestedCanvasListProject:()=>'',rememberedCanvasListProject:()=>''
    };
    const open = new Function('ctx','with(ctx){' + openSource + 'return openCanvas;}')(ctx);
    return {ctx,gets,open};
}

test('touch sees newer revision: refetch content before using newer CAS token', async()=>{
    const x=fixture(5);
    await x.open('canvas-one');
    assert.equal(x.gets.length,2,'must refetch when touch observed a newer revision');
    assert.equal(x.ctx.canvas.revision,5);
    assert.deepEqual(x.ctx.nodes.map(n=>n.id),['remote-new']);
    assert.equal(x.ctx.localCanvasDirty,false);
});

test('touch with unchanged revision does not cause an unnecessary refetch', async()=>{
    const x=fixture(4);
    await x.open('canvas-one');
    assert.equal(x.gets.length,1);
    assert.equal(x.ctx.canvas.revision,4);
    assert.deepEqual(x.ctx.nodes.map(n=>n.id),['stale']);
    assert.equal(x.ctx.canvas.updated_at,101);
});
