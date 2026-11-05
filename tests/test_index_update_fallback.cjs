'use strict';
// Execute the real inline update-check function from static/index.html, offline.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const start = html.indexOf('async function checkForUpdates(manual = false) {');
const end = html.indexOf('\n    </script>', start);
assert.ok(start >= 0 && end > start, 'expected real checkForUpdates function in index HTML');
const source = html.slice(start, end).trim();

function simulatedPage({backendOK=false, githubVersion='2026.08.28',
                        modelscopeVersion='2099.01.01'}={}) {
    const calls = [], notices = [], selections = [];
    const appInfo = {
        version:'2026.08.28',
        sources:{
            github:{version_url:'https://example.test/github/VERSION'},
            modelscope:{version_url:'https://example.test/modelscope/VERSION'},
        },
    };
    async function fetch(url) {
        calls.push(url);
        if (url === '/api/app-info') return {json:async()=>appInfo};
        if (url === '/api/check-update') return {
            ok:backendOK,
            json:async()=>({
                current:'2026.08.28', reachable:true,
                latest:{source:'github', version:githubVersion},
            }),
        };
        if (url.startsWith(appInfo.sources.github.version_url)) {
            return {ok:true, text:async()=>githubVersion};
        }
        if (url.startsWith(appInfo.sources.modelscope.version_url)) {
            return {ok:true, text:async()=>modelscopeVersion};
        }
        throw Error('unexpected fetch '+url);
    }
    const ctx = {
        appInfo:{}, fetch, document:{getElementById:()=>null},
        window:{StudioI18n:{lang:()=> 'zh'}},
        setProjectVersionBadge(){},
        compareVersions(a,b) {
            return Number(a.replaceAll('.','')) - Number(b.replaceAll('.',''));
        },
        setProjectUpdateNotes(){},
        showUpdateNotice(from,to) { notices.push({from,to}); },
        setUpdateSource(value) { selections.push(value); },
        openProjectUpdateModal(){},
        alert(){},
    };
    const check = vm.runInNewContext('('+source+')',ctx);
    return {calls, notices, selections, check};
}

test('legacy-browser fallback ignores disabled ModelScope and its newer version',async()=>{
    const page = simulatedPage();
    await page.check();
    assert.equal(page.calls.some(url=>url.includes('/modelscope/')), false);
    assert.equal(page.notices.length, 0);
    assert.equal(page.selections.length, 0);
});

test('legacy-browser fallback still announces an actual GitHub update',async()=>{
    const page = simulatedPage({githubVersion:'2026.09.01'});
    await page.check();
    assert.equal(page.calls.some(url=>url.includes('/modelscope/')), false);
    assert.equal(page.notices.length, 1);
    assert.equal(page.notices[0].to, '2026.09.01');
});

test('successful backend detection never enters direct-version fallback',async()=>{
    const page = simulatedPage({backendOK:true, githubVersion:'2026.09.01'});
    await page.check();
    assert.deepEqual(page.calls, ['/api/app-info','/api/check-update']);
    assert.equal(page.notices[0].to, '2026.09.01');
});
