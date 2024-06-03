"""gpio module"""

import os
import re
from fboss_utils import execute_shell_cmd
import i2cbus

GPIO_SUCCESS = "success"
GPIO_ERR_1 = "No fbiob GPIO device"
GPIO_ERR_2 = "No device link in this path : /run/devmap/ {}"
GPIO_ERR_3 = "please input high or low"
GPIO_ERR_4 = "GPIO set failed"


def detect_gpio_devmap_device():
    """detect gpio udev"""
    stat, _ = get_gpiochipnumber()
    if not stat:
        return GPIO_ERR_1

    gpio_udev = "/run/devmap/gpio/IOB_GPIO_CHIP_0"
    if not os.path.exists(gpio_udev):
        return GPIO_ERR_2.format("IOB_GPIO_CHIP_0")

    return GPIO_SUCCESS


def get_gpiochipnumber():
    """get gpio pin number"""
    cmd = "gpiodetect"
    pattern = re.compile(r"fbiob_pci.gpiochip.0")
    stat, value = execute_shell_cmd(cmd)
    if not stat:
        return stat, GPIO_ERR_1

    for line in value.splitlines():
        result = pattern.findall(line)
        if result:
            gpiochip = line.split("[")[0]
            break

    if "result" not in dir():
        return False, GPIO_ERR_1

    return stat, gpiochip


def set_gpio_output(gpiochip, pingnumber, write):
    """get gpio pin direction"""
    if write == "high":
        value = 1
    elif write == "low":
        value = 0
    else:
        return GPIO_ERR_3

    cmd = f"gpioset {gpiochip} {pingnumber}={value}"
    stat, _ = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_4

    return GPIO_SUCCESS


def set_gpio_input(gpiochip, pinnum):
    """set gpiochip pin direction as input"""
    cmd = f"gpioget {gpiochip} {pinnum}"
    stat, _ = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_1

    return GPIO_SUCCESS


def check_gpio_direction(gpiochip, pinnum):
    """check gpiochip pin directtion"""
    cmd = f"gpioinfo {gpiochip}"
    stat, value = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_1

    return value.splitlines()[pinnum + 1].split()[4]


def check_set_gpio_output_success():
    """test gpio control function"""
    bus_info = "/run/devmap/i2c-busses/IOB_I2C_BUS_6"
    if not os.path.exists(bus_info):
        return GPIO_ERR_2.format("IOB_I2C_BUS_6")

    i2c_number = i2cbus.get_i2c_bus_id("IOB_I2C_BUS_6")
    cmd = f"i2cget -y -f -a {i2c_number} 0x50"
    stat, _ = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_4

    return GPIO_SUCCESS


def test_gpio_pin_direction(gpiochip, pinnum):
    """test gpio pin setup and verify status"""
    status = "FAIL"
    _direction = ""
    set_gpio_output(gpiochip, pinnum, "high")
    _direction = check_gpio_direction(gpiochip, pinnum)
    if _direction == "output":
        status = "PASS"

    return status, _direction


def test_gpio(platform):
    """test gpio function"""
    stat, gpiochip = get_gpiochipnumber()
    if not stat:
        return GPIO_ERR_1

    ret = detect_gpio_devmap_device()
    if ret != GPIO_SUCCESS:
        return ret

    if platform == "janga" or platform == "tahan":
        # pin 55 test
        ret = set_gpio_output(gpiochip, 55, "high")
        if ret != GPIO_SUCCESS:
            return ret

        ret = check_set_gpio_output_success()
        if ret != GPIO_SUCCESS:
            return ret

        ret = set_gpio_input(gpiochip, 55)
        if ret != GPIO_SUCCESS:
            return ret

    print(
        "  GPIO CHIP | PIN ID | Default Directtion | Directtion Test | Status\n"
        "-------------------------------------------------------------------------"
    )
    default_direction = ""
    for i in range(72):
        default_direction = check_gpio_direction(gpiochip, i)
        status, direction = test_gpio_pin_direction(gpiochip, i)
        print(
            f'{"":2}{gpiochip:>5} {i:>5d}{"":5}{default_direction:>10s}'
            + f'{"":15}{direction:>6}{"":8}{status.ljust(1)} \n',
            end="",
        )
        set_gpio_input(gpiochip, i)

    return GPIO_SUCCESS


if __name__ == "__main__":
    test_gpio()
