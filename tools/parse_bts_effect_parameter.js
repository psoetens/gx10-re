#!/usr/bin/osascript -l JavaScript
//
// Parse BOSS Tone Studio's `effect_parameter.js` (and, when invoked
// with --with-resources, also `resource.js`) — both are JS object
// literals, not strict JSON: identifier constants, trailing commas,
// mixed quotes, conditional blocks gated on
// ProductSetting.communicationLevel.
//
// Run via:
//   osascript -l JavaScript tools/parse_bts_effect_parameter.js \
//     > captures/bts_effect_parameter.json
//
//   # also dump resource.js (enum strings indexed by resourceId)
//   osascript -l JavaScript tools/parse_bts_effect_parameter.js \
//     --with-resources \
//     > captures/bts_effect_parameter_with_resources.json
//
// Defaults to the GX-10 install. To target a different bundle, set
// $BTS_BUNDLE before invoking (the GX-100 bundle works too — same
// data-file format).
//
// macOS only (uses JavaScript for Automation + ObjC bridge to read files).
//
// All work happens at top level: JXA's `eval()` only sees variables in
// its outer lexical scope, and wrapping the setup in a `run()` function
// hides `window`/`EFFECT_PARAMETERS` from the eval'd BTS source.
ObjC.import('Foundation');

var env = $.NSProcessInfo.processInfo.environment;
var override = ObjC.unwrap(env.objectForKey('BTS_BUNDLE'));
var bundle = override && override.length
  ? override
  : '/Applications/BOSS/GX-10/BOSS TONE STUDIO for GX-10.app';
var base = bundle + '/Contents/Resources/html/js/';

// --with-resources flag: also evaluate resource.js and merge its output
// into the top-level JSON under "_resources".
var argv = ObjC.unwrap($.NSProcessInfo.processInfo.arguments).map(
  function (a) { return ObjC.unwrap(a); });
var withResources = argv.indexOf('--with-resources') !== -1;

function read(rel) {
  var s = $.NSString.stringWithContentsOfFileEncodingError(
    base + rel, $.NSUTF8StringEncoding, null);
  if (!s) throw new Error('cannot read ' + base + rel);
  return ObjC.unwrap(s);
}

// Stub globals BTS expects.
// ---- Integer-size encoding constants (utilities/constant.js) -----------
var INTEGER1x1 = 0x10000, INTEGER1x2 = 0x10001, INTEGER1x3 = 0x10002,
    INTEGER1x4 = 0x10003, INTEGER1x5 = 0x10004, INTEGER1x6 = 0x10005,
    INTEGER1x7 = 0x10006, INTEGER2x4 = 0x10007, INTEGER2x7 = 0x1000B,
    INTEGER4x4 = 0x10008;
// ---- App-runtime globals referenced by the data file ------------------
var window = { ProductSetting: { communicationLevel: 4 } };
var NUMPAD_TYPE = { withText: 'withText', normal: 'normal' };
var Parameter = { value: function () { return 0; } };

// numpad_const.js defines window.NUMPAD_TYPE properly; load it first.
eval(read('businesslogic/numpad_const.js'));
if (window.NUMPAD_TYPE) NUMPAD_TYPE = window.NUMPAD_TYPE;

// effect_parameter.js: closes its data initialization (`if (...) { ... }`)
// around line 17615, then runs cleanup loops that reference bare
// `EFFECT_PARAMETERS`. Alias it locally so those loops resolve.
var src = read('config/effect_parameter.js');
var lines = src.split('\n');
// The bare-EFFECT_PARAMETERS loops live inside function bodies that are
// called AFTER the data is fully populated by `Object.assign`. The alias
// must go at script-level scope BEFORE those function declarations so
// the function bodies pick it up via the lexical scope chain. Splice
// right after the `if (...communicationLevel >= 3) { ... }` block closes.
var aliasAt = -1;
for (var i = 0; i < lines.length; i++) {
  if (/^\s*function\s+appendBpmMidiAfterBpm\s*\(/.test(lines[i])) {
    aliasAt = i; break;
  }
}
if (aliasAt < 0) throw new Error('could not find appendBpmMidiAfterBpm anchor');
lines.splice(aliasAt, 0, 'var EFFECT_PARAMETERS = window.EFFECT_PARAMETERS;');
eval(lines.join('\n'));

// Optional resource.js extraction. The file defines a `Resource()` function
// that returns the populated resourceId -> {text: [...], icon: [...]} array.
var output;
if (withResources) {
  eval(read('config/resource.js'));
  var resources = Resource();
  output = { effect_parameters: window.EFFECT_PARAMETERS, resources: resources };
} else {
  output = window.EFFECT_PARAMETERS;
}

JSON.stringify(output);
