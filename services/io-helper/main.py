import os
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from output_test import OutputTest
from controller_lease import ControllerLease
from pulse_journal import PulseJournal
from input_filter import InputFilter
from bill_filter import BillFilter, normalize as normalize_bill_filter, PRESETS
from datetime import timedelta
from bill_gpio import event_seconds, BillGPIOTrace, BillLevelTrace
from bill_level_reader import LevelReader
from bill_process_reader import ProcessLevelReader, VendorProcessLevelReader
from bill_vendor_gpio import VendorSysfsLine

import gpiod
import yaml
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymodbus.client import ModbusSerialClient
from rfid import RfidReader


CONFIG_FILE = os.getenv("IO_CONFIG", "/config/io-map.yaml")

app = FastAPI(title="SAMMOY 2.0 io-helper")

state_lock = threading.Lock()
bill_lock = threading.RLock()
output_test = OutputTest()
started_monotonic = time.monotonic()

io_state = {
    "inputs": {},
    "raw_inputs": [],
    "outputs": {},
    "raw_outputs": [],
    "nv9_pulses": 0,
    "modbus_ok": False,
    "last_poll_at": None,
    "last_poll_monotonic": None,
}


class OutputCommand(BaseModel):
    on: bool


class PulseCounter:
    def __init__(self):
        self._count = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._count += 1
            return self._count

    def value(self):
        with self._lock:
            return self._count


class ModbusController:
    def __init__(self, cfg):
        self.cfg = cfg
        self.transport = cfg["transport"]
        self.client = None
        self.lock = threading.Lock()

        self.output_map = {
            item["name"]: item["address"]
            for item in cfg["outputs"]
        }

        self.output_names = [
            item["name"] for item in cfg["outputs"]
        ]

    def connect(self):
        # Serialize replacement with every reader/writer. A failed board poll can
        # leave the serial transport open; close it before creating its successor.
        with self.lock:
            if self.client is not None:
                self.client.close()
                self.client = None
            client = ModbusSerialClient(
                port=self.transport["device"],
                baudrate=self.transport["baud_rate"],
                bytesize=self.transport["data_bits"],
                parity="N",
                stopbits=self.transport["stop_bits"],
                timeout=self.transport["response_timeout_ms"] / 1000.0,
            )
            try:
                if not client.connect():
                    client.close()
                    return False
            except Exception:
                client.close()
                raise
            self.client = client
            return True

    def close(self):
        with self.lock:
            if self.client is not None:
                self.client.close()
                self.client = None

    def read_inputs(self):
        with self.lock:
            result = self.client.read_discrete_inputs(
                address=0,
                count=8,
                slave=self.transport["slave_address"],
            )

        if result.isError():
            raise RuntimeError(str(result))

        return result.bits[:8]

    def read_outputs(self):
        with self.lock:
            result = self.client.read_coils(
                address=0,
                count=8,
                slave=self.transport["slave_address"],
            )

        if result.isError():
            raise RuntimeError(str(result))

        return result.bits[:8]

    def write_output(self, name, on):
        if name not in self.output_map:
            raise KeyError(name)

        address = self.output_map[name]

        with self.lock:
            result = self.client.write_coil(
                address=address,
                value=bool(on),
                slave=self.transport["slave_address"],
            )

            if result.isError():
                raise RuntimeError(str(result))

            if self.cfg.get("safety", {}).get(
                "readback_after_write", True
            ):
                readback = self.client.read_coils(
                    address=address,
                    count=1,
                    slave=self.transport["slave_address"],
                )

                if readback.isError():
                    raise RuntimeError(
                        f"Readback failed: {readback}"
                    )

                actual = bool(readback.bits[0])

                if actual != bool(on):
                    raise RuntimeError(
                        f"Output readback mismatch: "
                        f"requested={bool(on)} actual={actual}"
                    )

                return actual

        return bool(on)

    def confirmed_outputs_off(self):
        """Fresh read, switch only energized coils, prove all eight OFF.

        Never infer OFF from the cached API state. On any uncertainty attempt
        the exhaustive shutdown before propagating the original failure.
        """
        try:
            raw = self.read_outputs()
            if len(raw) != 8:raise RuntimeError("Incomplete OFF readback")
            addresses = set(self.output_map.values())
            if any(on and index not in addresses for index,on in enumerate(raw)):
                raise RuntimeError("Unmapped energized output")
            energized = [name for name,address in self.output_map.items() if raw[address]]
            for name in energized:self.write_output(name,False)
            if energized:raw = self.read_outputs()
            if len(raw) != 8 or any(raw):raise RuntimeError("Not all outputs confirmed OFF")
            return raw
        except Exception:
            self.all_outputs_off()
            raise

    def all_outputs_off(self):
        errors=[]
        for name in self.output_names:
            try:
                self.write_output(name, False)
            except Exception as exc:
                errors.append(name)
                print(
                    f"SAFETY: failed to switch {name} OFF: {exc}",
                    flush=True,
                )

        if errors:raise RuntimeError("OFF not confirmed: "+", ".join(errors))


def load_config():
    from hardware_profile import validate_profile
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_profile(cfg)
    return cfg


def update_output_state(controller):
    raw = controller.read_outputs()

    logical = {}

    for index, item in enumerate(controller.cfg["outputs"]):
        logical[item["name"]] = bool(raw[index])

    with state_lock:
        io_state["raw_outputs"] = [int(x) for x in raw]
        io_state["outputs"] = logical


@app.get("/health")
def health():
    with state_lock:
        return {
            "status": "ok",
            "modbus_ok": io_state["modbus_ok"],
            "last_poll_at": io_state["last_poll_at"],
            "uptime_seconds": int(time.monotonic() - started_monotonic),
        }


@app.get("/io")
def get_io():
    safety=APP_STATE["lease"].snapshot()
    bill=bill_snapshot()
    with state_lock:
        return {
            "device_type": APP_STATE["controller"].cfg.get("device_type", "wash"),
            "inputs": dict(io_state["inputs"]),
            "raw_inputs": list(io_state["raw_inputs"]),
            "outputs": dict(io_state["outputs"]),
            "raw_outputs": list(io_state["raw_outputs"]),
            "bill_filter": bill,
            "nv9_pulses": io_state["nv9_pulses"],
            "nv9_enabled": APP_STATE.get("nv9_enabled", True),
            "nv9_stream_id": APP_STATE["pulse_counter"].stream_id,
            "nv9_listener_alive": bool(APP_STATE.get("nv9_thread") and APP_STATE["nv9_thread"].is_alive()),
            "last_poll_at": io_state["last_poll_at"],
            **safety,
            "poll_age_seconds": None if io_state["last_poll_monotonic"] is None else time.monotonic()-io_state["last_poll_monotonic"],
            "test_output": output_test.active,
            "modbus_ok": io_state["modbus_ok"],
        }


@app.get("/rfid/latest")
def rfid_latest():
    return {"ok": True, **APP_STATE["rfid"].snapshot()}


@app.get("/rfid/events")
def rfid_events(since: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000)):
    return APP_STATE["rfid"].events_since(since, limit)


@app.post("/controller/heartbeat")
def controller_heartbeat():
    return {"ok":True,**APP_STATE["lease"].heartbeat()}


@app.post("/controller/all-off")
def controller_all_off():
    controller=APP_STATE["controller"]
    try:
        with output_test.lock:
            raw=controller.confirmed_outputs_off()
            if len(raw)!=8 or any(raw):raise RuntimeError("Not all outputs confirmed OFF")
            update_output_state(controller)
            with state_lock:outputs=dict(io_state["outputs"])
            if any(outputs.values()):raise RuntimeError("OFF readback changed")
        return {"ok":True,"off_confirmed":True,"outputs":outputs}
    except Exception as exc:
        APP_STATE["lease"].trip("output_error")
        with output_test.lock:
            try:controller.all_outputs_off()
            except Exception:pass
        with state_lock:io_state["modbus_ok"]=False
        raise HTTPException(503,str(exc)) from None


@app.post("/outputs/{name}")
def set_output(name: str, command: OutputCommand):
    controller = APP_STATE["controller"]

    if name not in controller.output_map:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown output: {name}",
        )

    with state_lock:
        modbus_ok = io_state["modbus_ok"]

    if command.on and not APP_STATE["lease"].valid():
        raise HTTPException(409,"Controller lease expired")
    if command.on and not modbus_ok:
        raise HTTPException(
            status_code=503,
            detail="Modbus is not available",
        )

    try:
        with output_test.lock:
            if command.on and output_test.active is not None:
                raise HTTPException(409, "An output test is running")
            if command.on:
                raw=controller.confirmed_outputs_off()
                if len(raw)!=8 or any(raw):raise RuntimeError("Not all outputs confirmed OFF")
                if not APP_STATE["lease"].valid():raise HTTPException(409,"Controller lease expired")
            actual = controller.write_output(name, command.on)
            if actual is not command.on:raise RuntimeError("Output readback mismatch")
            if command.on:APP_STATE["lease"].rearm()
            update_output_state(controller)

        return {
            "ok": True,
            "output": name,
            "requested": command.on,
            "actual": actual,
        }

    except HTTPException:
        raise
    except Exception as exc:
        APP_STATE["lease"].trip("output_error")
        with output_test.lock:
            try:controller.all_outputs_off()
            except Exception:pass
        with state_lock:
            io_state["modbus_ok"] = False

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )


@app.get("/configuration")
def configuration():
    cfg = APP_STATE["controller"].cfg
    return {"ok": True, "transport": cfg["transport"], "bill_acceptor": cfg["bill_acceptor"],
            "rfid": cfg.get("rfid", {}), "inputs": cfg["inputs"], "outputs": cfg["outputs"],
            "nv9_listener_alive": bool(APP_STATE.get("nv9_thread") and APP_STATE["nv9_thread"].is_alive())}


@app.post("/outputs/{name}/test")
def test_output(name: str):
    controller = APP_STATE["controller"]
    if name not in controller.output_map:
        raise HTTPException(404, "Unknown output")
    with state_lock:
        ready = io_state["modbus_ok"]
    if not ready:
        raise HTTPException(503, "Modbus is not available")
    try:
        return output_test.run(controller, name, update_output_state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        with state_lock:
            io_state["modbus_ok"] = False
        raise HTTPException(503, "Output test or OFF readback failed") from exc


def bill_events_pending(line):
    reader=APP_STATE.get('bill_reader')
    return reader.pending() if reader is not None else line.event_wait(timedelta(seconds=0))


def bill_snapshot():
    with bill_lock:
        f=APP_STATE.get('bill_filter')
        return {'enabled':APP_STATE.get('nv9_enabled',False),
                'published_pulses':APP_STATE['pulse_counter'].value(),
                'presets':PRESETS, **(f.snapshot() if f else {'ready':False,'fault':None}),
                'diagnostics':{**(APP_STATE['bill_trace'].summary() if APP_STATE.get('bill_trace') else {}),
                    **(APP_STATE['bill_reader'].snapshot() if APP_STATE.get('bill_reader') else {'reader':'edges'})}}


@app.get('/bill/filter')
def bill_filter_read():
    return bill_snapshot()


@app.get('/bill/trace')
def bill_trace_read():
    with bill_lock:
        trace=APP_STATE.get('bill_trace')
        result=trace.snapshot() if trace else {'events':[]}
        levels=APP_STATE.get('bill_levels')
        if levels:result['levels']=levels.snapshot()
        return result


def observe_bill_levels(line, active_low, trace):
    # Read through the existing line request; no second GPIO consumer or output.
    try:
        while time.monotonic()<trace.ends_at:
            if APP_STATE.get('bill_line') is not line:break
            active=(line.get_value()==0) if active_low else (line.get_value()!=0)
            trace.observe(active,time.monotonic())
            time.sleep(.005)
    except Exception as exc:
        with trace.lock:trace.error=type(exc).__name__
    finally:
        with trace.lock:trace.finished=True


@app.post('/bill/trace/start')
def bill_level_trace_start(value:dict):
    seconds=value.get('seconds',180)
    if set(value)-{'seconds'} or type(seconds) is not int or not 10<=seconds<=300:
        raise HTTPException(422,'Observation must last 10 to 300 seconds')
    with bill_lock:
        line=APP_STATE.get('bill_line');f=APP_STATE.get('bill_filter')
        previous=APP_STATE.get('bill_levels')
        if line is None or f is None:raise HTTPException(503,'Bill input not enabled')
        if previous and not previous.finished:raise HTTPException(409,'Level observation already running')
        if f.active or not f.ready or f.fault:raise HTTPException(409,'Wait for an idle healthy input')
        trace=BillLevelTrace(seconds,time.monotonic());APP_STATE['bill_levels']=trace
        threading.Thread(target=observe_bill_levels,args=(line,f.settings['active_low'],trace),daemon=True,name='bill-level-diagnostics').start()
        return {'ok':True,'seconds':seconds,'sample_interval_ms':5,'credits_from_level_observer':False}


@app.post('/bill/filter')
def bill_filter_write(value: dict):
    try:config=normalize_bill_filter(value)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    with bill_lock:
        reader=APP_STATE.get('bill_reader')
        restart_reader=False
        with reader.state_lock if reader else nullcontext():
            old=APP_STATE.get('bill_filter');line=APP_STATE.get('bill_line')
            if old is None or line is None:raise HTTPException(503,'Bill input is not enabled')
            now=time.monotonic()
            repolarize=(config['active_low']!=old.settings['active_low'] and old.active
                        and old.since is not None and now-old.since>=config['startup_idle_ms']/1000)
            if not (old.can_reset(now) or repolarize) or bill_events_pending(line):
                raise HTTPException(409,'Wait for a stable inactive bill input')
            active=(line.get_value()==0) if config['active_low'] else (line.get_value()!=0)
            if active:raise HTTPException(409,'New polarity would make the input active')
            APP_STATE['pulse_counter'].set_setting('bill_filter',config)
            APP_STATE['bill_filter']=BillFilter(config,active,now,fault=old.fault)
            reader=APP_STATE.get('bill_reader')
            if reader:
                restart_reader=getattr(reader,'restart_for_settings',False)
                if not restart_reader:
                    reader.active_low=config['active_low']
                    reader.previous=active
                    reader.last_at=now
                    reader.gap_limit_ms=min(config['min_pulse_ms'],config['min_gap_ms'] or config['min_pulse_ms'])
        if restart_reader:
            try:reader.reconfigure(config['active_low'],active,now,min(config['min_pulse_ms'],config['min_gap_ms'] or config['min_pulse_ms']))
            except Exception:
                APP_STATE['bill_filter'].fault='reader_failed'
                APP_STATE['pulse_counter'].set_setting('bill_filter_fault','reader_failed')
                raise HTTPException(503,'Не удалось перезапустить читатель купюр; приём заблокирован') from None
    return bill_snapshot()


@app.post('/bill/filter/reset')
def bill_filter_reset():
    with bill_lock:
        f=APP_STATE.get('bill_filter');line=APP_STATE.get('bill_line')
        if f is None or line is None:raise HTTPException(503,'Bill input is not enabled')
        active=(line.get_value()==0) if f.settings['active_low'] else (line.get_value()!=0)
        now=time.monotonic()
        if active or not f.can_reset(now) or bill_events_pending(line):raise HTTPException(409,'Input must be stably inactive before reset')
        APP_STATE['pulse_counter'].set_setting('bill_filter_fault',None)
        f.reset_fault(now)
    return bill_snapshot()


def nv9_listener(cfg, counter, stop_event):
    bill=cfg['bill_acceptor']
    if bill.get('enabled',True) is False:return
    vendor = bill.get('source') == 'vendor-sysfs'
    chip = None
    reader_mode = bill.get('reader', 'level-process' if vendor else 'edges')
    if vendor:
        if reader_mode != 'level-process':
            raise ValueError('Vendor GPIO requires isolated level-process reader')
        line = VendorSysfsLine()
    else:
        chip=gpiod.chip(bill['gpio_chip'],gpiod.chip.OPEN_BY_PATH)
        line=chip.get_line(bill['gpio_line'])
        request=gpiod.line_request();request.consumer='sammoy-bill-filter'
        if reader_mode=='level' and os.getenv('IO_BILL_LEVEL_PROCESS')=='1':reader_mode='level-process'
        if reader_mode not in ('edges','level','level-process'):raise ValueError('Unknown bill GPIO reader')
        request.request_type=gpiod.line_request.DIRECTION_INPUT if reader_mode in ('level','level-process') else gpiod.line_request.EVENT_BOTH_EDGES
        if bill.get('gpio_bias')=='pull-up':request.flags=gpiod.line_request.FLAG_BIAS_PULL_UP
        line.request(request)
    reader=None
    try:
        config=normalize_bill_filter(counter.get_setting('bill_filter',{'active_low':bill.get('active_low',True)}))
        active=(line.get_value()==0) if config['active_low'] else (line.get_value()!=0)
        with bill_lock:
            APP_STATE['bill_line']=line
            APP_STATE['bill_trace']=BillGPIOTrace()
            APP_STATE['bill_filter']=BillFilter(config,active,time.monotonic(),counter.get_setting('bill_filter_fault'))
        reader=None
        if reader_mode in ('level','level-process'):
            positive_gap=config['min_gap_ms'] or config['min_pulse_ms']
            reader_class=VendorProcessLevelReader if vendor else (ProcessLevelReader if reader_mode=='level-process' else LevelReader)
            reader=reader_class(line,config['active_low'],active,time.monotonic(),min(config['min_pulse_ms'],positive_gap))
            APP_STATE['bill_trace'].timestamp_source='sampled_monotonic'
        APP_STATE['bill_reader']=reader
        if reader:reader.start()
        print('Bill GPIO filter ready: watching complete pulses; reader='+reader_mode,flush=True)
        while not stop_event.is_set():
            if reader:
                reader.available.wait(.02)
            else:
                has_event=line.event_wait(timedelta(milliseconds=20))
            with bill_lock:
                event=reader.read() if reader else (line.event_read() if has_event else None)
                f=APP_STATE['bill_filter'];old_fault=f.fault
                if reader and reader.error:f.fault=f.fault or reader.error
                if event is not None:
                    read_at=time.monotonic()
                    try:
                        now=event.at if reader else event_seconds(event)
                        if now > read_at+.01:raise ValueError('GPIO clock is not monotonic')
                    except (ValueError,AttributeError,TypeError,OverflowError):
                        f.fault=f.fault or 'timestamp_invalid'
                        if f.fault!=old_fault:
                            counter.set_setting('bill_filter_fault',f.fault)
                        continue  # No processing-clock fallback for financial events.
                    active=event.active if reader else ((event.event_type==gpiod.line_event.FALLING_EDGE) if f.settings['active_low'] else (event.event_type==gpiod.line_event.RISING_EDGE))
                    repeated=(active==f.active)
                    if reader and event.uncertain and f.active:
                        f.uncertain_pulse=True;f.uncertain_reason='sampling_gap'
                    accepted=f.edge(active,now) if not reader or event.changed else False
                    if reader and event.uncertain and active:
                        f.uncertain_pulse=True;f.uncertain_reason='sampling_gap'
                    if reader and not event.changed:f.poll(now)
                    trace_row=APP_STATE['bill_trace'].record(kernel_at=now,read_at=read_at,
                        active=active,accepted=accepted,fault=f.fault,repeated=repeated)
                    try:
                        trace_row['sampled_active']=(line.get_value()==0) if f.settings['active_low'] else (line.get_value()!=0)
                        trace_row['sampled_seconds']=round(time.monotonic(),6)
                    except Exception:
                        trace_row['sampled_active']=None
                else:
                    if not bill_events_pending(line):f.poll(time.monotonic())
                    accepted=False
                if f.fault!=old_fault:
                    counter.set_setting('bill_filter_fault',f.fault)
                    print('BILL FILTER FAULT: '+str(f.fault),flush=True)
                if accepted:
                    commit_start=time.monotonic()
                    count=counter.increment()
                    APP_STATE['bill_trace'].committed(trace_row,time.monotonic()-commit_start)
                    with state_lock:io_state['nv9_pulses']=count
                    print(f'BILL PULSE ACCEPTED: total={count}',flush=True)
    finally:
        if reader:reader.close()
        with bill_lock:
            APP_STATE['bill_line']=None
            APP_STATE['bill_reader']=None
        line.release()
        if chip is not None:chip.reset()


def modbus_loop(
    cfg,
    controller,
    stop_event,
):
    print(
        f"Modbus: {controller.transport['device']} @ "
        f"{controller.transport['baud_rate']} 8N1",
        flush=True,
    )

    print(
        f"Slave: {controller.transport['slave_address']}",
        flush=True,
    )

    connected = False
    filters={item['name']:InputFilter(item.get('debounce_ms',0)) for item in cfg['inputs']}
    try:
        while not stop_event.is_set():
            poll_wait = 0.05
            try:
                if not connected:
                    if not controller.connect():
                        raise RuntimeError("Cannot open Modbus device")
                    controller.all_outputs_off()
                    connected = True
                raw = controller.read_inputs()

                logical = {}

                for index, item in enumerate(cfg["inputs"]):
                    value = raw[index]

                    if item.get("active_low", False):
                        value = not value

                    logical[item["name"]] = filters[item['name']].observe(value,time.monotonic())

                with output_test.lock:
                    update_output_state(controller)

                with state_lock:
                    io_state["raw_inputs"] = [
                        int(x) for x in raw
                    ]
                    io_state["inputs"] = logical
                    io_state["modbus_ok"] = True
                    io_state["last_poll_at"] = datetime.now(timezone.utc).isoformat()
                    io_state["last_poll_monotonic"] = time.monotonic()

            except Exception as exc:
                poll_wait = 1.0
                for filter_ in filters.values():filter_.reset()
                with state_lock:
                    io_state["modbus_ok"] = False

                connected = False
                APP_STATE["lease"].trip("modbus_error")
                with output_test.lock:
                    try:controller.all_outputs_off()
                    except Exception:pass
                print(
                    f"MODBUS ERROR: {exc}",
                    flush=True,
                )

            stop_event.wait(poll_wait)

    finally:
        # SAFETY: all outputs OFF on shutdown.
        try:controller.all_outputs_off()
        finally:controller.close()


APP_STATE = {}


def main():
    cfg = load_config()

    stop_event = threading.Event()
    pulse_counter = PulseJournal(os.getenv("NV9_JOURNAL_PATH", "/var/lib/sammoy-io/nv9.sqlite3"))
    APP_STATE["pulse_counter"] = pulse_counter
    io_state["nv9_pulses"] = pulse_counter.value()

    controller = ModbusController(cfg)
    APP_STATE["controller"] = controller
    APP_STATE["lease"] = ControllerLease(cfg.get("safety",{}).get("controller_watchdog_ms",2000))
    rfid = RfidReader(cfg.get("rfid", {}))
    APP_STATE["rfid"] = rfid
    rfid_thread = threading.Thread(
        target=rfid.run, args=(stop_event,), name="pn532-reader", daemon=True,
    )

    print(
        "SAMMOY 2.0 io-helper",
        flush=True,
    )

    print(
        "MODE: READ-WRITE WITH SAFETY",
        flush=True,
    )

    nv9_thread = threading.Thread(
        target=nv9_listener,
        args=(
            cfg,
            pulse_counter,
            stop_event,
        ),
        name="nv9-listener",
        daemon=True,
    )

    modbus_thread = threading.Thread(
        target=modbus_loop,
        args=(
            cfg,
            controller,
            stop_event,
        ),
        name="modbus-reader",
        daemon=True,
    )

    APP_STATE["nv9_enabled"] = cfg["bill_acceptor"].get("enabled", True) is not False
    APP_STATE["nv9_thread"] = nv9_thread
    def watchdog():
        while not stop_event.wait(.05):
            if APP_STATE["lease"].valid():continue
            with output_test.lock:
                if output_test.active is not None:continue
                try:
                    if any(controller.read_outputs()):
                        APP_STATE["lease"].trip("controller_watchdog")
                        controller.all_outputs_off();update_output_state(controller)
                except Exception:
                    with state_lock:io_state["modbus_ok"]=False
                    try:controller.all_outputs_off()
                    except Exception:pass
    watchdog_thread=threading.Thread(target=watchdog,name="controller-watchdog",daemon=True)
    watchdog_thread.start()
    if APP_STATE["nv9_enabled"]:
        nv9_thread.start()
    modbus_thread.start()
    rfid_thread.start()

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8080,
            log_level="info",
            access_log=False,
        )

    finally:
        print(
            "Stopping io-helper...",
            flush=True,
        )

        stop_event.set()

        if nv9_thread.ident is not None:
            nv9_thread.join(timeout=2)
        modbus_thread.join(timeout=3)
        rfid_thread.join(timeout=3)
        watchdog_thread.join(timeout=3)

        print(
            f"Stopped. NV9 total pulses: "
            f"{pulse_counter.value()}",
            flush=True,
        )


if __name__ == "__main__":
    main()
