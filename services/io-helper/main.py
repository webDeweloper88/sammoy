import os
import time
import yaml

from pymodbus.client import ModbusSerialClient


CONFIG_FILE = os.getenv("IO_CONFIG", "/config/io-map.yaml")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    transport = cfg["transport"]

    client = ModbusSerialClient(
        port=transport["device"],
        baudrate=transport["baud_rate"],
        bytesize=transport["data_bits"],
        parity="N",
        stopbits=transport["stop_bits"],
        timeout=transport["response_timeout_ms"] / 1000.0,
    )

    print("SAMMOY 2.0 io-helper")
    print("MODE: READ-ONLY")
    print(f"Modbus: {transport['device']} @ {transport['baud_rate']} 8N1")
    print(f"Slave: {transport['slave_address']}")

    if not client.connect():
        raise RuntimeError("Cannot open Modbus device")

    try:
        while True:
            result = client.read_discrete_inputs(
                address=0,
                count=8,
                slave=transport["slave_address"],
            )

            if result.isError():
                print(f"MODBUS ERROR: {result}")
            else:
                raw = result.bits[:8]

                logical = []
                for index, item in enumerate(cfg["inputs"]):
                    value = raw[index]
                    if item.get("active_low", False):
                        value = not value

                    logical.append((item["name"], value))

                print(
                    "RAW:",
                    [int(x) for x in raw],
                    "| LOGICAL:",
                    {name: value for name, value in logical},
                )

            time.sleep(1)

    finally:
        client.close()


if __name__ == "__main__":
    main()
