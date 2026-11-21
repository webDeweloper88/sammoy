const errors = {
 io_connection_lost:'ioConnectionLost', io_helper_unavailable:'ioHelperUnavailable',
 io_data_stale:'ioDataStale', output_confirmation_failed:'outputConfirmationFailed',
 controller_safety_stop:'controllerSafetyStop', io_protocol_error:'ioProtocolError',
 payment_accounting_error:'paymentAccountingError', control_error:'controlError'
}
export function hardwareErrorText(state,t){return t[errors[state?.hardwareErrorCode]]||t.hardware}
export function hardwareWarningTexts(state,t){return (state?.hardwareWarnings||[]).map(code=>code==='nfc_unavailable'?t.nfcUnavailable:code==='cash_unavailable'?t.cashWarning:null).filter(Boolean)}
