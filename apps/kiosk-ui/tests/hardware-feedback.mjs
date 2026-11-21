import assert from 'node:assert/strict'
import {washTexts} from '../src/kiosk/wash-texts.js'
import {hardwareErrorText,hardwareWarningTexts} from '../src/kiosk/hardware-feedback.js'
for(const t of Object.values(washTexts)){
 for(const code of ['io_connection_lost','io_helper_unavailable','io_data_stale','output_confirmation_failed','controller_safety_stop','io_protocol_error','payment_accounting_error','control_error'])assert.notEqual(hardwareErrorText({hardwareErrorCode:code},t),t.hardware)
 assert.equal(hardwareWarningTexts({hardwareWarnings:['cash_unavailable','nfc_unavailable']},t).length,2)
 assert.equal(hardwareErrorText({hardwareErrorCode:'unknown'},t),t.hardware)
}
console.log('Four-language hardware feedback checks passed')
