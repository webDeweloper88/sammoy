import assert from 'node:assert/strict'
import {requestErrorText} from '../src/request-error.js'
for(const status of [500,502,401,403,409,422]){
 const error=Object.assign(new Error('Internal Server Error'),{status})
 const texts=['ru','uz','en'].map(language=>requestErrorText(error,language))
 assert.equal(new Set(texts).size,3)
 assert(texts.every(text=>text&&!text.includes('Internal Server Error')&&!text.includes('HTTP ')))
}
assert.equal(requestErrorText(new Error('HTTP 500'),'uz'),requestErrorText({status:500},'uz'))
assert.match(requestErrorText(new TypeError('Failed to fetch'),'ru'),/Нет ответа/)
assert.equal(requestErrorText(new Error('Введите код'),'ru'),'Введите код')
console.log('PASS request errors: RU/UZ/EN HTTP and network text; local validation preserved')
