// S04: offline Node regression for non-destructive conflict recovery.
// Run: node --test tests/test_canvas_conflict_recovery.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../static/js/canvas-conflict-recovery.js'),'utf8');
function api(){
    const win = {fetch:()=>{throw Error('Unexpected network request');},document:null};
    vm.runInNewContext(source,{window:win});
    return win.CanvasConflictRecovery;
}
function response(canvas,status=200){
    return {ok:status>=200&&status<300,status,json:async()=>({canvas})};
}
test('classic conflict saves a new canvas, never PUTs the original',async()=>{
    const recovery=api(), calls=[];
    const draft={canvas_id:'original',title:'Original',icon:'layers',project:'custom',nodes:[{id:'one'}],connections:[{id:'edge'}],viewport:{x:2,y:3,scale:1},logs:[]};
    const fetch=async(url,opts)=>{
        calls.push({url,opts});
        return calls.length===1?response({id:'new-canvas',revision:0}):response({id:'new-canvas',revision:1});
    };
    const result=await recovery.createIndependentCopy(draft,'classic',fetch);
    assert.equal(result.id,'new-canvas');
    assert.deepEqual(calls.map(c=>c.url),['/api/canvases','/api/canvases/new-canvas']);
    assert.equal(JSON.parse(calls[0].opts.body).project,'custom');
    assert.equal(JSON.parse(calls[1].opts.body).base_revision,0);
    assert.equal(JSON.parse(calls[1].opts.body).nodes[0].id,'one');
    assert.equal(draft.canvas_id,'original');
});
test('smart draft wrapper preserves settings and never writes original ID',async()=>{
    const recovery=api(), calls=[];
    const draft={canvas_id:'old',canvas:{kind:'smart',title:'Smart',nodes:[{id:'smart-1'}],settings:{engine:'api'},project:'p'}};
    await recovery.createIndependentCopy(draft,'smart',async(url,opts)=>{
        calls.push({url,opts});return response({id:'fresh',revision:4});
    });
    assert.deepEqual(calls.map(c=>c.url),['/api/canvases','/api/canvases/fresh']);
    assert.equal(JSON.parse(calls[0].opts.body).kind,'smart');
    assert.equal(JSON.parse(calls[1].opts.body).settings.engine,'api');
    assert.equal(JSON.parse(calls[1].opts.body).base_revision,4);
});
test('create failure never sends content PUT',async()=>{
    const calls=[];
    await assert.rejects(api().createIndependentCopy({nodes:[]},'classic',async(url)=>{
        calls.push(url);return response(null,503);
    }));
    assert.deepEqual(calls,['/api/canvases']);
});
test('failed copy PUT is reported without retrying original',async()=>{
    const calls=[];
    await assert.rejects(api().createIndependentCopy({nodes:[]},'classic',async(url)=>{
        calls.push(url);return calls.length===1?response({id:'new',revision:0}):response(null,409);
    }),/草稿仍保留/);
    assert.deepEqual(calls,['/api/canvases','/api/canvases/new']);
});
test('metadata recovery reads current revision before explicit CAS write',async()=>{
    const calls=[];
    await api().applyMetadataAfterConfirmation('old',{title:'New'},async(url,opts)=>{
        calls.push({url,opts});return response({id:'old',revision:12});
    });
    assert.deepEqual(calls.map(c=>c.url),['/api/canvases/old','/api/canvases/old/meta']);
    assert.equal(JSON.parse(calls[1].opts.body).base_revision,12);
    assert.equal(JSON.parse(calls[1].opts.body).title,'New');
});
test('metadata recovery refuses another concurrent conflict',async()=>{
    let count=0;
    await assert.rejects(api().applyMetadataAfterConfirmation('old',{title:'New'},async()=>{
        count++;return count===1?response({id:'old',revision:12}):response(null,409);
    }),/再次发生版本冲突/);
});
test('malformed draft cannot create an empty replacement',async()=>{
    let calls=0;
    await assert.rejects(api().createIndependentCopy({title:'bad'},'classic',async()=>{calls++;}),/no nodes/);
    assert.equal(calls,0);
});
test('saved smart draft is discoverable using its distinct key',()=>{
    const store={'smart_canvas_conflict_draft_old':JSON.stringify({canvas_id:'old',canvas:{nodes:[]}})};
    const nodes=new Map();
    function element(tag){
        return {tag,style:{},children:[],setAttribute(){},addEventListener(){},append(...c){this.children.push(...c);},remove(){nodes.delete(this.id);},set id(v){this._id=v;nodes.set(v,this);},get id(){return this._id;}};
    }
    const document={createElement:element,getElementById:id=>nodes.get(id),body:{append:el=>{nodes.set(el.id,el);}}};
    const window={fetch:()=>{},document,localStorage:{getItem:key=>store[key]||null}};
    vm.runInNewContext(source,{window,document});
    assert.equal(window.CanvasConflictRecovery.showSaved('old','smart'),true);
    assert.ok(nodes.get('canvas-conflict-recovery'));
});
