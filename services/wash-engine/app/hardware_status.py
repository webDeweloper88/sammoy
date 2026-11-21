"""Customer-safe fault codes; peripheral availability never grants output permission."""
class HardwareFault(RuntimeError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def critical_code(error):
    if isinstance(error, HardwareFault):
        return error.code
    message = str(error)
    if 'Modbus is unavailable' in message:
        return 'io_connection_lost'
    if 'profile mismatch' in message or 'native I/O' in message or 'Invalid I/O' in message:
        return 'io_protocol_error'
    if 'freshness' in message or 'polling is stale' in message:
        return 'io_data_stale'
    if 'readback' in message or 'outputs confirmed OFF' in message:
        return 'output_confirmation_failed'
    if 'controller restarted' in message or 'lease renewal' in message:
        return 'controller_safety_stop'
    if 'NV9' in message or 'Payment reconciliation' in message:
        return 'payment_accounting_error'
    return 'control_error'


def peripheral_status(io, rfid_payload):
    warnings = []
    bill_filter = io.get('bill_filter') or {}
    enabled = io.get('nv9_enabled') is not False
    cash_ready = enabled and io.get('nv9_listener_alive') is True and bill_filter.get('ready') is True and not bill_filter.get('fault')
    if enabled and not cash_ready:
        warnings.append('cash_unavailable')
    rfid = rfid_payload.get('rfid') or {}
    nfc_ready = rfid.get('online') is True and not rfid.get('last_error')
    if not nfc_ready:
        warnings.append('nfc_unavailable')
    return {'hardwareWarnings': warnings, 'billInputReady': bool(cash_ready),
            'billInputFault': bill_filter.get('fault') or ('listener_unavailable' if enabled and io.get('nv9_listener_alive') is False else None),
            'nfcReady': nfc_ready}
