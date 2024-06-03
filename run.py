#!/usr/bin/env python3
import unittest
import argparse
import os
from fboss import Fboss
from argparse import RawTextHelpFormatter


def get_args():
    parser = argparse.ArgumentParser(
        prog="fboss_test",
        usage="%(prog)s [options]",
        description="FBOSS BSP Tests Command.",
        formatter_class=RawTextHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--cmd",
        default="iob_version",
        help="""bsp command sets. command list:
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
        firmware_upgrade
        all""",
    )
    args = parser.parse_args()

    return args


class TestFboss(unittest.TestCase):

    def setUp(self):
        self.fboss = Fboss("./fboss.json")

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

    def test_firmware_upgrade(self):
        self.fboss.fboss_firmware_test()


if __name__ == "__main__":
    args = get_args()
    if args.cmd == "all":
        cmd = f"python -m unittest run.TestFboss"
    else:
        cmd = f"python -m unittest run.TestFboss.test_{args.cmd}"

    os.system(cmd)
