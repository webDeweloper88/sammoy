import os
import time
import threading
from datetime import timedelta

import gpiod
import yaml
from pymodbus.client import ModbusSerialClient


CONFIG_FILE = os.getenv("IO_CONFIG", "/config/io-map.yaml")


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
                print(f"NV9 PULSE: total={count}", flush=True)

    finally:
        line.release()
        chip.reset()


def main():
    cfg = load_config()
    transport = cfg["transport"]

    stop_event = threading.Event()
    pulse_counter = PulseCounter()

    nv9_thread = threading.Thread(
        target=nv9_listener,
        args=(cfg, pulse_counter, stop_event),
        name="nv9-listener",
        daemon=True,
    )
    nv9_thread.start()

    client = ModbusSerialClient(
        port=transport["device"],
        baudrate=transport["baud_rate"],
        bytesize=transport["data_bits"],
        parity="N",
        stopbits=transport["stop_bits"],
        timeout=transport["response_timeout_ms"] / 1000.0,
    )

    print("SAMMOY 2.0 io-helper", flush=True)
    print("MODE: READ-ONLY", flush=True)
    print(
        f"Modbus: {transport['device']} @ "
        f"{transport['baud_rate']} 8N1",
        flush=True,
    )
    print(f"Slave: {transport['slave_address']}", flush=True)

    if not client.connect():
        stop_event.set()
        raise RuntimeError("Cannot open Modbus device")

    try:
        while True:
            result = client.read_discrete_inputs(
                address=0,
                count=8,
                slave=transport["slave_address"],
            )

            if result.isError():
                print(f"MODBUS ERROR: {result}", flush=True)
            else:
                raw = result.bits[:8]

                logical = {}
                for index, item in enumerate(cfg["inputs"]):
                    value = raw[index]

                    if item.get("active_low", False):
                        value = not value

                    logical[item["name"]] = value

                print(
                    "RAW:",
                    [int(x) for x in raw],
                    "| LOGICAL:",
                    logical,
                    "| NV9:",
                    pulse_counter.value(),
                    flush=True,
                )

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping io-helper...", flush=True)

    finally:
        stop_event.set()
        nv9_thread.join(timeout=2)
        client.close()

        print(
            f"Stopped. NV9 total pulses: {pulse_counter.value()}",
            flush=True,
        )


if __name__ == "__main__":
    main()
