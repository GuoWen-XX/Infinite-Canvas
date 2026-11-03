// S04: localStorage quota/private-mode failure must be visible, not just logged.
// Run: node --test tests/test_canvas_draft_storage_failure.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const classic=fs.readFileSync(path.join(__dirname,'../static/js/canvas.js'),'utf8');
const smart=fs.readFileSync(path.join(__dirname,'../static/js/smart-canvas.js'),'utf8');
const helper=fs.readFileSync(path.join(__dirname,'../static/js/canvas-conflict-recovery.js'),'utf8');
function extract(source,from,to){
    const a=source.indexOf(from),b=source.indexOf(to,a);
    assert.ok(a>=0&&b>a,'missing actual function '+from);
    return source.slice(a,b);
}
function failStorage(){throw Error('QuotaExceededError');}
function classicFixture(storageFn){
    const segment=extract(classic,'function captureCanvasConflictDraft(){','async function saveCanvas(){');
    const ctx={
        canvas:{id:'x',title:'Local',icon:'star',revision:2,project:'default'},
        lastCanvasUpdatedAt:100,connections:[],viewport:{},nodes:[{id:'keep'}],
        serializableCanvasNodes(){return this.nodes},localStorage:{setItem:storageFn},
        console:{error(){}}
    };
    return new Function('ctx','with(ctx){'+segment+'return captureCanvasConflictDraft;}')(ctx)();
}
function smartFixture(storageFn){
    const segment=extract(smart,'function persistSmartConflictDraft(','function scheduleSave(){');
    const ctx={
        canvas:{id:'x',revision:2},canvasId:'x',nodes:[{id:'keep'}],viewport:{},
        canvasForStorage(){return {title:'Smart',nodes:[{id:'keep'}]};},
        localStorage:{setItem:storageFn},console:{error(){}}
    };
    return new Function('ctx','with(ctx){'+segment+'return persistSmartConflictDraft;}')(ctx)();
}
function recoveryPanel(record){
    const panels=[];
    const document={
        createElement(tag){
            return {tag,children:[],style:{},setAttribute(){},
                addEventListener(){},append(...items){this.children.push(...items)},
                appendChild(child){this.children.push(child)},remove(){}};
        },
        getElementById(){return null},
        body:{append(el){panels.push(el)}}
    };
    const window={document,fetch(){throw Error('No network')}}; 
    new Function('window','document',helper)(window,document);
    assert.equal(window.CanvasConflictRecovery.show({id:'x',record}),true);
    assert.equal(panels.length,1);
    return panels[0].children[1].textContent;
}
test('classic localStorage failure flags in-memory-only draft with original nodes',()=>{
    const draft=classicFixture(failStorage);
    assert.equal(draft.persistence_error,true);
    assert.equal(draft.nodes[0].id,'keep');
});
test('smart localStorage failure flags in-memory-only draft',()=>{
    const draft=smartFixture(failStorage);
    assert.equal(draft.persistence_error,true);
    assert.equal(draft.canvas.nodes[0].id,'keep');
});
test('recovery panel explicitly warns of data loss on reload and export action',()=>{
    const label=recoveryPanel({canvas_id:'x',nodes:[],persistence_error:true});
    assert.match(label,/本地存储失败/);
    assert.match(label,/刷新或关闭将丢失/);
    assert.match(label,/导出本地草稿 JSON/);
});
test('successful storage has no warning flag or false alarm',()=>{
    const classicDraft=classicFixture(()=>{});
    const smartDraft=smartFixture(()=>{});
    assert.equal(classicDraft.persistence_error,undefined);
    assert.equal(smartDraft.persistence_error,undefined);
    assert.match(recoveryPanel(classicDraft),/原画布不会被自动覆盖/);
});
