// S04: metadata-only edits must not send a full-canvas PUT.
// Run: node --test tests/test_canvas_metadata_routes.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../static/js/canvas.js'),'utf8');

function extract(name, after){
    const begin=source.indexOf('async function ' + name + '(');
    const end=source.indexOf(after,begin);
    assert.ok(begin>=0 && end>begin,'missing function '+name);
    return source.slice(begin,end);
}
const iconSource=extract('setCanvasIcon','function startTitleEdit(');
const titleSource=extract('setCanvasTitle','async function openCanvas(');
function fixture(){
    const calls=[];
    const ctx={
        canvas:{id:'one',title:'Old',icon:'layers',revision:3},
        currentCanvasTitle:{textContent:'Old'},
        closeCanvasMetaPopover(){calls.push('close');},
        async patchCanvasMeta(id,patch){
            calls.push({id,patch});
            Object.assign(ctx.canvas,patch);
        },
        fetch(){throw Error('A metadata edit must not issue an unversioned full PUT');}
    };
    return {
        ctx,calls,
        setIcon:new Function('ctx','with(ctx){'+iconSource+' return setCanvasIcon;}')(ctx),
        setTitle:new Function('ctx','with(ctx){'+titleSource+' return setCanvasTitle;}')(ctx)
    };
}
test('icon edit uses revision-aware metadata helper, not whole-canvas PUT',async()=>{
    const x=fixture();
    let prevented=false,stopped=false;
    await x.setIcon('one','star',{preventDefault(){prevented=true},stopPropagation(){stopped=true}});
    assert.equal(prevented,true);
    assert.equal(stopped,true);
    assert.deepEqual(x.calls[1],{id:'one',patch:{icon:'star'}});
    assert.equal(x.ctx.canvas.icon,'star');
});
test('title rename uses metadata CAS and preserves other fields',async()=>{
    const x=fixture();
    await x.setTitle('one','Concurrent rename');
    assert.deepEqual(x.calls[0],{id:'one',patch:{title:'Concurrent rename'}});
    assert.equal(x.ctx.canvas.revision,3);
    assert.equal(x.ctx.canvas.icon,'layers');
    assert.equal(x.ctx.currentCanvasTitle.textContent,'Concurrent rename');
});
test('empty icon falls back to a safe icon without modifying nodes',async()=>{
    const x=fixture();
    x.ctx.canvas.nodes=[{id:'keep'}];
    await x.setIcon('one','',null);
    assert.deepEqual(x.calls[1],{id:'one',patch:{icon:'layers'}});
    assert.equal(x.ctx.canvas.nodes[0].id,'keep');
});
