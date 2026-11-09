// S08: no-dependency regression for the canvas recovery panel collapse control.
// In real Chromium, inline display:flex overrides the UA rule for [hidden].
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../static/js/canvas-conflict-recovery.js'),'utf8');

function mount(){
    const nodes = new Map();
    function element(tag){
        const listeners = new Map();
        return {
            tag, style: {}, children:[], hidden:false, textContent:'',
            setAttribute(){}, addEventListener(event,cb){listeners.set(event,cb);},
            append(...children){this.children.push(...children);},
            click(){const cb = listeners.get('click') || this.onclick; if(cb)cb();},
            remove(){nodes.delete(this.id);},
            set id(value){this._id=value;nodes.set(value,this);},
            get id(){return this._id;}
        };
    }
    const document={createElement:element,getElementById:id=>nodes.get(id),body:{append(el){nodes.set(el.id,el);}}};
    const window={document,fetch(){throw Error('No fetch expected');}};
    vm.runInNewContext(source,{window,document});
    return {window,nodes};
}

test('collapse hides flex action buttons, and clicking the title expands them again',()=>{
    const {window,nodes}=mount();
    assert.equal(window.CanvasConflictRecovery.show({id:'offline',record:{nodes:[]}}),true);
    const panel=nodes.get('canvas-conflict-recovery');
    const [title,description,actions,status] = panel.children;
    const collapse = actions.children.at(-1);
    assert.equal(collapse.textContent,'收起');
    collapse.click();
    assert.equal(description.hidden,true);
    assert.equal(status.hidden,true);
    assert.equal(actions.style.display,'none','inline flex must be overridden; hidden alone is ignored by Chromium');
    title.click();
    assert.equal(actions.hidden,false);
    assert.equal(actions.style.display,'flex');
    assert.equal(description.hidden,false);
    assert.equal(status.hidden,false);
});
