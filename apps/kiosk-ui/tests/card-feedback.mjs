import assert from 'node:assert/strict'
import { walletErrorText } from '../src/kiosk/card-feedback.js'
import { washTexts } from '../src/kiosk/wash-texts.js'
for (const texts of Object.values(washTexts)) {
 assert.equal(walletErrorText({walletLastError:'VIP-карта уже используется на другом посту'},texts),texts.cardInUse)
 for(const [error,key] of [['VIP daily limit reached','vipDailyLimit'],['VIP card is not active','vipInactive'],['Срок действия VIP-карты истёк','vipExpired']]){assert.ok(texts[key]);assert.notEqual(texts[key],texts.walletUnavailable);assert.equal(walletErrorText({walletLastError:error},texts),texts[key])}
 assert.ok(texts.vipMoneyConflict)
 assert.notEqual(texts.vipMoneyConflict,texts.walletUnavailable)
 assert.equal(walletErrorText({walletLastError:'Денежный баланс нельзя смешивать с VIP-допуском'},texts),texts.vipMoneyConflict)
 for (const state of [null,{}, {walletLastError:'timeout'}]) assert.equal(walletErrorText(state,texts),texts.walletUnavailable)
}
console.log('Card feedback: four languages and outage fallback passed')
