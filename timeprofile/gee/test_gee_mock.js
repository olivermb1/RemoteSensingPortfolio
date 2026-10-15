// Runs the Code Editor script in Node against a stand-in `ee`/`ui`/`Map`/`Export`.
// It cannot check Earth Engine itself, only that the script runs end to end
// (including the click, draw and export handlers) without reference or type errors.
// Usage: node gee/test_gee_mock.js
var fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
var src = fs.readFileSync(path.join(__dirname, 'timeprofile_gee.js'), 'utf8');

var calls = [], proxies = new WeakSet();
function fake(name) {
  var fn = function () {};
  var p = new Proxy(fn, {
    get: function (t, k) {
      if (typeof k === 'symbol' || k === 'then' || k === 'prototype') return undefined;
      if (k === 'getValue') return function () { return undefined; };
      return fake(name + '.' + String(k));
    },
    apply: function (t, self, args) {
      calls.push(name);
      // Run callbacks (click, draw, button, map) so their bodies are exercised too.
      args.forEach(function (a) {
        if (typeof a === 'function' && !proxies.has(a)) a(fake('arg'), fake('acc'));
        else if (a && typeof a === 'object' && !proxies.has(a) && typeof a.onChange === 'function') a.onChange('NDMI');
      });
      return fake(name + '()');
    },
    construct: function () { return fake('new ' + name); }
  });
  proxies.add(p);
  return p;
}
var ctx = {ee: fake('ee'), ui: fake('ui'), Map: fake('Map'), Export: fake('Export'), print: fake('print')};
vm.runInNewContext(src, ctx);
// The Clear button's handler also ran (emptying the list), so add a place and export again.
ctx.addPlace(fake('geom'), 'Polygon');
ctx.exportCsv();
function has(s) { return calls.some(function (c) { return c.indexOf(s) >= 0; }); }
assert(has('reduceRegions'), 'no per-place reduction');
assert(has('ui.Chart.feature.groups'), 'no chart');
assert(has('NASA/HLS') || has('ee.ImageCollection'), 'no collection');
assert(has('Export.table.toDrive'), 'export handler did not run');
assert(has('rightShift'), 'no Fmask bit decoding');
console.log('GEE mock run ok:', calls.length, 'calls');
