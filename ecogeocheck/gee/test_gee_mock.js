// Runs the Code Editor script in Node against a stand-in `ee`/`Map`/`Export`/`ui`.
// It cannot check Earth Engine itself, only that the script runs end to end
// without reference or type errors, that it measures offsets and queues the export,
// and that ID_REGEX pulls orbit and scene out of ECOSTRESS v002 names.
// Usage: node gee/test_gee_mock.js
var fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
var src = fs.readFileSync(path.join(__dirname, 'ecogeocheck_gee.js'), 'utf8');

function run(source) {
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
        args.forEach(function (a) { if (typeof a === 'function' && !proxies.has(a)) a(fake('arg'), fake('acc')); });
        return fake(name + '()');
      },
      construct: function () { return fake('new ' + name); }
    });
    proxies.add(p);
    return p;
  }
  var ctx = {ee: fake('ee'), Map: fake('Map'), Export: fake('Export'), print: fake('print'), ui: fake('ui')};
  vm.runInNewContext(source, ctx);
  return {calls: calls, ctx: ctx};
}

var a = run(src);
var ex = a.calls.filter(function (c) { return /^Export\.table\.toDrive/.test(c); });
assert.strictEqual(ex.length, 1, 'expected 1 export');
assert(a.calls.some(function (c) { return c.indexOf('displacement') >= 0; }), 'no offset measurement');
// With a flag table set, the join path runs too.
var b = run(src.replace("var FLAG_TABLE = null;", "var FLAG_TABLE = 'projects/x/assets/geo_flags';"));
assert(b.calls.some(function (c) { return c.indexOf('Join.saveFirst') >= 0; }), 'no flag join');

var re = new RegExp(a.ctx.ID_REGEX);
var m = 'ECOv002_L2T_LSTE_33138_005_37MBU_20240505T081052_0712_01'.match(re);
assert.deepStrictEqual([m[1], m[2]], ['33138', '005']);
console.log('GEE mock run ok:', a.calls.length, 'calls; flag-table run', b.calls.length, 'calls; ID regex ok');
