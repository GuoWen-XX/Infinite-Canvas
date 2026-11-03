// S04: metadata edits must remain recoverable when the request never reaches
// the server or returns 5xx. Run: node --test tests/test_canvas_meta_transport.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function extract(pathname, startMarker, endMarker) {
    const source = fs.readFileSync(path.join(__dirname, '..', pathname), 'utf8');
    const start = source.indexOf(startMarker);
    const end = source.indexOf(endMarker, start);
    assert.ok(start >= 0 && end > start, 'missing actual metadata handler in ' + pathname);
    return source.slice(start, end);
}
const listSource = extract('static/js/canvas-list.js',
    'async function persistMeta(', '/* ===== Delete canvas');
const classicSource = extract('static/js/canvas.js',
    'async function patchCanvasMeta(', 'function togglePinCanvas(');

function fixture(kind, response, storageBlocked=false) {
    const saved = [], shown = [], statuses = [], store = {};
    const record = {id:'canvas-one', revision:3, title:'Original'};
    const scope = {
        canvases:[{...record}], canvas:{...record},
        localStorage:{
            getItem(key){return store[key] ?? null;},
            setItem(key, raw){
                if(storageBlocked) throw new Error('storage unavailable');
                store[key] = raw; saved.push({key, value:JSON.parse(raw)});
            }
        },
        window:{CanvasConflictRecovery:{showMetadata(details){shown.push(details);}}},
        fetch:response,
        renderBoard(){}, renderCanvasList(){}, sortCanvasListByUpdated(){},
        setStatus(status){statuses.push(status);},
        L:x=>x, tr:x=>x,
        loadCanvasList:async()=>{}, updateCanvasListRecord(){},
        console:{error(){}}
    };
    const isClassic = kind === 'classic';
    const source = isClassic ? classicSource : listSource;
    const handler = isClassic ? 'patchCanvasMeta' : 'persistMeta';
    const apply = new Function('scope', 'with(scope){' + source + 'return ' + handler + ';}')(scope);
    return {apply:(patch={title:'Offline rename'})=>apply('canvas-one',patch), saved, shown, statuses, store};
}
for (const kind of ['classic','list']) {
    test(kind + ' preserves failed network metadata patch', async()=>{
        const x = fixture(kind, ()=>Promise.reject(new Error('network offline')));
        await x.apply();
        assert.equal(x.saved.length,1);
        assert.equal(x.saved[0].key,'canvas_meta_conflict_canvas-one');
        assert.deepEqual(x.saved[0].value.patch,{title:'Offline rename'});
        assert.equal(x.shown.length,1);
        assert.deepEqual(x.shown[0],{id:'canvas-one',patch:{title:'Offline rename'}});
    });
    test(kind + ' preserves server 503 metadata patch', async()=>{
        const x = fixture(kind, async()=>({ok:false,status:503}));
        await x.apply();
        assert.equal(x.saved.length,1);
        assert.equal(x.shown.length,1);
    });
    test(kind + ' successful metadata save does not create a false conflict draft', async()=>{
        const x = fixture(kind, async()=>({
            ok:true,status:200,json:async()=>({canvas:{id:'canvas-one',revision:4}})
        }));
        await x.apply();
        assert.equal(x.saved.length,0);
        assert.equal(x.shown.length,0);
    });
}

for(const kind of ['classic','list']){
    test(kind + ' retains two separate failed metadata fields', async()=>{
        const x = fixture(kind, ()=>Promise.reject(new Error('offline')));
        await x.apply({title:'Unsent title'});
        await x.apply({icon:'unsent-icon'});
        const expected = {title:'Unsent title',icon:'unsent-icon'};
        assert.deepEqual(JSON.parse(x.store['canvas_meta_conflict_canvas-one']).patch,expected);
        assert.deepEqual(x.shown.at(-1).patch,expected);
    });
    test(kind + ' latest failed value wins for the same field', async()=>{
        const x = fixture(kind, ()=>Promise.reject(new Error('offline')));
        await x.apply({title:'First'});
        await x.apply({title:'Second'});
        assert.deepEqual(JSON.parse(x.store['canvas_meta_conflict_canvas-one']).patch,{title:'Second'});
    });
    test(kind + ' warns when browser storage cannot persist recovery', async()=>{
        const x = fixture(kind, ()=>Promise.reject(new Error('offline')),true);
        await x.apply({title:'Unstored'});
        assert.equal(x.shown.at(-1).persistenceError,true);
        assert.deepEqual(x.shown.at(-1).patch,{title:'Unstored'});
    });
}
