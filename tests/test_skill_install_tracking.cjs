// S06: the GitHub install UI must send a moving ref alongside the fixed SHA.
// Run: node --test tests/test_skill_install_tracking.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/js/skill-manager.js'),'utf8');
const start=code.indexOf('async function githubInstall()');
const end=code.indexOf('async function checkUpdate(',start);
assert.ok(start>=0&&end>start);
const source=code.slice(start,end);
function fixture(previewRef='main',inputRef=''){
    const req=[];
    const elements={
        ghUrl:{value:'https://github.com/example/ink'},
        ghInstallName:{value:'ink'},ghOverwrite:{checked:false},
        ghInstallBtn:{disabled:false},ghRef:{value:inputRef},
        ghSubdir:{value:'skills/ink'},ghOverwriteRow:{hidden:true},
    };
    const ctx={
        ghPreview:{repo:{sha:'a'.repeat(40),ref:previewRef}},
        document:{getElementById(id){return elements[id];}},
        setStatus(){},toast(){},closeOverlay(){},syncTabs(){},
        loadSkills:async()=>{},activeSource:'custom',
        api:async(url,opts)=>{
            req.push({url,body:JSON.parse(opts.body)});
            return {id:'ink'};
        }
    };
    const run=new Function('ctx','with(ctx){'+source+'return githubInstall;}')(ctx);
    return {run,req,elements,ctx};
}
test('install sends branch as tracking_ref and SHA as immutable commit',async()=>{
    const f=fixture('release-v3');
    await f.run();
    assert.equal(f.req.length,1);
    assert.equal(f.req[0].url,'/api/skills/github/install');
    assert.equal(f.req[0].body.sha,'a'.repeat(40));
    assert.equal(f.req[0].body.tracking_ref,'release-v3');
    assert.equal(f.elements.ghInstallBtn.disabled,false);
});
test('explicit ref input survives if preview metadata does not contain ref',async()=>{
    const f=fixture('','feature/ink-update');
    await f.run();
    assert.equal(f.req[0].body.tracking_ref,'feature/ink-update');
});
test('missing ref leaves default-branch tracking without copying commit SHA',async()=>{
    const f=fixture('','');
    await f.run();
    assert.equal(f.req[0].body.tracking_ref,'');
    assert.equal(f.req[0].body.sha,'a'.repeat(40));
});
