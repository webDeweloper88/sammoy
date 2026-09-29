import gpiod

CHIP = "/dev/gpiochip0"
LINE = 33

chip = gpiod.chip(CHIP, gpiod.chip.OPEN_BY_PATH)
line = chip.get_line(LINE)

config = gpiod.line_request()
config.consumer = "sammoy-gpio-test"
config.request_type = gpiod.line_request.DIRECTION_INPUT

line.request(config)

value = line.get_value()
print(f"{CHIP} line {LINE} = {value}")

line.release()
chip.reset()
