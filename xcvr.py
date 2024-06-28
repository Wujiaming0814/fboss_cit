import os
from fboss_utils import read_sysfile_value, write_sysfile_value

XCVR_SUCCESS = "success"
XCVR_ERR_1 = "NO udev link path: {}"
XCVR_ERR_2 = "SET value failed {}"
XCVR_ERR_3 = "NOT find {} link file, udev mapping or driver error"

BASE_VALUE = "0x0"
XCVR_UDEV_PATH = "/run/devmap/xcvrs/"

def check_xcvr_drv_udev(device):
    """Check xcvr driver and udev status."""
    xcvr_file = os.path.join(XCVR_UDEV_PATH, device)
    if not os.path.exists(xcvr_file):
        return False, XCVR_ERR_1.format(xcvr_file)
    if not os.path.islink(xcvr_file):
        return False, XCVR_ERR_3.format(xcvr_file)
    if not os.readlink(xcvr_file):
        return False, XCVR_ERR_3.format(xcvr_file)

    return True, XCVR_SUCCESS

def get_xcvr_value(device):
    """Read xcvr status."""
    devfile = os.path.join(XCVR_UDEV_PATH, device)
    value = read_sysfile_value(devfile)
    if not value:
        return False, XCVR_ERR_1.format(devfile)

    return True, value

def set_xcvr_value(device, set_value):
    """Set xcvr status."""
    devfile = os.path.join(XCVR_UDEV_PATH, device)
    stat, _ = write_sysfile_value(devfile, int(set_value, 16))
    if not stat:
        return XCVR_ERR_2.format(devfile)

    return XCVR_SUCCESS

def xcvr_object_validate(xcvr_item):
    """Validate xcvr object mode."""
    stat, ret = check_xcvr_drv_udev(xcvr_item)
    if not stat:
        return ret, []

    stat, default_val = get_xcvr_value(xcvr_item)
    if not stat:
        return XCVR_ERR_1.format(xcvr_item), []

    # Save default value
    set_val = "0x1" if default_val == BASE_VALUE else "0x0"
    ret = set_xcvr_value(xcvr_item, set_val)
    if ret != XCVR_SUCCESS:
        return ret, []

    # Setup new value to switch xcvr object mode
    stat, new_val = get_xcvr_value(xcvr_item)
    if not stat:
        return XCVR_ERR_1.format(xcvr_item), []

    # Compare switch mode correct
    if int(new_val, 16) != int(set_val, 16):
        return XCVR_ERR_2.format(set_val), []

    # Restore default value
    ret = set_xcvr_value(xcvr_item, default_val)
    if ret != XCVR_SUCCESS:
        return ret, []

    return XCVR_SUCCESS, [default_val, new_val]

def xcvr_test(port_num):
    """Xcvr management test function."""
    print(
        "-------------------------------------------------------------------------\n"
        "  PORT ID  |   XCVR UDEV NAME   |  Default Value  |  Test Value  | Status\n"
        "-------------------------------------------------------------------------"
    )
    for mode in ("xcvr_low_power", "xcvr_reset"):
        for i in range(port_num):
            xcvr_item = f"xcvr_{i + 1}/{mode}_{i + 1}"
            ret, res = xcvr_object_validate(xcvr_item)
            status = "PASS"
            if ret != XCVR_SUCCESS:
                res = ["NA", "NA"]
                status = "\033[31mFAIL\033[0m\t" + f"{ret}"
            print(
                f'{"":>4}{i:>2}{"":>9}{xcvr_item.split("/")[1]:<18}{"":>7}{res[0]:<3}{"":>12}'
                + f'{res[1]:<3}{"":>9}{status.ljust(1)} \n',
                end="",
            )

    return XCVR_SUCCESS

if __name__ == "__main__":
    xcvr_test(33)
