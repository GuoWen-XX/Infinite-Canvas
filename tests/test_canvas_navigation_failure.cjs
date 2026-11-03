'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'static/js/canvas.js'), 'utf8');
const backHandler = source.match(/backToManagerBtn\?\.addEventListener\('click', \(\) => \{[\s\S]*?\n\}\);/)?.[0];
const unloadHandler = source.match(/window\.addEventListener\('beforeunload', event => \{[\s\S]*?\n\}\);/)?.[0];
const saveHandler = source.slice(source.indexOf('async function saveCanvas(){'), source.indexOf('\nasync function loadConfig(){'));
assert.ok(backHandler && unloadHandler && saveHandler.startsWith('async function saveCanvas(){'));

function simulateBack({dirty=false, saving=false, conflict=false}={}){
    let click;
    let drafts = 0;
    let panels = 0;
    const window = {location:{href:'/static/canvas.html'}, CanvasConflictRecovery:{show(){panels++;}}};
    new Function('backToManagerBtn','window','canvas','savingCanvasNow','localCanvasDirty','canvasConflictPending',
        'captureCanvasConflictDraft','canvasListUrlForProject','requestedCanvasListProject',
        'rememberedCanvasListProject','setStatus',backHandler)(
        {addEventListener(name, handler){assert.equal(name,'click');click=handler;}},
        window,{id:'canvas-1',project:'default'},saving,dirty,conflict,
        ()=>{drafts++;return {canvas_id:'canvas-1',nodes:[{id:'unsaved'}]};},
        ()=>'/static/canvas-list.html',()=>null,()=>null,()=>{});
    click();
    return {href:window.location.href,drafts,panels};
}

test('classic editor back navigation blocks an in-flight save and offers recovery',()=>{
    const actual = simulateBack({saving:true,dirty:true});
    assert.equal(actual.href,'/static/canvas.html');
    assert.equal(actual.drafts,1);
    assert.equal(actual.panels,1);
});

test('classic editor clean navigation still reaches the canvas manager',()=>{
    const actual = simulateBack();
    assert.equal(actual.href,'/static/canvas-list.html');
    assert.equal(actual.drafts,0);
});

test('classic editor network failure preserves a recoverable draft without blind retry',async()=>{
    let drafts=0,panels=0,retries=0;
    const statuses=[];
    const factory = new Function('canvas','fetch','sanitizeConnections','savingCanvasNow','saveCanvasAgain',
        'localCanvasDirty','canvasConflictPending','serializableCanvasNodes','connections','viewport','CLIENT_ID',
        'lastCanvasUpdatedAt','setStatus','captureCanvasConflictDraft','window','setTimeout','loadCanvasList',
        'currentCanvasTime','formatCanvasTime','applyingRemoteCanvas','console',
        saveHandler+'; return {saveCanvas,state:()=>({canvasConflictPending,localCanvasDirty,saveCanvasAgain,savingCanvasNow})};');
    const env = factory(
        {id:'canvas-1',revision:3,title:'edited'},async()=>{throw new Error('offline');},()=>{},
        false,false,true,false,()=>[{id:'unsaved'}],[],{},'client',0,x=>statuses.push(x),
        ()=>{drafts++;return {canvas_id:'canvas-1',nodes:[{id:'unsaved'}]};},
        {CanvasConflictRecovery:{show(){panels++;}}},()=>{retries++;},()=>{},null,()=>{},false,{error(){}});
    await env.saveCanvas();
    assert.equal(drafts,1);
    assert.equal(panels,1);
    assert.equal(retries,0);
    assert.equal(env.state().canvasConflictPending,true);
    assert.equal(env.state().localCanvasDirty,true);
    assert.equal(env.state().savingCanvasNow,false);
    assert.match(statuses.at(-1),/draft preserved/i);
});

test('classic editor beforeunload captures pending edits and warns',()=>{
    let unload,drafts=0;
    const window={addEventListener(name,fn){assert.equal(name,'beforeunload');unload=fn;}};
    new Function('window','canvas','savingCanvasNow','localCanvasDirty','canvasConflictPending',
        'captureCanvasConflictDraft',unloadHandler)(window,{id:'canvas-1'},true,true,false,()=>{drafts++;});
    const event={preventDefault(){this.prevented=true;}};
    unload(event);
    assert.equal(drafts,1);
    assert.equal(event.prevented,true);
    assert.equal(event.returnValue,'');
});
