import os
import threading
import time
from datetime import datetime, timezone
from output_test import OutputTest
from controller_lease import ControllerLease
from pulse_journal import PulseJournal
from input_filter import InputFilter
from datetime import timedelta

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
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    with state_lock:
        return {
            "inputs": dict(io_state["inputs"]),
            "raw_inputs": list(io_state["raw_inputs"]),
            "outputs": dict(io_state["outputs"]),
            "raw_outputs": list(io_state["raw_outputs"]),
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


def nv9_listener(cfg, counter, stop_event):
    bill = cfg["bill_acceptor"]
    if bill.get("enabled", True) is False:
        return

    chip_path = bill["gpio_chip"]
    line_number = bill["gpio_line"]

    chip = gpiod.chip(
        chip_path,
        gpiod.chip.OPEN_BY_PATH,
    )

    line = chip.get_line(line_number)

    request = gpiod.line_request()
    request.consumer = "sammoy-nv9"

    if bill.get("active_low", True):
        request.request_type = (
            gpiod.line_request.EVENT_FALLING_EDGE
        )
    else:
        request.request_type = (
            gpiod.line_request.EVENT_RISING_EDGE
        )

    if bill.get("gpio_bias") == "pull-up":
        request.flags = (
            gpiod.line_request.FLAG_BIAS_PULL_UP
        )

    line.request(request)

    print(
        f"NV9: watching {chip_path} line {line_number}",
        flush=True,
    )

    try:
        while not stop_event.is_set():
            if line.event_wait(timedelta(seconds=1)):
                line.event_read()

                count = counter.increment()

                with state_lock:
                    io_state["nv9_pulses"] = count

                print(
                    f"NV9 PULSE: total={count}",
                    flush=True,
                )

    finally:
        line.release()
        chip.reset()


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
