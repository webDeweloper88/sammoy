from datetime import timedelta
import gpiod

CHIP = "/dev/gpiochip0"
LINE = 33

chip = gpiod.chip(CHIP, gpiod.chip.OPEN_BY_PATH)
line = chip.get_line(LINE)

config = gpiod.line_request()
config.consumer = "sammoy-nv9-test"
config.request_type = gpiod.line_request.EVENT_FALLING_EDGE
config.flags = gpiod.line_request.FLAG_BIAS_PULL_UP

line.request(config)

print(f"Watching {CHIP} line {LINE}")
print("Waiting for FALLING edges... Ctrl+C to stop.")

count = 0

try:
    while True:
        if line.event_wait(timedelta(seconds=1)):
            event = line.event_read()
            count += 1
            print(f"NV9 PULSE #{count}  timestamp={event.timestamp}")
except KeyboardInterrupt:
    print(f"\nStopped. Total pulses: {count}")
finally:
    line.release()
    chip.reset()
