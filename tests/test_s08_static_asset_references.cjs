"use strict";
// S08 offline release smoke-check: every literal local asset referenced by the
// project's HTML pages must exist. No browser, network, or install required.
// Run: node --test tests/test_s08_static_asset_references.cjs
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");

const ROOT=path.resolve(__dirname,"..");
const roots=[
  path.join(ROOT,"static"),
  path.join(ROOT,"tools","chrome-local-asset-importer"),
  path.join(ROOT,"tools","photoshop-asset-connector"),
];
function htmlFiles(dir){
  if(!fs.existsSync(dir)) return [];
  const files=[];
  for(const ent of fs.readdirSync(dir,{withFileTypes:true})){
    const full=path.join(dir,ent.name);
    if(ent.isDirectory()) files.push(...htmlFiles(full));
    else if(ent.isFile() && ent.name.endsWith(".html")) files.push(full);
  }
  return files;
}

test("all literal local script, stylesheet and image references in HTML resolve",()=>{
  const html=roots.flatMap(htmlFiles);
  assert.ok(html.length>0,"no HTML pages found");
  let checked=0;
  const missing=[];
  for(const page of html){
    const source=fs.readFileSync(page,"utf8");
    // Dynamic template expressions are runtime values, not static file links.
    const tags=/<(?:script|link|img)\b[^>]*?\b(?:src|href)\s*=\s*(["'])(.*?)\1/gi;
    for(const match of source.matchAll(tags)){
      const uri=match[2].split(/[?#]/,1)[0].trim();
      if(uri.includes("$"+"{")||uri.includes("{{")) continue;
      let asset="";
      if(uri.startsWith("/static/")) asset=path.join(ROOT,uri.slice(1));
      else if(uri.startsWith("./")||uri.startsWith("../")) asset=path.resolve(path.dirname(page),uri);
      else continue; // External URLs, data URLs and runtime-relative routes.
      checked++;
      if(!fs.existsSync(asset))missing.push(path.relative(ROOT,page)+" -> "+uri);
    }
  }
  assert.ok(checked>0,"no local HTML assets were examined");
  assert.deepEqual(missing,[],"missing local HTML asset references");
});
