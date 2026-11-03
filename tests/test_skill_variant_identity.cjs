// S05: editing a variant label must not change the ID referenced by canvases.
// Run: node --test tests/test_skill_variant_identity.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/skill-manager.js'),'utf8');
const begin=source.indexOf('function addVariantRow(');
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
    const ctx={document:doc,editingId:'ink-skill',escapeHtml:value=>String(value),
        api:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true}},
        toast(){},closeOverlay(){},loadSkills:async()=>{}};
    const actions=new Function('ctx','with(ctx){'+snippet+'return {addVariantRow,collectVariants,saveEditor};}')(ctx);
    return {rows,elements,requests,...actions};
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
    assert.equal(x.requests[0].body.content,'# Updated body');
    assert.equal(x.requests[0].body.variants[0].id,'sumi-custom-17');
});
