// S04: a stale browser tab must not restore a changed trash entry.
// Run from checkout: node --test tests/test_canvas_restore_cas.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function extract(filename, begin, end) {
    const content=fs.readFileSync(path.join(__dirname,'../static/js',filename),'utf8');
    const start=content.indexOf(begin);
    const stop=content.indexOf(end,start);
    assert.ok(start>=0 && stop>start,'Expected actual function '+begin);
    return content.slice(start,stop);
}
const classic=extract('canvas.js','async function restoreCanvas(id, event){','async function purgeCanvas(');
const board=extract('canvas-list.js','async function restoreCanvas(id){','async function purgeCanvas(');

function fixture(kind, status=200, revision=7) {
    const calls=[],statuses=[];
    const ctx={
        deletedCanvases:[revision==null?{id:'old'}:{id:'old',revision}],
        pendingPurgeCanvasId:'old',
        setStatus:value=>statuses.push(value),tr:value=>value,L:(zh,en)=>en,
        fetch:async(url,opts)=>{
            calls.push({url,opts});
            return {status,ok:status>=200&&status<300};
        },
        loadAll:async()=>{calls.push({operation:'loadAll'})},
        loadTrash:async()=>{calls.push({operation:'loadTrash'})},
        loadTrashList:async()=>{calls.push({operation:'loadTrashList'})},
        loadCanvasList:async()=>{calls.push({operation:'loadCanvasList'})},
        renderTrash(){},console:{error(e){throw e}}
    };
    const code=kind==='classic'?classic:board;
    return {ctx,calls,statuses,restore:new Function('ctx','with(ctx){'+code+' return restoreCanvas;}')(ctx)};
}
for(const kind of ['classic','board']){
    test(kind+' restore sends observed revision, never unversioned POST',async()=>{
        const fx=fixture(kind);
        await fx.restore('old',{preventDefault(){},stopPropagation(){}});
        assert.equal(fx.calls[0].url,'/api/canvases/old/restore?base_revision=7');
        assert.equal(fx.calls[0].opts.method,'POST');
        assert.equal(fx.ctx.deletedCanvases.length,0);
    });
    test(kind+' rejects missing revision before network call',async()=>{
        const fx=fixture(kind,200,null);
        await fx.restore('old',{preventDefault(){},stopPropagation(){}});
        assert.equal(fx.calls.some(x=>x.url),false);
        assert.equal(fx.ctx.deletedCanvases.length,1);
    });
    test(kind+' HTTP 409 refreshes trash and keeps entry',async()=>{
        const fx=fixture(kind,409);
        await fx.restore('old',{preventDefault(){},stopPropagation(){}});
        assert.equal(fx.calls[0].url,'/api/canvases/old/restore?base_revision=7');
        assert.equal(fx.ctx.deletedCanvases.length,1);
        assert.ok(fx.calls.some(x=>x.operation==='loadTrash' || x.operation==='loadTrashList'));
    });
}
