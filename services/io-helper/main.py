import os
import time
import threading
from datetime import timedelta

import gpiod
import yaml
import uvicorn
from fastapi import FastAPI
from pymodbus.client import ModbusSerialClient


CONFIG_FILE = os.getenv("IO_CONFIG", "/config/io-map.yaml")

app = FastAPI(title="SAMMOY 2.0 io-helper")

state_lock = threading.Lock()
io_state = {
    "inputs": {},
    "raw_inputs": [],
    "nv9_pulses": 0,
    "modbus_ok": False,
}


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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


@app.get("/health")
def health():
    with state_lock:
        return {
            "status": "ok",
            "modbus_ok": io_state["modbus_ok"],
        }


@app.get("/io")
def get_io():
    with state_lock:
        return {
            "inputs": dict(io_state["inputs"]),
            "raw_inputs": list(io_state["raw_inputs"]),
            "nv9_pulses": io_state["nv9_pulses"],
            "modbus_ok": io_state["modbus_ok"],
        }


def nv9_listener(cfg, counter, stop_event):
    bill = cfg["bill_acceptor"]

    chip_path = bill["gpio_chip"]
    line_number = bill["gpio_line"]

    chip = gpiod.chip(chip_path, gpiod.chip.OPEN_BY_PATH)
    line = chip.get_line(line_number)

    request = gpiod.line_request()
    request.consumer = "sammoy-nv9"

    if bill.get("active_low", True):
        request.request_type = gpiod.line_request.EVENT_FALLING_EDGE
    else:
        request.request_type = gpiod.line_request.EVENT_RISING_EDGE

    if bill.get("gpio_bias") == "pull-up":
        request.flags = gpiod.line_request.FLAG_BIAS_PULL_UP

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

                print(f"NV9 PULSE: total={count}", flush=True)

    finally:
        line.release()
        chip.reset()


def modbus_loop(cfg, stop_event):
    transport = cfg["transport"]

    client = ModbusSerialClient(
        port=transport["device"],
        baudrate=transport["baud_rate"],
        bytesize=transport["data_bits"],
        parity="N",
        stopbits=transport["stop_bits"],
        timeout=transport["response_timeout_ms"] / 1000.0,
    )

    print(
        f"Modbus: {transport['device']} @ "
        f"{transport['baud_rate']} 8N1",
        flush=True,
    )
    print(f"Slave: {transport['slave_address']}", flush=True)

    if not client.connect():
        with state_lock:
            io_state["modbus_ok"] = False
        print("MODBUS ERROR: cannot open device", flush=True)
        return

    try:
        while not stop_event.is_set():
            result = client.read_discrete_inputs(
                address=0,
                count=8,
                slave=transport["slave_address"],
            )

            if result.isError():
                with state_lock:
                    io_state["modbus_ok"] = False

                print(f"MODBUS ERROR: {result}", flush=True)

            else:
                raw = result.bits[:8]

                logical = {}
                for index, item in enumerate(cfg["inputs"]):
                    value = raw[index]

                    if item.get("active_low", False):
                        value = not value

                    logical[item["name"]] = value

                with state_lock:
                    io_state["raw_inputs"] = [int(x) for x in raw]
                    io_state["inputs"] = logical
                    io_state["modbus_ok"] = True

            time.sleep(1)

    finally:
        client.close()


def main():
    cfg = load_config()
    stop_event = threading.Event()
    pulse_counter = PulseCounter()

    print("SAMMOY 2.0 io-helper", flush=True)
    print("MODE: READ-ONLY", flush=True)

    nv9_thread = threading.Thread(
        target=nv9_listener,
        args=(cfg, pulse_counter, stop_event),
        name="nv9-listener",
        daemon=True,
    )

    modbus_thread = threading.Thread(
        target=modbus_loop,
        args=(cfg, stop_event),
        name="modbus-reader",
        daemon=True,
    )

    nv9_thread.start()
    modbus_thread.start()

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8080,
            log_level="info",
        )

    finally:
        print("Stopping io-helper...", flush=True)
        stop_event.set()

        nv9_thread.join(timeout=2)
        modbus_thread.join(timeout=2)

        print(
            f"Stopped. NV9 total pulses: {pulse_counter.value()}",
            flush=True,
        )


if __name__ == "__main__":
    main()
