// S04: execute real canvas.js save/exit functions with offline, deferred HTTP.
// Run against a checked-out branch: node --test tests/test_canvas_save_races.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/canvas.js'), 'utf8');

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
