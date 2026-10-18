import assert from 'node:assert/strict'
import {editPaymentAmount as edit} from '../src/kiosk/payment-amount.js'
assert.deepEqual(edit('10000','2',true),{amount:'2',replace:false})
assert.equal(edit('2','5',false).amount,'25')
assert.equal(edit('25000','⌫',true).amount,'2500')
assert.equal(edit('25000','C',true).amount,'')
assert.equal(edit('0','5',false).amount,'5')
assert.equal(edit('12345678','9',false).amount,'12345678')
console.log('Payment amount editing passed')
