#!/usr/bin/env python3

import unittest
import argparse
import os
import sys
from fboss import Fboss
from argparse import RawTextHelpFormatter


def arg_parser():

    cit_description = """
    CIT supports running following classes of tests:

    Running tests on target FBOSS: test pattern "test_*"
    Running tests on target FBOSS from outside BMC: test pattern "external_*"
    Running tests on target FBOSS from outside BMC: test pattern "external_fw_upgrade*"
    Running stress tests on target FBOSS: test pattern "stress_*"

    Usage Examples:
    On devserver:
    List tests : python cit_runner.py --platform wedge100 --list-tests --start-dir tests/
    List tests that need to connect to BMC: python cit_runner.py --platform wedge100 --list-tests --start-dir tests/ --external --host "NAME"
    List real upgrade firmware external tests that connect to BMC: python cit_runner.py --platform wedge100 --list-tests --start-dir tests/ --upgrade-fw
    Run tests that need to connect to BMC: python cit_runner.py --platform wedge100 --start-dir tests/ --external --bmc-host "NAME"
    Run real upgrade firmware external tests that connect to BMC: python cit_runner.py --platform wedge100 --run-tests "path" --upgrade --bmc-host "NAME" --firmware-opt-args="-f -v"
    Run single/test that need connect to BMC: python cit_runner.py --run-test "path" --external --host "NAME"

    On BMC:
    List tests : python cit_runner.py --platform wedge100 --list-tests
    Run tests : python cit_runner.py --platform wedge100
    Run single test/module : python cit_runner.py --run-test "path"
    """

    parser = argparse.ArgumentParser(
        prog="fboss_test",
        usage="%(prog)s [options]",
        epilog=cit_description, formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "--run-test",
        "-r",
        help="""Path to run a single test. Example:
            tests.wedge100.test_eeprom.EepromTest.test_odm_pcb""",
    )

    parser.add_argument(
        "-c",
        "--cmd",
        default="iob_version",
        help="""bsp command sets.
command list:
    iob_reset
    iob_uptime
    iob_general
    iob_scatch
    iob_version
    iob_info
    spi_udev
    spi_detect
    gpio
    i2c_udev
    i2c_detect
    i2c_buses
    port_led
    loop_leds
    xcvrs
    sensors
    hwmon
    firmware_upgrade
    all""",
    )

    return parser.parse_args()


class TestFboss(unittest.TestCase):

    def setUp(self):
        self.fboss = Fboss("./fboss_dvt.json")

    def test_iob_reset(self):
        self.fboss.iob_logic_reset_active()

    def test_iob_uptime(self):
        self.fboss.iob_up_time_test(5)

    def test_iob_general(self):
        self.fboss.iob_reg_raw_data_show()

    def test_iob_scatch(self):
        stat = self.fboss.iob_scratch_pad()

    def test_iob_version(self):
        self.fboss.show_version_info()

    def test_iob_info(self):
        self.fboss.show_fpga_info()

    def test_spi_udev(self):
        status = self.fboss.spi_bus_udev_test()

    def test_spi_detect(self):
        self.fboss.detect_spi_device()

    def test_i2c_udev(self):
        status = self.fboss.detect_i2c_drv_udev()

    def test_i2c_detect(self):
        self.fboss.detect_iob_i2c_buses()
        self.fboss.detect_doms_i2c_buses()

    def test_i2c_buses(self):
        self.fboss.detect_i2c_devices()

    def test_gpio(self):
        self.fboss.gpio_chip_test()

    def test_port_led(self):
        self.fboss.port_led_status_test()

    def test_loop_leds(self):
        self.fboss.port_led_loop_test()

    def test_xcvrs(self):
        self.fboss.fboss_xcvr_test()

    def test_sensors(self):
        self.fboss.fboss_sensor_test()
        self.fboss.fboss_end_flag_test()

    def test_hwmon(self):
         self.fboss.fboss_hwmon_test()

    def test_firmware_upgrade(self):
        self.fboss.fboss_firmware_test()


if __name__ == "__main__":
    #unittest.main(verbosity=2)
    args = arg_parser()

    if args.cmd == "all":
        cmd = f"python -m unittest runner.TestFboss"
    else:
        cmd = f"python -m unittest runner.TestFboss.test_{args.cmd}"

    os.system(cmd)
