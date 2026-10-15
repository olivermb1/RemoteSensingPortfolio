// Runs the Code Editor script in Node against a stand-in `ee`/`Map`/`Export`.
// It cannot check Earth Engine itself, only that the script runs end to end
// without reference or type errors, and that it queues the three exports.
// Usage: node gee/test_gee_mock.js
var fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
var src = fs.readFileSync(path.join(__dirname, 'distwatch_gee.js'), 'utf8');

var calls = [], proxies = new WeakSet();
function fake(name) {
  var fn = function () {};
  var p = new Proxy(fn, {
    get: function (t, k) {
      if (typeof k === 'symbol' || k === 'then' || k === 'prototype') return undefined;
      return fake(name + '.' + String(k));
    },
    apply: function (t, self, args) {
      calls.push(name);
      // Run callbacks passed to map/iterate so their bodies are exercised too.
      args.forEach(function (a) { if (typeof a === 'function' && !proxies.has(a)) a(fake('arg'), fake('acc')); });
      return fake(name + '()');
    },
    construct: function () { return fake('new ' + name); }
  });
  proxies.add(p);
  return p;
}
var ctx = {ee: fake('ee'), Map: fake('Map'), Export: fake('Export'), print: fake('print')};
vm.runInNewContext(src, ctx);
var exports_ = calls.filter(function (c) { return /^Export\.(table|image)\.to/.test(c); });
assert.strictEqual(exports_.length, 3, 'expected 3 exports, got ' + exports_);
assert(calls.some(function (c) { return c.indexOf('reduceRegions') >= 0; }), 'no per-area summary');
assert(calls.some(function (c) { return c.indexOf('connectedPixelCount') >= 0; }), 'no patch-size filter');
console.log('GEE mock run ok:', calls.length, 'calls,', exports_.join(', '));
