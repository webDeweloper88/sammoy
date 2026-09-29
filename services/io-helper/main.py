import os
import threading
import time
from datetime import datetime, timezone
from output_test import OutputTest
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
        self.client = ModbusSerialClient(
            port=self.transport["device"],
            baudrate=self.transport["baud_rate"],
            bytesize=self.transport["data_bits"],
            parity="N",
            stopbits=self.transport["stop_bits"],
            timeout=self.transport["response_timeout_ms"] / 1000.0,
        )

        return self.client.connect()

    def close(self):
        with self.lock:
            if self.client is not None:
                self.client.close()

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

    def all_outputs_off(self):
        for name in self.output_names:
            try:
                self.write_output(name, False)
            except Exception as exc:
                print(
                    f"SAFETY: failed to switch {name} OFF: {exc}",
                    flush=True,
                )


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
    with state_lock:
        return {
            "inputs": dict(io_state["inputs"]),
            "raw_inputs": list(io_state["raw_inputs"]),
            "outputs": dict(io_state["outputs"]),
            "raw_outputs": list(io_state["raw_outputs"]),
            "nv9_pulses": io_state["nv9_pulses"],
            "last_poll_at": io_state["last_poll_at"],
            "test_output": output_test.active,
            "modbus_ok": io_state["modbus_ok"],
        }


@app.get("/rfid/latest")
def rfid_latest():
    return {"ok": True, **APP_STATE["rfid"].snapshot()}


@app.get("/rfid/events")
def rfid_events(since: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000)):
    return APP_STATE["rfid"].events_since(since, limit)


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

    if not modbus_ok:
        raise HTTPException(
            status_code=503,
            detail="Modbus is not available",
        )

    try:
        with output_test.lock:
            if command.on and output_test.active is not None:
                raise HTTPException(409, "An output test is running")
            actual = controller.write_output(name, command.on)

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

    if not controller.connect():
        print(
            "MODBUS ERROR: cannot open device",
            flush=True,
        )
        return

    try:
        # SAFETY: all outputs OFF at startup.
        controller.all_outputs_off()

        while not stop_event.is_set():

            try:
                raw = controller.read_inputs()

                logical = {}

                for index, item in enumerate(cfg["inputs"]):
                    value = raw[index]

                    if item.get("active_low", False):
                        value = not value

                    logical[item["name"]] = value

                update_output_state(controller)

                with state_lock:
                    io_state["raw_inputs"] = [
                        int(x) for x in raw
                    ]
                    io_state["inputs"] = logical
                    io_state["modbus_ok"] = True
                    io_state["last_poll_at"] = datetime.now(timezone.utc).isoformat()

            except Exception as exc:
                with state_lock:
                    io_state["modbus_ok"] = False

                print(
                    f"MODBUS ERROR: {exc}",
                    flush=True,
                )

            stop_event.wait(1.0)

    finally:
        # SAFETY: all outputs OFF on shutdown.
        controller.all_outputs_off()
        controller.close()


APP_STATE = {}


def main():
    cfg = load_config()

    stop_event = threading.Event()
    pulse_counter = PulseCounter()

    controller = ModbusController(cfg)
    APP_STATE["controller"] = controller
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

    APP_STATE["nv9_thread"] = nv9_thread
    nv9_thread.start()
    modbus_thread.start()
    rfid_thread.start()

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8080,
            log_level="info",
        )

    finally:
        print(
            "Stopping io-helper...",
            flush=True,
        )

        stop_event.set()

        nv9_thread.join(timeout=2)
        modbus_thread.join(timeout=3)
        rfid_thread.join(timeout=3)

        print(
            f"Stopped. NV9 total pulses: "
            f"{pulse_counter.value()}",
            flush=True,
        )


if __name__ == "__main__":
    main()
