// S04: execute real canvas.js save/exit functions with offline, deferred HTTP.
// Run against a checked-out branch: node --test tests/test_canvas_save_races.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/canvas.js'), 'utf8');
const smartSource = fs.readFileSync(path.join(__dirname, '../static/js/smart-canvas.js'), 'utf8');

function extract(name, until) {
    const start = source.indexOf('async function ' + name + '(){');
    const end = source.indexOf(until, start);
    assert.ok(start !== -1 && end > start, 'expected actual canvas.js function: ' + name);
    return source.slice(start, end);
}
const saveSource = extract('saveCanvas', 'async function loadConfig(){');
const leaveSource = extract('returnToCanvasManager', 'function requestDeleteCanvas(');
function sandbox() {
    let answer;
    let scheduled;
    const ctx = {
        canvas:{id:'original',title:'Old',icon:'layers',revision:3,updated_at:100,logs:[]},
        applyingRemoteCanvas:false,canvasConflictPending:false,savingCanvasNow:false,
        saveCanvasAgain:false,localCanvasDirty:true,lastCanvasUpdatedAt:100,
        connections:[],viewport:{x:0,y:0,scale:1},CLIENT_ID:'offline-test',
        sanitizeConnections(){},serializableCanvasNodes(){return [{id:'node-one'}];},
        setStatus(){},loadCanvasList(){},currentCanvasTime:null,formatCanvasTime(){},
        setTimeout(fn){scheduled=fn;},clearTimeout(){},saveTimer:null,
        console:{error(){}},window:{CanvasConflictRecovery:{show(){}}},
        fetch(){return new Promise(resolve => {answer=resolve;});},
        captureCanvasConflictDraft(){return {canvas_id:ctx.canvas.id};}
    };
    const save = new Function('scope','with(scope){' + saveSource + ' return saveCanvas;}')(ctx);
    const leave = new Function('scope','with(scope){' + leaveSource + ' return returnToCanvasManager;}')(ctx);
    return {ctx,save,leave,reply(value){answer(value);},scheduled(){return scheduled;}};
}
function response(canvas,status=200) {
    return {ok:status >= 200 && status < 300,status,json:async()=>({canvas})};
}
test('edit title and icon while PUT is pending: response must not erase newer edits', async()=>{
    const x=sandbox();
    const pending=x.save();
    x.ctx.canvas.title='Newer local title';
    x.ctx.canvas.icon='star';
    x.ctx.saveCanvasAgain=true;
    x.reply(response({id:'original',title:'Old',icon:'layers',revision:4,updated_at:110}));
    await pending;
    assert.equal(x.ctx.canvas.title,'Newer local title');
    assert.equal(x.ctx.canvas.icon,'star');
    assert.equal(x.ctx.canvas.revision,4);
    assert.equal(typeof x.scheduled(),'function','must schedule another CAS save');
});
test('response from previous canvas cannot resurrect previous canvas after navigation', async()=>{
    const x=sandbox();
    const pending=x.save();
    x.ctx.canvas={id:'other',title:'Other',revision:0};
    x.reply(response({id:'original',title:'Old',revision:4}));
    await pending;
    assert.equal(x.ctx.canvas.id,'other');
});
test('do not leave an unsaved canvas while a save is in flight', async()=>{
    const x=sandbox();
    x.ctx.savingCanvasNow=true;
    await x.leave();
    assert.equal(x.ctx.canvas.id,'original');
});
test('a 409 cannot advance the base token and overwrite the remote canvas', async()=>{
    const x=sandbox();
    let showed=false;
    x.ctx.window.CanvasConflictRecovery.show=()=>{showed=true;};
    const pending=x.save();
    x.reply(response({id:'original',revision:6},409));
    await pending;
    assert.equal(x.ctx.canvas.revision,3);
    assert.equal(x.ctx.canvasConflictPending,true);
    assert.equal(x.ctx.localCanvasDirty,true);
    assert.equal(showed,true);
});

test('classic editor opens recovery panel if canvas was deleted remotely',async()=>{
    const x=sandbox();
    let shown=false;
    x.ctx.window.CanvasConflictRecovery.show=()=>{shown=true;};
    const pending=x.save();
    x.reply(response(null,404));
    await pending;
    assert.equal(x.ctx.canvasConflictPending,true);
    assert.equal(x.ctx.localCanvasDirty,true);
    assert.equal(x.ctx.canvas.revision,3);
    assert.equal(shown,true);
});
function smartSandbox(status){
    const begin=smartSource.indexOf('async function saveCanvas(){');
    const end=smartSource.indexOf('function imageMetaFromNode(',begin);
    assert.ok(begin>=0 && end>begin,'missing real smart-canvas save function');
    const seen=[];
    const ctx={
        canvasId:'smart-canvas-one',canvas:{id:'smart-canvas-one',title:'Smart',revision:3,updated_at:100},
        smartCanvasConflictPending:false,canvasSyncInFlight:false,saveTimer:null,
        savePromptDraftForCurrent(){},nodes:[],viewport:{x:0,y:0,scale:1},
        settingsForStorage:s=>s||{},canvasDefaultSmartSettings:{},initialSmartSettings:{},
        canvasForStorage(){return {title:'Smart',icon:'sparkles',nodes:[],connections:[],viewport:ctx.viewport,logs:[],settings:{},updated_at:100};},
        mediaItemForStorage:v=>v,stripImageGenerationMeta:v=>v,
        fetch:async()=>({ok:false,status}),clearTimeout(){},
        persistSmartConflictDraft(snapshot){return {canvas_id:ctx.canvasId,canvas:snapshot};},
        window:{CanvasConflictRecovery:{show:details=>seen.push(details)}},
        toast:msg=>seen.push(msg),tr:x=>x,smartClientId:'offline-test',
        console:{error(){}}
    };
    const save=new Function('scope','with(scope){'+smartSource.slice(begin,end)+' return saveCanvas;}')(ctx);
    return {ctx,seen,save};
}
test('smart editor preserves a recoverable draft after remote 404 deletion',async()=>{
    const x=smartSandbox(404);
    await x.save();
    assert.equal(x.ctx.smartCanvasConflictPending,true);
    assert.equal(x.ctx.canvas.revision,3);
    assert.equal(typeof x.seen[0],'object');
    assert.equal(x.seen[0].kind,'smart');
});
test('smart editor still preserves a recoverable draft on stale 409',async()=>{
    const x=smartSandbox(409);
    await x.save();
    assert.equal(x.ctx.smartCanvasConflictPending,true);
    assert.equal(typeof x.seen[0],'object');
});

test('smart saves serialize pending edits and use the newly acknowledged revision',async()=>{
    const begin=smartSource.indexOf('function scheduleSave(){');
    const end=smartSource.indexOf('function imageMetaFromNode(',begin);
    assert.ok(begin>=0 && end>begin,'real smart save functions missing');
    const requests=[],pending=[],timers=[];
    const ctx={
        canvasId:'smart',canvas:{id:'smart',revision:5,updated_at:100,title:'Title'},
        smartCanvasConflictPending:false,canvasSyncInFlight:false,saveTimer:null,
        savePromptDraftForCurrent(){},nodes:[],viewport:{x:0,y:0,scale:1},
        settingsForStorage:x=>x||{},canvasDefaultSmartSettings:{},initialSmartSettings:{},
        canvasForStorage(){return {title:ctx.canvas.title,icon:'sparkles',updated_at:ctx.canvas.updated_at,settings:{},nodes:[],viewport:{}};},
        fetch:async(url,opts)=>{
            requests.push(JSON.parse(opts.body).base_revision);
            return new Promise(resolve=>pending.push(resolve));
        },
        clearTimeout(){},setTimeout(callback){timers.push(callback);return 1;},
        window:{CanvasConflictRecovery:{show(){}}},toast(){},tr:x=>x,
        smartClientId:'offline',console:{error(){}}
    };
    const api=new Function('scope','with(scope){'+smartSource.slice(begin,end)+' return {save:saveCanvas,schedule:scheduleSave};}')(ctx);
    const first=api.save();
    ctx.canvas.title='New title while saving';
    api.schedule();
    assert.deepEqual(requests,[5],'must not start second PUT with stale revision');
    pending.shift()({ok:true,status:200,json:async()=>({canvas:{revision:6,updated_at:101}})});
    await first;
    assert.equal(timers.length,1,'must enqueue a follow-up save');
    const second=timers.shift()();
    assert.deepEqual(requests,[5,6],'second PUT must use acknowledged revision');
    pending.shift()({ok:true,status:200,json:async()=>({canvas:{revision:7,updated_at:102}})});
    await second;
    assert.equal(ctx.canvas.title,'New title while saving');
    assert.equal(ctx.canvas.revision,7);
});

function switchingSandbox(){
    const start=source.indexOf('function preserveDraftBeforeCanvasSwitch(){');
    const stop=source.indexOf('function applyRemoteCanvasData(',start);
    assert.ok(start>=0 && stop>start,'missing actual canvas-switch guard');
    let release;
    const events=[];
    const ctx={
        canvas:{id:'original',title:'Unsaved'},localCanvasDirty:false,
        savingCanvasNow:false,saveCanvasAgain:false,canvasConflictPending:false,
        captureCanvasConflictDraft(){events.push('backup');return {canvas_id:'original'};},
        window:{CanvasConflictRecovery:{show(){events.push('shown');}}},
        setStatus(){},tr:x=>x,console:{error(){}},
        fetch(){events.push('fetch');return new Promise(resolve=>{release=resolve;});},
        resetCascadeRuntimeState(){events.push('reset');},
        canvasListUrlForProject(){return '/list';},requestedCanvasListProject(){},
        rememberedCanvasListProject(){}
    };
    const open=new Function('scope','with(scope){'+source.slice(start,stop)+'return openCanvas;}')(ctx);
    return {ctx,events,open,reply(result){release(result);}};
}
test('switching canvas with unsaved work does not start a destructive GET',async()=>{
    const x=switchingSandbox();
    x.ctx.localCanvasDirty=true;
    await x.open('other');
    assert.equal(x.events.includes('fetch'),false);
    assert.equal(x.ctx.canvas.id,'original');
    assert.equal(x.events.includes('backup'),true);
});
test('late GET response cannot discard edits made while loading another canvas',async()=>{
    const x=switchingSandbox();
    const pending=x.open('other');
    x.ctx.localCanvasDirty=true;
    x.reply({ok:true,json:async()=>({canvas:{id:'other'}})});
    await pending;
    assert.equal(x.ctx.canvas.id,'original');
    assert.equal(x.events.includes('reset'),false);
    assert.equal(x.events.includes('shown'),true);
});
