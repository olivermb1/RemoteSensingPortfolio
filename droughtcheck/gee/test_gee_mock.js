// Dry run of drought_check.js in Node with a stand-in `ee`, `ui`, `Map`, `Export`:
// every ee call returns another stand-in, so this catches JavaScript errors (typos,
// undefined names in callbacks too, since callbacks are run once) but not Earth Engine semantics.
// Usage: node gee/test_gee_mock.js
const fs = require('fs'), path = require('path'), vm = require('vm');
const calls = {};
function stub(name) {
  const f = function (...args) {
    calls[name] = (calls[name] || 0) + 1;
    // run callbacks (map, iterate, forEach bodies) once with stand-in arguments
    args.filter(a => typeof a === 'function' && !a.__stub).forEach(cb => cb(stub('arg'), stub('arg')));
    return stub(name + '()');
  };
  f.__stub = true;
  return new Proxy(f, {
    get(t, k) {
      if (k === 'evaluate') return cb => cb('2026-08');
      if (k === '__stub') return true;
      if (typeof k === 'symbol') return undefined;
      return stub(String(k));
    },
  });
}
const ctx = { ee: stub('ee'), ui: stub('ui'), Map: stub('Map'), Export: stub('Export'), Math,
              print: () => {}, Object, parseInt };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'drought_check.js'), 'utf8'), ctx);
const need = ['gammainc', 'erfInv', 'pearsonsCorrelation', 'linearFit', 'addLayer', 'toDrive', 'series', 'iterate'];
const missing = need.filter(k => !calls[k]);
if (missing.length) { console.error('never called:', missing); process.exit(1); }
console.log('ok: script ran end to end;', Object.keys(calls).length, 'distinct calls');
