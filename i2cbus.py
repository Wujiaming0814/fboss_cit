"""Module providing i2c bus and devices test function."""

#!/bin/python

import os
from fboss_utils import *

DEVMAP_I2C = "/run/devmap/i2c-busses/"
I2C_DRV = "/sys/class/i2c-adapter/"
DEVMAP_XCVR_REST = "/run/devmap/xcvrs"
RESET_STATUS = {"hold": "0x0", "reset": "0x1"}


def parse_dev_udev() -> dict:
    devs_dict = {}
    i2c_udev_list = os.listdir(DEVMAP_I2C)
    if not i2c_udev_list:
        return False, "\033[31m FAIL\033[0m\tNo I2C udev devices."

    for dev in i2c_udev_list:
        file = os.readlink(f"{DEVMAP_I2C}{dev}")
        devid = os.path.basename(file)
        devs_dict.update({dev: devid})

    return devs_dict


def parse_sort_drv_devices(source_list):
    sort_list = []
    for i2cdev in source_list:
        adapter_info = os.readlink(f"{I2C_DRV}{i2cdev}").split("/")
        master_info = adapter_info[6].split(".")[1]
        masterid = adapter_info[6].split(".")[2]
        sort_list.append([master_info, int(masterid)])

    return sorted(sort_list)


def check_drv_udev_status():
    """check i2c bus driver and udev"""
    i2c_dev_list = os.listdir(I2C_DRV)
    if not i2c_dev_list:
        return False, "\033[31m FAIL\033[0m\tNo I2C bus, i2c driver error."
    # remove come module i2c buses
    i2c_dev_list.remove("i2c-0")
    i2c_dev_list.remove("i2c-1")
    if not i2c_dev_list:
        return False, "\033[31m FAIL\033[0m\tNo I2C bus, i2c driver error."

    devs_list = parse_sort_drv_devices(i2c_dev_list)

    for i2cdev in devs_list:
        masterid = i2cinfo = udev_info = master_info = "NA"
        status = "PASS"
        stat = True
        dev_info = f"fbiob_pci.{i2cdev[0]}.{i2cdev[1]}"
        for i2cinfo in i2c_dev_list:
            if not os.path.islink(f"{I2C_DRV}{i2cinfo}"):
                stat = False
                status = "\033[31m FAIL\033[0m\tNo Master device."
            adapter_info = os.readlink(f"{I2C_DRV}{i2cinfo}").split("/")[-2]
            if adapter_info == dev_info:
                master_info = adapter_info.split(".")[1]
                masterid = master_info.split("_")[0].upper()
            else:
                continue

            devs_dict = parse_dev_udev()
            for item in devs_dict.items():
                if item[1] == i2cinfo:
                    udev_info = item[0]
            print(
                f'  {masterid:<5}{"":2}{i2cinfo:<6}{"":3}{adapter_info:<30}'
                + f'{"":3}{udev_info:15} {status:<5}  \n',
                end="",
            )

    return stat, status


def get_i2c_bus_id(bus_name) -> int:
    """get i2c bus id"""
    busid = -1
    dev_name = f"{DEVMAP_I2C}{bus_name}"
    if not os.path.exists(dev_name):
        return busid
    chardev = os.readlink(dev_name)
    if os.path.exists(chardev):
        bus_info = os.path.basename(chardev)
        bus_id = bus_info.split("-")
        busid = bus_id[1]

    return busid


def detect_i2c_devices(bus_info):
    busid = get_i2c_bus_id(bus_info)
    cmd = f"i2cdetect -y -a {busid}"
    os.system(cmd)


def list_difference(list1, list2):
    """compare two lists"""
    status = True
    temp1, temp2 = [], []

    if list1:
        for item in list1:
            temp1.append(int(item, 16))
    if list2:
        for item in list2:
            temp2.append(int(item, 16))

    if [i for i in temp1 + temp2 if i not in temp1 or i not in temp2]:
        status = False
    return status


def list_i2c_devices(_busid: int) -> list:
    """detect devices under i2c bus"""
    addr_list, devices_list = [], []
    busid = f"{_busid}"
    cmd = f"i2cdetect -y -a {busid}"
    _, i2cdevs = execute_shell_cmd(cmd)
    if not _:
        print(f"Scan Bus {busid} failed.")
        return addr_list

    for line in i2cdevs.strip().splitlines()[1:]:
        temp_list = line.split()
        addr_list += temp_list[1:]

    for addr in range(3, len(addr_list)):
        if addr_list[addr] != "--":
            if addr_list[addr] == "UU":
                cmd = f"i2cget -y -f -a {busid} {hex(addr)}"
                _, i2cdevs = execute_shell_cmd(cmd)
                if _:
                    devices_list.append(hex(addr))
                else:
                    print(f"Bus:{busid} dev:{hex(addr)} read failed.")
            else:
                devices_list.append(hex(int(addr_list[addr], 16)))
    return devices_list


def get_reset_status(chanid):
    """get reset status"""
    devfile = f"{DEVMAP_XCVR_REST}/xcvr_{chanid}/xcvr_reset_{chanid}"
    value = read_sysfile_value(devfile)
    if not value:
        return None

    return f'{"Yes" if value== "0x0" else "No"}'


def enable_reset(chanid):
    """enable reset status"""
    devfile = f"{DEVMAP_XCVR_REST}/xcvr_{chanid}/xcvr_reset_{chanid}"
    value = get_reset_status(chanid)
    if not value:
        return "FAIL"

    if value == "Yes":
        return "SUCCESS"

    stat, _ = write_sysfile_value(devfile, int(RESET_STATUS.get("reset"), 16))
    if not stat:
        return "FAIL"

    value = get_reset_status(chanid)
    if not value:
        return None

    if value == "No":
        return "FAIL"

    return "SUCCESS"


def read_present_value(platform, devid):
    devfile = f"/run/devmap/cplds/SMB_CPLD/xcvr_present_{devid}"
    if platform == "tahan" or platform == "janga":
        devfile = f"/run/devmap/cplds/SMB_CPLD_2/xcvr_present_{devid}"

    if not os.path.exists(devfile):
        return "No"

    value = read_sysfile_value(devfile)
    if not value:
        return None

    present = value.split("\n")

    return f'{"Yes" if present == "0x1" else "No"}'


def scan_verify_i2c_bus(platform, fpga_type, bus_info, dev_map=None):
    """detect devices and compare"""
    status, reset = "PASS", "No"
    sta_info = "Scan I2C Buses sussesful."
    expect_devs, sdevices = "", ""
    devices_list, expect_list = [], []
    chanid = bus_info.split("_")[-1]

    if fpga_type == "DOM":
        devid = bus_info.split("_")[-1]
        present = read_present_value(platform, devid)
        if present == "Yes":
            ret = enable_reset(devid)
            if ret == "SUCCESS":
                reset = "Yes"

    bus_id = get_i2c_bus_id(bus_info)
    if int(bus_id) >= 0:
        devices_list = list_i2c_devices(bus_id)
    else:
        status = "\033[31m FAIL\033[0m"
        sta_info = f"Get Bus [{chanid}] with udev [{bus_info}] failed."

    if not devices_list:
        sdevices = "NULL"
    else:
        for dev in devices_list:
            sdevices += "".join([f"{dev} "])

    if dev_map:
        if fpga_type == "DOM":
            reset = get_reset_status(devid)
            expect_list = dev_map
            if present == "Yes" and reset == "Yes":
                if not list_difference(devices_list, expect_list):
                    status = "\033[31m FAIL\033[0m"
                    sta_info = "Scan devices not match system."
        else:
            expect_list = dev_map.get(bus_info)
            if not list_difference(devices_list, expect_list):
                status = "\033[31m FAIL\033[0m"
                sta_info = "Scan devices not match system."

    if fpga_type == "DOM":
        print(
            f' {status:>5}  {chanid:>5}  {bus_id:>6}{"":5}{bus_info.ljust(7)}'
            + f'{"":3}{present.ljust(7)} {present.ljust(7)}'
            + f"{reset.ljust(5)} {sdevices.ljust(1)} \n",
            end="",
        )
        if dev_map and expect_list:
            for test_dev in expect_list:
                expect_devs += "".join([f"{test_dev} "])
            print(f'{"":56} {expect_devs.ljust(1)}{"[test dev]"} \n', end="")
        else:
            print(f'{"":56} {"[NA]":>4s} {"[test dev]"} \n', end="")
    else:
        print(
            f' {status:>5}  {chanid:>5}  {bus_id:>6}{"":5}'
            + f"{bus_info.ljust(16)}  {sdevices.ljust(1)} \n",
            end="",
        )
        if dev_map and expect_list:
            for test_dev in expect_list:
                expect_devs += "".join([f"{test_dev} "])
            print(f'{"":43} {expect_devs.ljust(1)}{"[test dev]"} \n', end="")
        else:
            print(f'{"":43} {"[NA]":>4s} {"[test dev]"} \n', end="")

    return status, sta_info


if __name__ == "__main__":
    scan_verify_i2c_bus()
