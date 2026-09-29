import time

from pn532_linux import LinuxI2cPn532


BUS = 7
ADDRESS = 0x24

print(f"Opening PN532 on /dev/i2c-{BUS}, address 0x{ADDRESS:02X}")

reader = None

try:
    reader = LinuxI2cPn532(BUS, ADDRESS)

    print("Reading firmware...")
    firmware = reader.firmware_version
    print("PN532 firmware:", firmware)

    print("Sending SAM_configuration...")
    reader.SAM_configuration()
    print("PN532 ONLINE")

    print("Bring NFC card to reader...")
    print("Ctrl+C to stop")

    while True:
        uid = reader.read_passive_target(timeout=0.5)

        if uid is not None:
            print("CARD UID:", bytes(uid).hex().upper())
            time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")

except Exception as exc:
    print("PN532 ERROR:", repr(exc))
    raise

finally:
    if reader is not None:
        reader.close()
