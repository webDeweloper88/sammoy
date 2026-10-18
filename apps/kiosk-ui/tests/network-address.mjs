import assert from 'node:assert/strict';
import {maskFromPrefix,prefixFromMask} from '../src/network-address.js';
for(let prefix=8;prefix<=30;prefix++)assert.equal(prefixFromMask(maskFromPrefix(prefix)),prefix);
assert.equal(prefixFromMask('255.255.255.0'),24);
assert.equal(prefixFromMask('255.255.0.0'),16);
assert.equal(prefixFromMask('255.255.255.128'),25);
for(const mask of ['255.0.255.0','255.255.255.256','255.255.255','255.255.255.255','0.0.0.0','abc','255.255.255.-1'])assert.throws(()=>prefixFromMask(mask));
console.log('PASS subnet mask conversion: /8–/30 roundtrip and invalid/non-contiguous masks rejected');
