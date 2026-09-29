import os
import threading
from datetime import timedelta

import gpiod
import yaml
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymodbus.client import ModbusSerialClient


CONFIG_FILE = os.getenv("IO_CONFIG", "/config/io-map.yaml")

app = FastAPI(title="SAMMOY 2.0 io-helper")

state_lock = threading.Lock()

io_state = {
    "inputs": {},
    "raw_inputs": [],
    "outputs": {},
    "raw_outputs": [],
    "nv9_pulses": 0,
    "modbus_ok": False,
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
            "modbus_ok": io_state["modbus_ok"],
        }


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
        actual = controller.write_output(
            name,
            command.on,
        )

        update_output_state(controller)

        return {
            "ok": True,
            "output": name,
            "requested": command.on,
            "actual": actual,
        }

    except Exception as exc:
        with state_lock:
            io_state["modbus_ok"] = False

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )


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
        print(
            "Stopping io-helper...",
            flush=True,
        )

        stop_event.set()

        nv9_thread.join(timeout=2)
        modbus_thread.join(timeout=3)

        print(
            f"Stopped. NV9 total pulses: "
            f"{pulse_counter.value()}",
            flush=True,
        )


if __name__ == "__main__":
    main()
