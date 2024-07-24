#!/usr/bin/env python3

import os
import re
import csv

# Constants for sensor status and error messages
SENSOR_SUCCESS = "success"

# Define paths and constants
IOB_PCI_DRIVER = "fbiob_pci"
I2C_PATH = "/sys/bus/auxiliary/devices/{}.{}_i2c_master.{}/"
HWMON_PATH = "/sys/bus/auxiliary/devices/{}.{}_i2c_master.{}/i2c-{}/{}-00{}/hwmon/"

# Sensor data structure (more organized)
class Sensor:
    """
    Represents a sensor with its attributes.
    """
    def __init__(self, fpga_id, busid, addr, sysfs_link, position, coefficient, unit, maxval, minval):
        self.fpga_id = fpga_id
        self.busid = busid
        self.addr = addr
        self.sysfs_link = sysfs_link
        self.position = position
        self.coefficient = coefficient
        self.unit = unit
        self.maxval = maxval
        self.minval = minval

    def get_i2c_bus(self, directory):
        """
        Searches for the I2C bus ID within files in a given directory.
        """
        files = os.listdir(directory)
        for file in files:
            dev = re.findall(r"i2c-\d+", file, re.M)
            if dev:
                return dev[0].split("-")[1]
        return None

    def _read_sensor_data(self):
        """
        Reads sensor data from either sysfs link or device path.
        """
        data = self._read_sysfs_data()
        if data:
            return data
        data = self._read_device_data()
        if data:
            return data
        return None

    def _read_sysfs_data(self):
        """
        Reads sensor data from the sysfs link.
        """
        if not os.path.exists(self.sysfs_link):
            return None
        with open(self.sysfs_link, "r") as f:
            sensor_data = f.read().strip()
            if self.coefficient:
                sensor_data = sensor_data * float(self.coefficient)
        return sensor_data

    def _read_device_data(self):
        """
        Reads sensor data from the device path.
        """
        
        fpga_id = self.fpga_id.lower()
        dev_name = self.sysfs_link.split('/')[-1]

        bus_path = I2C_PATH.format(IOB_PCI_DRIVER, fpga_id, self.busid)  # Replace fpga_id with self.fpga_id.lower()
        if os.path.exists(bus_path):
            devid = self.get_i2c_bus(bus_path)
            dev_path = HWMON_PATH.format(IOB_PCI_DRIVER, fpga_id, self.busid, devid, devid, self.addr)  # Replace fpga_id with self.fpga_id.lower()
            if os.path.exists(dev_path):
                for root, dirs, files in os.walk(dev_path):
                    dev_file = f"{dev_path}{dirs[0]}/{dev_name}"
                    with open(dev_file, "r") as f:
                        sensor_data = f.read().strip()
                    break
                if self.coefficient:
                    sensor_data = sensor_data * float(self.coefficient)
                return sensor_data
        return None

    def test_sensor_data(self):
        """
        Tests the sensor data against its thresholds.
        """
        raw_data = self._read_sensor_data()
        if raw_data:
            return raw_data, self._compare_data(raw_data)
        print(f"Invalid device for sensor: {self.sysfs_link}")
        return None

    def _compare_data(self, raw_data):
        """
        Compares the sensor data against its thresholds.
        """
        try:
            data = float(raw_data)
        except ValueError:
            print(f"Invalid data format for sensor: {self.sysfs_link}")
            return None

        if self.minval:
            return "FAIL" if data < self.minval else "PASS"
        if self.maxval:
            return "FAIL" if data > self.maxval else "PASS"
        return "PASS"

def read_config_file(filename):
    """
    Reads sensor configuration from a CSV file.
    """
    sensors = []
    with open(filename, 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            sensors.append(Sensor(
                fpga_id=row['Bus Location'].strip(' '),
                busid=row['Bus ID'].strip(' '),
                addr=row['Sensor Addr'][3:5],
                sysfs_link=row['Software point'],
                position=row['Sensor Position'],
                coefficient=float(row['Multiply']),
                unit=row['Sensor Unit'],
                maxval=float(row['Max_Design']) if row['Max_Design']!='NA' else None,
                minval=float(row['Min_Design']) if row['Min_Design']!='NA' else None
            ))
    return sensors

def sensor_data(sensors):
    """
    Tests the sensors based on the provided configuration.
    """
    print(
        "-------------------------------------------------------------------------\n"
        "       Sensor ID       | Bus | Addr | test data1 | test data2 | Status\n"
        "-------------------------------------------------------------------------"
    )

    for sensor in sensors:
        status = "PASS"
        data, status = sensor.test_sensor_data()
        if status:

            print(
                f'{sensor.fpga_id:<22}{"":>3}{sensor.busid:<2}{"":>4}'
                + f'{data:<5}{"":>3}{sensor.maxval}{"":>3}{sensor.minval}{"":>3}{status:<5} \n',
                end="",
            )

    return status

def sensor_test(config_file="Minipack3_sensors_threshold_list_20240719.csv"):
    """
    Main function to test sensors.
    """
    sensors = read_config_file(config_file)
    sensor_data(sensors)

if __name__ == "__main__":
    sensor_test()
