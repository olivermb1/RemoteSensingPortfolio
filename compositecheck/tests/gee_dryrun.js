// Dry run of gee/composite_check.js with a stand-in `ee` where every call returns another
// stand-in. It catches JavaScript errors (typos, undefined names, wrong client-side code);
// Callbacks passed to .map() etc. are run too. It cannot check Earth Engine semantics. Usage: node tests/gee_dryrun.js
const fs = require('fs'), path = require('path'), vm = require('vm');
const calls = new Set();
const proxies = new WeakSet();
function stub(name) {
  const f = function () {};
  const p = new Proxy(f, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => 1 : (calls.add(name + '.' + String(k)), stub(String(k)))),
    apply: (t, self, args) => {
      // run callbacks (the bodies of .map(function ...) etc.) with stand-in arguments
      args.forEach(a => { if (typeof a === 'function' && !proxies.has(a)) a(stub('arg'), stub('arg')); });
      return stub(name + '()');
    },
    construct: () => stub('new ' + name),
  });
  proxies.add(p);
  return p;
}
const ctx = {ee: stub('ee'), ui: stub('ui'), Map: stub('Map'), Export: stub('Export'), print: () => {}, Math};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'gee', 'composite_check.js'), 'utf8'), ctx);
console.log('dry run ok,', calls.size, 'distinct ee/ui member accesses');
