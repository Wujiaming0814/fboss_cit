import os
import subprocess
from fboss_utils import read_sysfile_value, write_sysfile_value, get_platform
import fboss

# Constants for sensor status and error messages
SENSOR_SUCCESS = "success"
SENSOR_ERR_1 = "name is NULL"
SENSOR_ERR_2 = "physical channel is NULL"
SENSOR_ERR_3 = "No device link in this path: /run/devmap/sensors [{}]"
SENSOR_ERR_4 = "ERROR platform, please check: [{}]"
SENSOR_ERR_5 = "ERROR EVT VERSION, please check: [{}]"
SENSOR_ERR_6 = "chip id is NULL"
SENSOR_ERR_7 = "not match: [{}]"
SENSOR_ERR_8 = "data NULL"
SENSOR_ERR_9 = "chip id not match: [{}] [{}]"
SENSOR_ERR_10 = "NOT find [{}] link file, udev mapping or driver error"

# Define paths and constants
HWMON_PATH = "/sys/class/hwmon/"
TABLE_FLAG = "-----+-----+-----+-----+"
SKIP = "SMB_U19_LM75B_1"

# Sensor data structure (more organized)
class Sensor:
    def __init__(self, udev_link, chip_id, kernel_info, device1, device2):
        self.udev_link = udev_link
        self.chip_id = chip_id
        self.kernel_info = kernel_info
        self.device1 = device1
        self.device2 = device2

# Sensor data for different platforms
TAHAN_SENSOR = [
    # udev link:chip id:kernel info:device:device
    "SMB_J28_PMBUS_2:0061:fbiob iob_i2c_master.21 at 0xfb505500:power1_input:temp1_input",
    "SMB_U206_ADC128D818_2:001d:fbiob iob_i2c_master.25 at 0xfb505900:in0_input:in1_input",
    "SMB_U20_MP2975_1:007e:fbiob iob_i2c_master.10 at 0xfb504a00:curr1_input:power1_input",
    "SMB_U279_ADM1272_1:0010:fbiob iob_i2c_master.21 at 0xfb505500:curr1_input:power1_input",
    "SMB_U57_LM75B_2:0049:fbiob iob_i2c_master.16 at 0xfb505000:temp1_input:temp1_max",
    "SMB_U6_ADC128D818_3:0035:fbiob iob_i2c_master.26 at 0xfb505a00:in0_input:in1_input",
    "SMB_U86_MP2975_2:007d:fbiob iob_i2c_master.10 at 0xfb504a00:curr1_input:power1_input",
    "SMB_J28_LM75B_1:0048:fbiob iob_i2c_master.21 at 0xfb505500:temp1_input:temp1_max",
    "SMB_U122_PMBUS_1:0076:fbiob iob_i2c_master.3 at 0xfb504300:curr1_input:power1_input",
    "SMB_U207_ADC128D818_3:0035:fbiob iob_i2c_master.25 at 0xfb505900:in0_input:in1_input",
    "SMB_U21_ADC128D818_2:001d:fbiob iob_i2c_master.26 at 0xfb505a00:in0_input:temp1_input",
    "SMB_U39_LM75B_1:0048:fbiob iob_i2c_master.24 at 0xfb505800:temp1_input:temp1_max",
    "SMB_U67_LM75B_2:0049:fbiob iob_i2c_master.12 at 0xfb504c00:temp1_input:temp1_max",
    "SMB_U77_LM75B_1:0048:fbiob iob_i2c_master.20 at 0xfb505400:temp1_input:temp1_max",
    "SMB_U92_MP2975_2:007b:fbiob iob_i2c_master.11 at 0xfb504b00:curr1_input:power1_input",
    "SMB_J28_PMBUS_1:0060:fbiob iob_i2c_master.21 at 0xfb505500:curr1_input:power1_input",
    "SMB_U182_LM75B_2:0049:fbiob iob_i2c_master.24 at 0xfb505800:temp1_input:temp1_max",
    "SMB_U208_ADC128D818_1:0037:fbiob iob_i2c_master.25 at 0xfb505900:in0_input:temp1_input",
    "SMB_U229_MP2975_1:007a:fbiob dom1_i2c_master.11 at 0xfb542b00:curr1_input:power1_input",
    "SMB_U51_LM75B_1:0048:fbiob dom1_i2c_master.16 at 0xfb543000:temp1_input:temp1_max",
    "SMB_U69_LM75B_1:0048:fbiob dom1_i2c_master.12 at 0xfb542c00:temp1_input:temp1_max",
    "SMB_U7_ADC128D818_1:0037:fbiob dom1_i2c_master.26 at 0xfb543a00:in0_input:temp1_input",
]

J3_SENSOR = [
    # udev link:chip id:kernel info
    "SMB_U19_LM75B_1:0048:fbiob iob_i2c_master.1 at 0xfb504100:temp1_input:temp1_max",
    "SMB_U72_LM75B_1:0048:fbiob iob_i2c_master.3 at 0xfb504300:temp1_input:temp1_max",
    "SMB_U229_MP2975_1:007a:fbiob iob_i2c_master.3 at 0xfb504300:curr1_input:power1_input",
    "SMB_U237_MP2975_2:007d:fbiob dom1_i2c_master.3 at 0xfb542300:curr1_input:power1_input",
    "SMB_U17_LM75B_1:0049:fbiob iob_i2c_master.4 at 0xfb504400:temp1_input:temp1_max",
    "SMB_U25_LM75B_2:004a:fbiob iob_i2c_master.4 at 0xfb504400:temp1_input:temp1_max",
    "SMB_U210_MP2975_1:0076:fbiob iob_i2c_master.10 at 0xfb504a00:curr1_input:power1_input",
    "SMB_U347_MP2975_2:007a:fbiob iob_i2c_master.10 at 0xfb504a00:curr1_input:power1_input",
    "SMB_U92_MP2975_3:007b:fbiob iob_i2c_master.10 at 0xfb504a00:curr1_input:power1_input",
    "SMB_U216_MP2975_4:007e:fbiob iob_i2c_master.10 at 0xfb504a00:curr1_input:power1_input",
    "SMB_U337_PMBUS_1:0060:fbiob iob_i2c_master.11 at 0xfb504b00:power1_input:temp1_input",
    "SMB_U177_PMBUS_2:0076:fbiob iob_i2c_master.11 at 0xfb504b00:power1_input:temp1_input",
    "SMB_U343_MP2975_1:007b:fbiob iob_i2c_master.11 at 0xfb504b00:curr1_input:power1_input",
    "SMB_U86_MP2975_2:007d:fbiob iob_i2c_master.11 at 0xfb504b00:curr1_input:power1_input",
    "SMB_U16_LM75B_1:0048:fbiob iob_i2c_master.12 at 0xfb504c00:temp1_input:temp1_max",
    "SMB_U15_LM75B_2:0049:fbiob iob_i2c_master.12 at 0xfb504c00:temp1_input:temp1_max",
    "SMB_U279_ADM1272_1:0010:fbiob iob_i2c_master.21 at 0xfb505500:curr1_input:power1_input",
    "SMB_U1_LM75B_1:0048:fbiob iob_i2c_master.21 at 0xfb505500:temp1_input:temp1_max",
    "SMB_U104_LM75B_2:004a:fbiob iob_i2c_master.21 at 0xfb505500:temp1_input:temp1_max",
    "SMB_PS1_PMBUS_1:0060:fbiob iob_i2c_master.21 at 0xfb505500:curr1_input:temp1_input",
    "SMB_PS2_PMBUS_2:0061:fbiob iob_i2c_master.21 at 0xfb505500:curr1_input:temp1_input",
    "SMB_U355_ADC128D818_1:0037:fbiob iob_i2c_master.22 at 0xfb505600:in0_input:in1_input",
    "SMB_U356_ADC128D818_1:0037:fbiob iob_i2c_master.24 at 0xfb505800:in0_input:in1_input",
    "SMB_U360_ADC128D818_2:001d:fbiob iob_i2c_master.24 at 0xfb505800:in0_input:in1_input",
    "SMB_U361_ADC128D818_1:0037:fbiob iob_i2c_master.25 at 0xfb505900:in0_input:in1_input",
    "SMB_U357_ADC128D818_2:001d:fbiob iob_i2c_master.25 at 0xfb505900:in0_input:in1_input",
    "SMB_U354_ADC128D818_1:0037:fbiob iob_i2c_master.26 at 0xfb505a00:in0_input:in1_input",
    "SMB_U288_ADC128D818_2:001d:fbiob iob_i2c_master.26 at 0xfb505a00:in0_input:in1_input",
    "SMB_U353_ADC128D818_3:001f:fbiob iob_i2c_master.26 at 0xfb505a00:in0_input:in1_input",
]

def check_file_type(path):
    """
    Checks the file type of a given path.

    Args:
        path: The path to the file.

    Returns:
        True if the path is a file, False if it's a directory, None if it doesn't exist.
    """

    if not os.path.exists(path):
        return None

    return os.path.isfile(path)

def get_subdirectories(path):
    """
    Recursively collects all subdirectories within a given path.

    Args:
        path: The path to start the search from.

    Returns:
        A list of all subdirectories found within the given path.
    """

    subdirectories = []
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if os.path.isdir(item_path):
            subdirectories.append(item_path)
    return subdirectories

def get_device_name(path):
    """
    Gets the device name from the 'name' file within a given path.

    Args:
        path: The path to the directory containing the 'name' file.

    Returns:
        The device name as a string, or None if the 'name' file doesn't exist.
    """

    dev_path = os.path.join(path, "name")
    if not os.path.exists(dev_path):
        return None

    with open(dev_path, "r") as f:
        dev_name = f.read().strip()
    return dev_name

def sensors_folder_list():
    """
    Lists all sensor folders within the HWMON_PATH.

    This function is currently unused and can be removed if not needed.
    """

    sensors_list = get_subdirectories(HWMON_PATH)
    for item in sensors_list:
        item_path = os.path.join(HWMON_PATH, item)
        name = get_device_name(item_path)

def check_sensor_physical_channel(name, chip_id, channel):
    """
    Checks if the sensor's physical channel is accessible.

    Args:
        name: The name of the sensor.
        chip_id: The chip ID of the sensor.
        channel: The physical channel (e.g., "i2c-1").

    Returns:
        A tuple containing the status (SENSOR_SUCCESS or error message) and the bus ID.
    """

    status = SENSOR_SUCCESS
    busid = -1

    if name == "":
        return SENSOR_ERR_1, busid

    if chip_id == "":
        status = SENSOR_ERR_6

    if channel == "":
        status = SENSOR_ERR_2

    devfile = f"/run/devmap/sensors/{name}/device"
    if not os.path.exists(devfile):
        return SENSOR_ERR_3.format(name), busid

    value = os.readlink(devfile)
    arr = value.split("-")
    chipid = arr[1].rstrip()
    bus = arr[0]

    if chip_id != chipid:
        status = SENSOR_ERR_9.format(chipid, chip_id)

    arr = bus.split("/")
    busid = arr[3]

    # Use subprocess for more reliable shell command execution
    cmd = f"i2cdetect -l | grep {channel} | grep i2c-{busid}"
    try:
        output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    except subprocess.CalledProcessError:
        status = SENSOR_ERR_8.format(busid)
    else:
        if output.strip() == "":
            status = SENSOR_ERR_9.format(chipid, chip_id)

    return status, busid

def split_arr(array):
    """
    Splits a string into an array based on ':'.

    Args:
        array: The string to split.

    Returns:
        A list of strings.
    """

    return array.split(":")

def get_sensor_data(udev_link, device1, device2):
    """
    Reads sensor data from the specified files.

    Args:
        udev_link: The udev link of the sensor.
        device1: The first device file to read.
        device2: The second device file to read.

    Returns:
        A tuple containing the status (SENSOR_SUCCESS or error message), the data from device1, and the data from device2.
    """

    val1 = "NA"
    val2 = "NA"

    sensor_file = f"/run/devmap/sensors/{udev_link}/{device1}"
    if not os.path.exists(sensor_file):
        return (SENSOR_ERR_10.format(udev_link), val1, val2)

    val1 = read_sysfile_value(sensor_file)
    if not val1:
        return (SENSOR_ERR_8, val1, val2)

    sensor_file = f"/run/devmap/sensors/{udev_link}/{device2}"
    if not os.path.exists(sensor_file):
        return (SENSOR_ERR_10.format(udev_link), val1, val2)

    val2 = read_sysfile_value(sensor_file)
    if not val2:
        return (SENSOR_ERR_8, val1, val2)

    return (SENSOR_SUCCESS, val1, val2)

def sensor_data(platform):
    """
    Tests the sensors on the specified platform.

    Args:
        platform: The platform to test (e.g., "tahan", "janga").

    Returns:
        The overall test status (SENSOR_SUCCESS or error message).
    """

    print(
        "-------------------------------------------------------------------------\n"
        "       Sensor ID       | Bus | Addr | test data1 | test data2 | Status\n"
        "-------------------------------------------------------------------------"
    )

    sensors = []
    if platform == "janga":
        sensors = J3_SENSORS
        evt_version = fboss.get_board_revision()
        if evt_version == "EVT1" or evt_version == "DVT1":
            pass  # No skipping needed
        elif evt_version == "EVT2":
            sensors = [sensor for sensor in sensors if sensor.udev_link != SKIP]
        else:
            return SENSOR_ERR_5.format(evt_version)
    elif platform == "tahan":
        sensors = TAHAN_SENSORS
    elif platform == "montblanc":
        return "ERROR"
    else:
        return SENSOR_ERR_4.format(platform)

    for sensor in sensors:
        status = "PASS"
        data1 = ""
        data2 = ""

        ret, bus_info = check_sensor_physical_channel(sensor.udev_link, sensor.chip_id, sensor.kernel_info)
        if ret != SENSOR_SUCCESS:
            status = "\033[31mFAIL\033[0m\t" + f"{ret}"

        ret, data1, data2 = get_sensor_data(sensor.udev_link, sensor.device1, sensor.device2)
        if ret != SENSOR_SUCCESS:
            status = "\033[31mFAIL\033[0m\t" + f"{ret}"

        print(
            f'{sensor.udev_link:<22}{"":>3}{bus_info:<2}{"":>4}'
            + f'{hex(int(sensor.chip_id, 16)):<3}{"":>3}{data1.strip():<10}'
            + f'{"":>3}{data2.strip():<10}{"":>3}{status:<5} \n',
            end="",
        )

    return status

def sensor_test(platform=None):
    if not platform:
        platform = get_platform()
    sensor_data(platform)

if __name__ == "__main__":
    sensor_test()
