// S05: editing a variant label must not change the ID referenced by canvases.
// Run: node --test tests/test_skill_variant_identity.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/skill-manager.js'),'utf8');
const begin=source.indexOf('function openEditor(');
const end=source.indexOf('async function deleteSkill(',begin);
assert.ok(begin>=0 && end>begin);
const snippet=source.slice(begin,end);
function fixture(){
    const rows=[];
    const elements={
        skillVariantsList:{
            appendChild(row){rows.push(row);},
            get innerHTML(){return ''},
            set innerHTML(_){rows.length=0},
        },
        skillEditContent:{value:'# Updated body'},
        skillEditSave:{disabled:false},
    };
    const requests=[];
    const doc={
        getElementById(id){return elements[id]||{value:'',textContent:'',style:{}};},
        querySelectorAll(){return rows},
        createElement(){
            const values={label:'',prompt:''};
            const deleteButton={};
            const row={
                className:'',dataset:{},remove(){rows.splice(rows.indexOf(row),1)},
                set innerHTML(markup){
                    values.label=markup.match(/class="skill-input v-label"[^>]+value="([^"]*)"/)?.[1]||'';
                    values.prompt=markup.match(/class="skill-input v-prompt"[^>]+value="([^"]*)"/)?.[1]||'';
                },
                querySelector(which){
                    return which==='.v-del'?deleteButton:
                           which==='.v-label'?{get value(){return values.label},set value(x){values.label=x}}:
                           which==='.v-prompt'?{get value(){return values.prompt},set value(x){values.prompt=x}}:null;
                }
            };
            return row;
        }
    };
    const ctx={document:doc,editingId:'ink-skill',editBaseSha:'a'.repeat(64),escapeHtml:value=>String(value),openOverlay(){},
        api:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true}},
        toast(){},closeOverlay(){},loadSkills:async()=>{}};
    const actions=new Function('ctx','with(ctx){'+snippet+'return {openEditor,addVariantRow,collectVariants,saveEditor};}')(ctx);
    return {rows,elements,requests,ctx,...actions};
}
test('existing custom variant ID remains unchanged when label and prompt change',()=>{
    const x=fixture();
    x.addVariantRow('Old Ink','old prompt','sumi-custom-17');
    x.rows[0].querySelector('.v-label').value='Renamed Ink';
    x.rows[0].querySelector('.v-prompt').value='new prompt';
    assert.deepEqual(x.collectVariants(),[{
        id:'sumi-custom-17',label:'Renamed Ink',prompt:'new prompt'
    }]);
});
test('new variants have no supplied ID so backend allocates it',()=>{
    const x=fixture();
    x.addVariantRow('New Watercolor','new style');
    assert.equal(x.collectVariants()[0].id,'');
});
test('editor sends explicit body contract and stable ID to backend',async()=>{
    const x=fixture();
    x.addVariantRow('Ink','brush','sumi-custom-17');
    x.rows[0].querySelector('.v-label').value='Other label';
    await x.saveEditor();
    assert.equal(x.requests.length,1);
    assert.equal(x.requests[0].url,'/api/skills/custom/ink-skill');
    assert.equal(x.requests[0].body.content_format,'body');
    assert.equal(x.requests[0].body.base_sha256,'a'.repeat(64));
    assert.equal(x.requests[0].body.content,'# Updated body');
    assert.equal(x.requests[0].body.variants[0].id,'sumi-custom-17');
});

test('editing existing Skill disables save until a valid content hash arrives',async()=>{
    const x=fixture();
    let resolveDetail;
    x.ctx.api=()=>new Promise(resolve=>{resolveDetail=resolve});
    x.openEditor({id:'ink-skill',name:'Ink'});
    assert.equal(x.elements.skillEditSave.disabled,true);
    resolveDetail({content_sha256:'b'.repeat(64),body:'# Current body',variants:[
        {id:'Ink@V2',label:'Ink label',prompt:'paint'}
    ]});
    await Promise.resolve();
    assert.equal(x.elements.skillEditSave.disabled,false);
    assert.equal(x.elements.skillEditContent.value,'# Current body');
    assert.equal(x.collectVariants()[0].id,'Ink@V2');
});
test('missing content hash refuses unsafe editing',async()=>{
    const x=fixture();
    x.ctx.api=async()=>({body:'# Current body',variants:[]});
    x.openEditor({id:'ink-skill',name:'Ink'});
    await Promise.resolve();await Promise.resolve();
    assert.equal(x.elements.skillEditSave.disabled,true);
});
