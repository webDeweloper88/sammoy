export function walletErrorText(state, texts) {
 const known={'VIP daily limit reached':'vipDailyLimit','VIP card is not active':'vipInactive','Срок действия VIP-карты истёк':'vipExpired'}
 if(known[state?.walletLastError])return texts[known[state.walletLastError]]
 if (state?.walletLastError === 'VIP-карта уже используется на другом посту') return texts.cardInUse
 return state?.walletLastError === 'Денежный баланс нельзя смешивать с VIP-допуском' ? texts.vipMoneyConflict : texts.walletUnavailable
}
