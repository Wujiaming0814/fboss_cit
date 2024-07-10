#!/usr/bin/env python3
"""Read PMBus energy data functions."""

from smbus2 import SMBus
from time import sleep, time
import os
import re

# Define constants for PMBus registers and data
DEVICE_CONFIG = 0xE4
READ_EIN = 0x86
BLK_SIZE = 8
DEV_ADDR = 0x4C

# Define constants for sample periods
SAMPLE_PERIOD_11US = 11 * 10**6
SAMPLE_PERIOD_18US = 18 * 10**6

# Define constants for accumulator register
ACCUMULATOR_MAX_BITS = 15
ACCUMULATOR_MAX_SCALE = 10**7

# Byte merge constants
MV_8BIT = 2**8
MV_16BIT = 2**16

# Device path format
DEVPATH = "/sys/bus/auxiliary/devices/fbiob_pci.iob_i2c_master.{}/"

def read_energy_data(bus_id, raw_data=False):
    """Reads energy data from an I2C device.

    Args:
        bus_id: The I2C bus ID.
        raw_data: If True, prints raw data from the block.

    Returns:
        A tuple containing:
            - accumulator_value: The accumulator value as a 16-bit unsigned integer.
            - rollover: The rollover value as a single byte.
            - sample_count: The sample count as a 24-bit unsigned integer.
    """
    with SMBus(bus_id, force=True) as bus:
        block = bus.read_i2c_block_data(DEV_ADDR, READ_EIN, BLK_SIZE, force=True)
        if raw_data:
            print("Raw data: ", " ".join(f"{hex(b)}" for b in block))

        # Extract data from the block
        accumulator_value = block[1] + block[2] * MV_8BIT
        rollover = block[3]
        sample_count = block[4] + block[5] * MV_8BIT + block[6] * MV_16BIT

        return accumulator_value, rollover, sample_count

def read_sample_period(bus_id):
    """Reads the sample period from the device.

    Args:
        bus_id: The I2C bus ID.

    Returns:
        The sample period in microseconds (11 or 18), or None if an error occurs.
    """
    try:
        with SMBus(bus_id, True) as bus:
            # Read the configuration data from the device
            config_data = bus.read_word_data(DEV_ADDR, DEVICE_CONFIG, force=True)

            # Extract the relevant bit from the configuration data
            config_bit = (config_data >> 3) & 0x01

            # Return the corresponding time value
            return SAMPLE_PERIOD_11US if config_bit == 0 else SAMPLE_PERIOD_18US
    except OSError as e:
        print(f"Error reading sample period: {e}")
        return None

def calculate_energy_count(accumulator_value, rollover, rval):
    """Calculates the energy count based on the PMBus accumulator register.

    Args:
        accumulator_value: The current value of the accumulator register.
        rollover: Rollover value from the PMBus register.
        rval: The value of RIMON.

    Returns:
        The energy count as a float.
    """
    m = round(38.22 * rval, 3)
    Accumulator_Roll_Over_Value = round(2 ** ACCUMULATOR_MAX_BITS * ACCUMULATOR_MAX_SCALE / m, 3)
    return round(rollover * Accumulator_Roll_Over_Value + accumulator_value, 3)

def pmbus_show_accumulation_energy(busid, rval):
    """Calculates the accumulated energy.

    Args:
        busid: The I2C bus ID.
        rval: The value of RIMON.

    Returns:
        The accumulated energy as a float, or None if an error occurs.
    """
    accumulator_value, rollover, sample_count = read_energy_data(busid)
    energy_count = calculate_energy_count(accumulator_value, rollover, rval)
    sample_period = read_sample_period(busid)

    if sample_period:
        return round(energy_count * sample_period, 3)
    else:
        return None

def pmbus_show_average_energy(busid, rval, delay_time):
    """Calculates the average power.

    Args:
        busid: The I2C bus ID.
        rval: The value of RIMON.
        delay_time: The delay time in seconds between readings.

    Returns:
        The average power as a float, or None if no change in energy count or an error occurs.
    """
    current_timestamp = time()
    print(f"First time read at: {current_timestamp}")
    last_accumulator_value, last_rollover, last_sample_count = read_energy_data(busid, raw_data=True)
    last_energy_count = calculate_energy_count(last_accumulator_value, last_rollover, rval)

    print(f"Delay {delay_time} seconds..")
    sleep(delay_time)

    current_timestamp = time()
    print(f"Second time read at: {current_timestamp}")
    accumulator_value, rollover, sample_count = read_energy_data(busid, raw_data=True)
    energy_count = calculate_energy_count(accumulator_value, rollover, rval)

    if energy_count == last_energy_count:
        print("No change in energy count.")
        return None

    energy_count_diff = energy_count - last_energy_count
    if energy_count_diff < 0:
        energy_count_diff += (1 << 32)

    sample_count_diff = sample_count - last_sample_count
    if sample_count_diff < 0:
        sample_count_diff += (1 << 24)

    average_power =  round(energy_count_diff / sample_count_diff, 3)
    return average_power


def read_all_device_energy():
    # Set the RIMON value
    rval = 1780

    # Iterate through potential I2C bus IDs
    for n in range(18, 26):
        bus_path = DEVPATH.format(n)

        # Get the I2C bus ID from the directory
        busid = get_i2c_bus(bus_path)
        if busid is None:
            print(f"I2C bus not found in {bus_path}")
            continue

        # Convert bus ID to integer
        busid = int(busid)

        # Calculate and print accumulated energy
        accumulation_energy = pmbus_show_accumulation_energy(busid, rval)
        if accumulation_energy is not None:
            print(f"Accumulated energy on bus {busid}: \033[1;32m{accumulation_energy}\033[0m")
        else:
            print(f"Error reading accumulated energy on bus {busid}")

        # Calculate and print average energy
        average_energy = pmbus_show_average_energy(busid, rval, 5)
        if average_energy is not None:
            print(f"Average energy on bus {busid}: \033[1;33m{average_energy}\033[0m")
        else:
            print(f"Error reading average energy on bus {busid}")
        print()

def get_i2c_bus(directory):
    """
    Searches for the I2C bus ID within files in a given directory.

    Args:
    directory: The directory to search.

    Returns:
    The I2C bus ID as a string, or None if not found.
    """

    files = os.listdir(directory)

    for file in files:
        dev = re.findall(r"i2c-\d+", file, re.M)
        if dev:
            return dev[0].split("-")[1]

    return None

if __name__ == "__main__":
    read_all_device_energy()
