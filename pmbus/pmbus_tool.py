#!/usr/bin/env python3
# ==============================================================================
# PMBus Interaction Tool & Multi-Vendor Specialized Dumper
# Version: 1.5.0
#
# Description:
#   A tool to find details for, read, write, and dump values of PMBus commands
#   using i2c-tools. Includes a highly optimized, auto-detecting dump sequence
#   for Infineon XDPE and Renesas RAA dual-loop controllers.
#
# Revision History:
#   v1.0.0 - Initial release with standard PMBus read/write/dump capabilities.
#   v1.1.0 - Added specific registers and dual-page dump for Infineon XDPE.
#   v1.2.0 - Unified XDPE dump command with hardware auto-detection.
#   v1.3.0 - Added support for Renesas RAA229641 controllers & Telemetry math.
#   v1.4.0 - Expanded Infineon family support (192xx, 1B2xx) and ASCII parsing.
#   v1.5.0 - Fixed VOUT decode offset bug by correctly reading VOUT_MODE (0x20)
#            dynamically per page to calculate Linear16 (ULINEAR16) exponents.
#          - Expanded output column widths to 30 for cleaner alignment.
# ==============================================================================

import argparse
import subprocess
import sys

__version__ = "1.5.0"

# --- Infineon Internal Revision Metadata ---
INFINEON_REVISION_MAP = {
    "XDPE152xx": {
        "Rev A": {"REV_CODE": 0x00, "FW_ROM_ID": 0x5eea7ae9, "RPTR": 0xFD, "SCPAD": 0x2005E000},
        "Rev B": {"REV_CODE": 0x01, "FW_ROM_ID": 0x5eea7ae9, "RPTR": 0xFD, "SCPAD": 0x2005E000},
        "Rev C": {"REV_CODE": 0x02, "FW_ROM_ID": 0x5fbd9788, "RPTR": 0xCE, "SCPAD": 0x2005E000},
        "Rev D": {"REV_CODE": 0x03, "FW_ROM_ID": 0x60fadc18, "RPTR": 0xCE, "SCPAD": 0x2005E000},
    },
    "XDPE192xx": {
        "Rev A": {"REV_CODE": 0x00, "FW_ROM_ID": 0x5fbd9788, "RPTR": 0xCE, "SCPAD": 0x2005E000},
        "Rev B": {"REV_CODE": 0x01, "FW_ROM_ID": 0x6192ee1e, "RPTR": 0xCE, "SCPAD": 0x2005E000},
        "Rev C": {"REV_CODE": 0x02, "FW_ROM_ID": 0x63cef57d, "RPTR": 0xCE, "SCPAD": 0x2005E400},
    },
    "XDPE1A2xx": {
        "Rev A": {"REV_CODE": 0x00, "FW_ROM_ID": 0x60ce0678, "RPTR": 0xCE, "SCPAD": 0x2005E000},
        "Rev B": {"REV_CODE": 0x01, "FW_ROM_ID": 0x60ce0678, "RPTR": 0xCE, "SCPAD": 0x2005E000},
    },
    "XDPE1B2xx": {
        "Rev A": {"REV_CODE": 0x00, "FW_ROM_ID": 0x645bd692, "RPTR": 0xCE, "SCPAD": 0x2005D400},
    }
}

# --- Common Helper for Two's Complement ---
def to_signed(val, bits):
    """Converts an unsigned integer to a signed two's complement integer."""
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val

# PMBus command dictionary
PMBUS_COMMANDS = {
    # Command Group: Paging, Phasing, and Configuration
    "PAGE": {"code": 0x00, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OPERATION": {"code": 0x01, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "ON_OFF_CONFIG": {"code": 0x02, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "CLEAR_FAULTS": {"code": 0x03, "access": "W", "bytes": 0, "type": "Send Byte"},
    "PHASE": {"code": 0x04, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "PAGE_PLUS_WRITE": {"code": 0x05, "access": "W", "bytes": "2-33", "type": "Block Write"},
    "PAGE_PLUS_READ": {"code": 0x06, "access": "R/W", "bytes": "2-33", "type": "Block Write-Block Read Process Call"},
    "ZONE_CONFIG": {"code": 0x07, "access": "W", "bytes": "2-N", "type": "Block Write"},
    "ZONE_ACTIVE": {"code": 0x08, "access": "R", "bytes": "1-N", "type": "Block Read"},

    # Command Group: Device Configuration and Programming
    "WRITE_PROTECT": {"code": 0x10, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "STORE_DEFAULT_ALL": {"code": 0x11, "access": "W", "bytes": 0, "type": "Send Byte"},
    "RESTORE_DEFAULT_ALL": {"code": 0x12, "access": "W", "bytes": 0, "type": "Send Byte"},
    "STORE_DEFAULT_CODE": {"code": 0x13, "access": "W", "bytes": 1, "type": "Write Byte"},
    "RESTORE_DEFAULT_CODE": {"code": 0x14, "access": "W", "bytes": 1, "type": "Write Byte"},
    "STORE_USER_ALL": {"code": 0x15, "access": "W", "bytes": 0, "type": "Send Byte"},
    "RESTORE_USER_ALL": {"code": 0x16, "access": "W", "bytes": 0, "type": "Send Byte"},
    "STORE_USER_CODE": {"code": 0x17, "access": "W", "bytes": 1, "type": "Write Byte"},
    "RESTORE_USER_CODE": {"code": 0x18, "access": "W", "bytes": 1, "type": "Write Byte"},
    "CAPABILITY": {"code": 0x19, "access": "R", "bytes": 1, "type": "Read Byte"},
    "QUERY": {"code": 0x1A, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "SMBALERT_MASK": {"code": 0x1B, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Voltage Control (FORMAT: Linear16 for VOUT Commands)
    "VOUT_MODE": {"code": 0x20, "access": "R", "bytes": 1, "type": "Read Byte"},
    "VOUT_COMMAND": {"code": 0x21, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_TRIM": {"code": 0x22, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_CAL_OFFSET": {"code": 0x23, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_MAX": {"code": 0x24, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear16", "unit": "V"},
    "VOUT_MARGIN_HIGH": {"code": 0x25, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_MARGIN_LOW": {"code": 0x26, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_TRANSITION_RATE": {"code": 0x27, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11"},
    "VOUT_DROOP": {"code": 0x28, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11"},
    "VOUT_SCALE_LOOP": {"code": 0x29, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_SCALE_MONITOR": {"code": 0x2A, "access": "R", "bytes": 2, "type": "Read Word"},
    "VOUT_MIN": {"code": 0x2B, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "OPL_SET": {"code": 0x2D, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OPL_SR": {"code": 0x2E, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VOUT_MIN_AWARE": {"code": 0x2F, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},

    # Command Group: Configuration and Operation
    "MAX_DUTY": {"code": 0x32, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "FREQUENCY_SWITCH": {"code": 0x33, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11"},
    "POWER_MODE": {"code": 0x34, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "INTERLEAVE": {"code": 0x37, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Input Voltage and Current
    "VIN_ON": {"code": 0x35, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "V"},
    "VIN_OFF": {"code": 0x36, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "V"},
    "IOUT_CAL_GAIN": {"code": 0x38, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_CAL_OFFSET": {"code": 0x39, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Fault Warning and Shutdown Thresholds
    "VOUT_OV_FAULT_LIMIT": {"code": 0x40, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_OV_FAULT_RESPONSE": {"code": 0x41, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VOUT_OV_WARN_LIMIT": {"code": 0x42, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_UV_WARN_LIMIT": {"code": 0x43, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_UV_FAULT_LIMIT": {"code": 0x44, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "VOUT_UV_FAULT_RESPONSE": {"code": 0x45, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IOUT_OC_FAULT_LIMIT": {"code": 0x46, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "A"},
    "IOUT_OC_FAULT_RESPONSE": {"code": 0x47, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IOUT_OC_LV_FAULT_LIMIT": {"code": 0x48, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "IOUT_OC_LV_FAULT_RESPONSE": {"code": 0x49, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IOUT_OC_WARN_LIMIT": {"code": 0x4A, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "A"},
    "IOUT_UC_FAULT_LIMIT": {"code": 0x4B, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "A"},
    "IOUT_UC_FAULT_RESPONSE": {"code": 0x4C, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OT_FAULT_LIMIT": {"code": 0x4F, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "C"},
    "OT_FAULT_RESPONSE": {"code": 0x50, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OT_WARN_LIMIT": {"code": 0x51, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "C"},
    "UT_WARN_LIMIT": {"code": 0x52, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "C"},
    "UT_FAULT_LIMIT": {"code": 0x53, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "C"},
    "UT_FAULT_RESPONSE": {"code": 0x54, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VIN_OV_FAULT_LIMIT": {"code": 0x55, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "V"},
    "VIN_OV_FAULT_RESPONSE": {"code": 0x56, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VIN_OV_WARN_LIMIT": {"code": 0x57, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "V"},
    "VIN_UV_WARN_LIMIT": {"code": 0x58, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "V"},
    "VIN_UV_FAULT_LIMIT": {"code": 0x59, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "V"},
    "VIN_UV_FAULT_RESPONSE": {"code": 0x5A, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IIN_OC_FAULT_LIMIT": {"code": 0x5B, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "A"},
    "IIN_OC_FAULT_RESPONSE": {"code": 0x5C, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IIN_OC_WARN_LIMIT": {"code": 0x5D, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "A"},
    "POWER_GOOD_ON": {"code": 0x5E, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},
    "POWER_GOOD_OFF": {"code": 0x5F, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16", "unit": "V"},

    # Command Group: Timing
    "TON_DELAY": {"code": 0x60, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "ms"},
    "TON_RISE": {"code": 0x61, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "ms"},
    "TON_MAX_FAULT_LIMIT": {"code": 0x62, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "ms"},
    "TON_MAX_FAULT_RESPONSE": {"code": 0x63, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "TOFF_DELAY": {"code": 0x64, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "ms"},
    "TOFF_FALL": {"code": 0x65, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "ms"},
    "TOFF_MAX_WARN_LIMIT": {"code": 0x66, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "ms"},

    # Command Group: Power Limiting
    "POUT_OP_FAULT_LIMIT": {"code": 0x68, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "W"},
    "POUT_OP_FAULT_RESPONSE": {"code": 0x69, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "POUT_OP_WARN_LIMIT": {"code": 0x6A, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "W"},
    "PIN_OP_WARN_LIMIT": {"code": 0x6B, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear11", "unit": "W"},

    # Command Group: Status and Monitoring
    "STATUS_BYTE": {"code": 0x78, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_WORD": {"code": 0x79, "access": "R", "bytes": 2, "type": "Read Word"},
    "STATUS_VOUT": {"code": 0x7A, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_IOUT": {"code": 0x7B, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_INPUT": {"code": 0x7C, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_TEMPERATURE": {"code": 0x7D, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_CML": {"code": 0x7E, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_OTHER": {"code": 0x7F, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_MFR_SPECIFIC": {"code": 0x80, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_FANS_1_2": {"code": 0x81, "access": "R", "bytes": 1, "type": "Read Byte"},
    "STATUS_FANS_3_4": {"code": 0x82, "access": "R", "bytes": 1, "type": "Read Byte"},

    # Command Group: Telemetry (VOUT marked as Linear16)
    "READ_VIN": {"code": 0x88, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "READ_IIN": {"code": 0x89, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "A"},
    "READ_VCAP": {"code": 0x8A, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "READ_VOUT": {"code": 0x8B, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear16", "unit": "V"},
    "READ_IOUT": {"code": 0x8C, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "A"},
    "READ_TEMPERATURE_1": {"code": 0x8D, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "READ_TEMPERATURE_2": {"code": 0x8E, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "READ_TEMPERATURE_3": {"code": 0x8F, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "READ_FAN_SPEED_1": {"code": 0x90, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_FAN_SPEED_2": {"code": 0x91, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_FAN_SPEED_3": {"code": 0x92, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_FAN_SPEED_4": {"code": 0x93, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_DUTY_CYCLE": {"code": 0x94, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "%"},
    "READ_FREQUENCY": {"code": 0x95, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_POUT": {"code": 0x96, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "W"},
    "READ_PIN": {"code": 0x97, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "W"},

    # Command Group: Manufacturing and Identification
    "PMBUS_REVISION": {"code": 0x98, "access": "R", "bytes": 1, "type": "Read Byte"},
    "MFR_ID": {"code": 0x99, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_MODEL": {"code": 0x9A, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_REVISION": {"code": 0x9B, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_LOCATION": {"code": 0x9C, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_DATE": {"code": 0x9D, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_SERIAL": {"code": 0x9E, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_VIN_MIN": {"code": 0xA0, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "MFR_VIN_MAX": {"code": 0xA1, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "MFR_IIN_MAX": {"code": 0xA2, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "A"},
    "MFR_PIN_MAX": {"code": 0xA3, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "W"},
    "MFR_VOUT_MIN": {"code": 0xA4, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear16", "unit": "V"},
    "MFR_VOUT_MAX": {"code": 0xA5, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear16", "unit": "V"},
    "MFR_IOUT_MAX": {"code": 0xA6, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "A"},
    "MFR_POUT_MAX": {"code": 0xA7, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "W"},
    "MFR_TAMBIENT_MAX": {"code": 0xA8, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "MFR_TAMBIENT_MIN": {"code": 0xA9, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "MFR_EFFICIENCY_LL": {"code": 0xAA, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_EFFICIENCY_HL": {"code": 0xAB, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_PIN_ACCURACY": {"code": 0xAC, "access": "R", "bytes": 1, "type": "Read Byte"},
    "IC_DEVICE_ID": {"code": 0xAD, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "IC_DEVICE_REV": {"code": 0xAE, "access": "R", "bytes": "1-N", "type": "Read Block"},
    "MFR_IOUT_MIN": {"code": 0xAF, "access": "R", "bytes": 2, "type": "Read Word"},

    # Command Group: User Data
    "USER_DATA_00": {"code": 0xB0, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_01": {"code": 0xB1, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_02": {"code": 0xB2, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_03": {"code": 0xB3, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_04": {"code": 0xB4, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_05": {"code": 0xB5, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_06": {"code": 0xB6, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_07": {"code": 0xB7, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_08": {"code": 0xB8, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_09": {"code": 0xB9, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_10": {"code": 0xBA, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_11": {"code": 0xBB, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_12": {"code": 0xBC, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_13": {"code": 0xBD, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_14": {"code": 0xBE, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "USER_DATA_15": {"code": 0xBF, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},

    # Command Group: Manufacturer Specific
    "MFR_SPECIFIC_COMMAND": {"code": 0xD0, "access": "R/W", "bytes": "1-N", "type": "Read/Write Block"},
    "MFR_FAN_PROFILE": {"code": 0xD1, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "MFR_ALERTS": {"code": 0xD2, "access": "R", "bytes": 1, "type": "Read Byte"},

    # Command Group: PMBus Extensions
    "PMBUS_COMMAND_EXT": {"code": 0xFE, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # === Infineon XDPE Specific Commands ===
    "CRC_CHECKSUM": {"code": 0xB8, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "FW_CONFIG_REGULATION": {"code": 0xC5, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "FW_CONFIG_TELEMETRY": {"code": 0xC6, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_COMMON_FAULT_STATUS1": {"code": 0xC7, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "FW_CONFIG_FAULTS": {"code": 0xC8, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "MFR_COMMON_FAULT_STATUS2": {"code": 0xC9, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "MFR_SETUP_PASSWORD": {"code": 0xCA, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_DISABLE_SECURITY_ONCE": {"code": 0xCB, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_SELECT_TEMPERATURE_SENSOR": {"code": 0xCC, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "MFR_GAMER": {"code": 0xCD, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_AHB_ADDRESS": {"code": 0xCE, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_DEBUG_BUFF": {"code": 0xCF, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "SVID_IMON_SCALE_PG_OFFSET": {"code": 0xD1, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "MFR_SECURITY_BIT_MASK_LOW": {"code": 0xD2, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_SECURITY_BIT_MASK_HIGH": {"code": 0xD3, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "PER_PHASE_CURRENT_LIMIT": {"code": 0xD4, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "ISYS_GAIN": {"code": 0xD5, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "CLOUD_PHASE_IMBALANCE": {"code": 0xD6, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "PIN_MAX": {"code": 0xD7, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "PEAK_PSYS_VALUE": {"code": 0xD8, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "CLOUD_IRQ_MASK": {"code": 0xD9, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_EVENT": {"code": 0xDA, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "MFR_OVP_RELATIVE_THRESH": {"code": 0xDB, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "MFR_UVP_RELATIVE_THRESH": {"code": 0xDC, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "P_STAGE_FAULT_ID": {"code": 0xDD, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_REG_WRITE": {"code": 0xDE, "access": "W", "bytes": "1-N", "type": "Block Write"},
    "MFR_REG_READ": {"code": 0xDF, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "SVID_TRANSACTION_LOG": {"code": 0xE0, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "SVI3_TRANSACTION_LOG": {"code": 0xE1, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "AVS_TRANSACTION_LOG": {"code": 0xE2, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "PSYS_PL1_EVENT": {"code": 0xE8, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "CLOUD_MEAS_PULSE_A_SETUP": {"code": 0xE9, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "CLOUD_MEAS_PULSE_B_SETUP": {"code": 0xEA, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "CLOUD_MEAS_PULSE_C_SETUP": {"code": 0xEB, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "CLOUD_MEAS_PULSE_D_SETUP": {"code": 0xEC, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "CLOUD_MEAS_PULSE_REPORT": {"code": 0xED, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "CLOUD_PEAK_VALLEY_REPORT": {"code": 0xEE, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "OUTPUT_CAP_MIN": {"code": 0xF0, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "OUTPUT_CAP_MEASURE": {"code": 0xF1, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_PID": {"code": 0xF2, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_COUT_CONFIG": {"code": 0xF4, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "MFR_READ_COUT": {"code": 0xF5, "access": "R", "bytes": 1, "type": "Read Byte"},
    "PSYS_PL2_EVENT": {"code": 0xF6, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "PSYS_PL1_PL2_EVENT_COUNTERS": {"code": 0xF7, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "SYS_ALERT_MASK": {"code": 0xF8, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "SVID_IOUT_OFFSET": {"code": 0xF9, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "PHASE_ENABLE": {"code": 0xFA, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "POWER_STAGE_VENDOR_ID": {"code": 0xFB, "access": "R", "bytes": 2, "type": "Read Word"},
    "PEAK_IOUT_WITH_VOUT": {"code": 0xFC, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "MFR_FIRMWARE_COMMAND_DATA": {"code": 0xFD, "access": "R/W", "bytes": "1-N", "type": "Block Read/Write"},
    "MFR_FIRMWARE_COMMAND": {"code": 0xFE, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},

    # === Infineon XDPE152x4D Specific Variants ===
    "MFR_OVP_RELATIVE_THRESH_152": {"code": 0x2C, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "MFR_UVP_RELATIVE_THRESH_152": {"code": 0x2D, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "READ_EIN": {"code": 0x86, "access": "R", "bytes": "1-N", "type": "Block Read"},
    "READ_EOUT": {"code": 0x87, "access": "R", "bytes": "1-N", "type": "Block Read"},

    # === Renesas RAA229641 Specific Commands ===
    "DMAFIX": {"code": 0xC5, "access": "R/W", "bytes": "1-N", "type": "Block R/W"},
    "DMASEQ": {"code": 0xC6, "access": "R/W", "bytes": "1-N", "type": "Block R/W"},
    "DMAADDR": {"code": 0xC7, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "READ_VMON_IINSEN": {"code": 0xC8, "access": "R", "bytes": 2, "type": "Read Word"},
    "PEAK_OC_LIMIT": {"code": 0xCD, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "PEAK_UC_LIMIT": {"code": 0xCE, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VMON_ON": {"code": 0xD0, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VMON_OFF": {"code": 0xD1, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "COMPPROP": {"code": 0xDD, "access": "R/W", "bytes": "1-N", "type": "Block R/W"},
    "COMPINTEG": {"code": 0xDE, "access": "R/W", "bytes": "1-N", "type": "Block R/W"},
    "COMPDIFF": {"code": 0xDF, "access": "R/W", "bytes": "1-N", "type": "Block R/W"},
    "COMPCFB": {"code": 0xE0, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "HS_BUS_CURRENT_SCALE": {"code": 0xE3, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "PHASE_CURRENT": {"code": 0xE4, "access": "R", "bytes": 2, "type": "Read Word"},
    "PEAK_OCUC_COUNT": {"code": 0xE9, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "SLOW_IOUT_OC_LIMIT": {"code": 0xEA, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "FAST_OC_FILT_COUNT": {"code": 0xEB, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "SLOW_OC_FILT_COUNT": {"code": 0xEC, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "LOOPCFG": {"code": 0xF0, "access": "R/W", "bytes": "1-N", "type": "Block R/W"},
    "RESTORE_CFG": {"code": 0xF2, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
}

# --- Status Bit Definitions (Based on PMBus Spec Part II, Table 11-2) ---
STATUS_WORD_HIGH_BYTE_MAP = {
    7: "VOUT: Output voltage fault/warning",
    6: "IOUT/POUT: Output current/power fault/warning",
    5: "INPUT: Input voltage/current/power fault/warning",
    4: "MFR_SPECIFIC: Manufacturer specific fault/warning",
    3: "POWER_GOOD#: POWER_GOOD signal is negated",
    2: "FANS: Fan fault/warning",
    1: "OTHER: A fault/warning not covered by other bits",
    0: "UNKNOWN: A fault of an unknown type has occurred",
}

STATUS_WORD_LOW_BYTE_MAP = {
    7: "VOUT_OV_FAULT: Output Overvoltage Fault",
    6: "IOUT_OC_FAULT: Output Overcurrent Fault",
    5: "VIN_UV_FAULT: Input Undervoltage Fault",
    4: "TEMPERATURE: Temperature fault or warning",
    3: "CML: Communications, memory, or logic fault",
    2: "NONE_OF_THE_ABOVE: A non-categorized fault/warning has occurred",
    1: "BUSY: Device is busy and unable to respond",
    0: "OFF: The output is off",
}

VOUT_MODE_MAP = {
    0b000: "Linear",
    0b001: "VR11",
    0b010: "VR12",
    0b011: "VR12.5",
    0b100: "VR13",
    0b101: "IMVP-8",
    0b110: "IMVP-9",
}

MFR_ALERTS_MAP = {
    7: "LIQUID_LEAK_DETECTED - A liquid leak has been detected.",
    4: "PUMP_OVER_TEMP - The liquid cooling pump is overheating.",
    1: "FAN_2_FAULT - Fan 2 is not spinning at the correct speed.",
    0: "FAN_1_FAULT - Fan 1 is not spinning at the correct speed.",
}

# --- Helper Functions for Data Cleanup and Parsing ---
def clean_i2c_block_data(raw_output):
    """
    Cleans up the raw output from 'i2cget ... i' (I2C block read).
    Uses the first byte as the SMBus length indicator to crop trailing 0xFFs,
    or handles uninitialized 0xFF responses gracefully.
    """
    parts = raw_output.split()
    if not parts:
        return raw_output

    try:
        length = int(parts[0], 16)
        if length == 0xFF:
            return "0xff (Uninitialized/Empty)"
        if 0 < length <= 32 and length < len(parts):
            return " ".join(parts[:length + 1])
        while len(parts) > 1 and parts[-1].lower() == '0xff':
            parts.pop()
        return " ".join(parts)
    except ValueError:
        return raw_output

def get_decoded_summary_status_word(value):
    """Returns a compact string summary of a STATUS_WORD value."""
    high_byte = (value >> 8) & 0xFF
    low_byte = value & 0xFF
    flags = []
    for bit, desc in STATUS_WORD_HIGH_BYTE_MAP.items():
        if (high_byte >> bit) & 1:
            flags.append(desc.split(':')[0])
    for bit, desc in STATUS_WORD_LOW_BYTE_MAP.items():
        if (low_byte >> bit) & 1:
            flags.append(desc.split(' ')[0].replace('_FAULT', '').replace('_WARN', ''))
    return ", ".join(flags) if flags else "OK"

def get_decoded_summary_status_byte(value):
    """Returns a compact string summary of a STATUS_BYTE value."""
    flags = []
    for bit, desc in STATUS_WORD_LOW_BYTE_MAP.items():
        if (value >> bit) & 1:
            flags.append(desc.split(' ')[0].replace('_FAULT', '').replace('_WARN', ''))
    return ", ".join(flags) if flags else "OK"

def get_decoded_summary_vout_mode(value):
    """Returns a compact string summary of a VOUT_MODE value."""
    mode = (value >> 5) & 0b111
    parameter = value & 0b11111
    mode_str = VOUT_MODE_MAP.get(mode, "Reserved")
    if mode_str == "Linear":
        exponent_n = parameter
        if (exponent_n >> 4) & 1:
            exponent_n = -((~exponent_n & 0b11111) + 1)
        return f"Linear, N={exponent_n}"
    return mode_str

def get_decoded_summary_operation(value):
    """Returns a compact string summary of an OPERATION value."""
    flags = []
    if (value >> 7) & 1:
        flags.append("On")
    else:
        flags.append("Off")
    margin = (value >> 4) & 0b11
    if margin == 0b01:
        flags.append("Margin-Low")
    elif margin == 0b10:
        flags.append("Margin-High")
    elif margin == 0b11:
        flags.append("Margin-Pin")
    return ", ".join(flags)

def get_decoded_summary_mfr_alerts(value):
    """Returns a compact string summary of an MFR_ALERTS value."""
    flags = []
    for bit, desc in MFR_ALERTS_MAP.items():
        if (value >> bit) & 1:
            flags.append(desc.split(' - ')[0])
    return ", ".join(flags) if flags else "OK"

def convert_linear11_to_float(raw_value):
    """Converts a 16-bit PMBus Linear11 format value to a floating-point number."""
    exponent = (raw_value >> 11) & 0b11111
    if (exponent >> 4) & 1:
        exponent = -((~exponent & 0b11111) + 1)
    mantissa = raw_value & 0b11111111111
    if (mantissa >> 10) & 1:
        mantissa = -((~mantissa & 0b11111111111) + 1)
    return mantissa * (2 ** exponent)

def convert_linear16_to_float(raw_value, n_exponent):
    """Converts a 16-bit PMBus Linear16 format value to a floating-point number."""
    # Used primarily for VOUT commands (unsigned integer * 2^N)
    return raw_value * (2 ** n_exponent)

def get_decoded_summary(command_name, raw_value, model="Generic", vout_exponent=-9):
    """Dispatcher that returns a compact string summary for a given command, value, and model."""
    try:
        # Skip multi-byte block reads for standard math conversions
        if ' ' in str(raw_value):
            return ""
        value = int(str(raw_value).strip(), 16)
    except (ValueError, TypeError):
        return ""

    # --- Step 1: Handle Status Decodes ---
    summary_funcs = {
        "STATUS_WORD": get_decoded_summary_status_word,
        "STATUS_BYTE": get_decoded_summary_status_byte,
        "MFR_ALERTS": get_decoded_summary_mfr_alerts,
        "VOUT_MODE": get_decoded_summary_vout_mode,
        "OPERATION": get_decoded_summary_operation,
    }
    for name in PMBUS_COMMANDS:
        if name.startswith("STATUS_") and name not in summary_funcs:
            summary_funcs[name] = get_decoded_summary_status_byte

    func = summary_funcs.get(command_name.upper())
    if func:
        try:
            return func(value)
        except Exception:
            return "<decode error>"

    # --- Step 2: Handle Model-Aware Telemetry Decoding ---
    cmd_upper = command_name.upper()

    if model == "RAA229641":
        # Renesas RAA229641 uses Direct Format
        try:
            if cmd_upper in ["READ_VOUT", "VOUT_COMMAND", "VOUT_MAX", "VOUT_MARGIN_HIGH", "VOUT_MARGIN_LOW", "VOUT_MIN", "VOUT_OV_FAULT_LIMIT", "VOUT_OV_WARN_LIMIT", "VOUT_UV_WARN_LIMIT", "VOUT_UV_FAULT_LIMIT", "POWER_GOOD_ON", "POWER_GOOD_OFF"]:
                return f"{value / 1000:.3f} V" # 1mV per LSB
            elif cmd_upper == "READ_VIN":
                return f"{to_signed(value, 16) * 10 / 1000:.3f} V"
            elif cmd_upper == "READ_IIN":
                return f"{to_signed(value, 16) / 100:.2f} A"
            elif cmd_upper == "READ_IOUT":
                return f"{to_signed(value, 16) / 10:.2f} A"
            elif cmd_upper == "READ_POUT":
                return f"{to_signed(value, 16):.2f} W"
            elif cmd_upper == "READ_PIN":
                return f"{to_signed(value, 16):.2f} W"
            elif cmd_upper in ["READ_TEMPERATURE_1", "READ_TEMPERATURE_2"]:
                return f"{to_signed(value, 16)} C"
            elif cmd_upper == "READ_VMON_IINSEN":
                return f"{to_signed(value, 16) * 10} mV/mA"
        except Exception:
            return "<decode error>"

    else:
        # Default PMBus standard: Linear11 and Linear16 (VOUT)
        command_info = PMBUS_COMMANDS.get(cmd_upper)
        if command_info:
            data_format = command_info.get('format')
            unit = command_info.get('unit', '')

            if data_format == 'Linear11':
                try:
                    real_value = convert_linear11_to_float(value)
                    return f"{real_value:.3f} {unit}".strip()
                except Exception:
                    return "<convert error>"

            elif data_format == 'Linear16':
                try:
                    real_value = convert_linear16_to_float(value, vout_exponent)
                    return f"{real_value:.3f} {unit}".strip()
                except Exception:
                    return "<convert error>"
    return ""


# --- Tool Action Handlers ---

def auto_detect_model(bus, address):
    """
    Attempts to auto-detect the IC model by reading IC_DEVICE_ID (0xAD) first.
    If hex decoding fails, falls back to reading MFR_MODEL (0x9A) for ASCII
    string matching to ensure robust identification for unknown revisions.
    """
    # 1. Hardware Hex ID Check via IC_DEVICE_ID (0xAD)
    try:
        result = subprocess.run(['i2cget', '-y', '-f', str(bus), address, '0xAD', 'i'],
                                capture_output=True, text=True, check=True)
        raw_data = result.stdout.strip()
        parts = raw_data.split()

        if len(parts) >= 3:
            low_byte = parts[1]
            high_byte = parts[2]
            product_id = f"0x{high_byte[-2:]}{low_byte[-2:]}".lower()

            if product_id in ['0x9e01', '0x9b01', '0xb201']:
                print(f"[*] Auto-detected model XDPE1A2GxB from IC_DEVICE_ID ({product_id})")
                return "1A2G"

            elif product_id.startswith('0x8a') or product_id.startswith('0x8c') or product_id.startswith('0x90'):
                print(f"[*] Auto-detected model XDPE152x4D from IC_DEVICE_ID ({product_id})")
                return "152"

            if len(parts) >= 5:
                renesas_sig = "".join([x[-2:] for x in parts[1:5]]).lower()
                if "49d29b00" in renesas_sig or "009bd249" in renesas_sig:
                    print(f"[*] Auto-detected model Renesas RAA229641 from IC_DEVICE_ID")
                    return "RAA229641"
    except Exception:
        pass

    # 2. ASCII String Check Fallback via MFR_MODEL (0x9A)
    try:
        result = subprocess.run(['i2cget', '-y', '-f', str(bus), address, '0x9A', 'i'],
                                capture_output=True, text=True, check=True)
        raw_data = result.stdout.strip()
        parts = raw_data.split()
        if len(parts) > 1:
            ascii_str = "".join([chr(int(x, 16)) for x in parts[1:] if 32 <= int(x, 16) < 127]).upper()
            if "1A2" in ascii_str:
                print(f"[*] Auto-detected model XDPE1A2GxB from MFR_MODEL ASCII")
                return "1A2G"
            if "152" in ascii_str:
                print(f"[*] Auto-detected model XDPE152x4D from MFR_MODEL ASCII")
                return "152"
            if "192" in ascii_str:
                print(f"[*] Auto-detected model XDPE192xx from MFR_MODEL ASCII")
                return "192"
            if "1B2" in ascii_str:
                print(f"[*] Auto-detected model XDPE1B2xx from MFR_MODEL ASCII")
                return "1B2"
            if "RAA" in ascii_str:
                print(f"[*] Auto-detected model Renesas RAA229641 from MFR_MODEL ASCII")
                return "RAA229641"
    except Exception:
        pass

    print("[!] Warning: Auto-detection failed. Defaulting to Generic PMBus.")
    return "Generic"

def _perform_dump(bus, address, decode_flag, allowed_names=None, model="Generic"):
    """Internal helper to perform the core dump logic for the current page."""

    # Read VOUT_MODE to handle Linear16 decoding for the current page
    vout_exponent = -9 # Default reasonable fallback
    if model != "RAA229641": # RAA uses Direct, skipping
        try:
            res = subprocess.run(['i2cget', '-y', '-f', str(bus), address, '0x20', 'b'], capture_output=True, text=True)
            vout_mode_val = int(res.stdout.strip(), 16)
            mode = (vout_mode_val >> 5) & 0b111
            param = vout_mode_val & 0b11111
            if mode == 0: # 0b000 = Linear
                vout_exponent = param
                if (vout_exponent >> 4) & 1: # Convert from 5-bit two's complement
                    vout_exponent = -((~vout_exponent & 0b11111) + 1)
        except Exception:
            pass

    sorted_commands = sorted(PMBUS_COMMANDS.items(), key=lambda item: item[1]['code'])

    for cmd_name, cmd_info in sorted_commands:
        if 'R' not in cmd_info['access']:
            continue

        if cmd_name == "PAGE":
            continue

        if allowed_names is not None and cmd_name not in allowed_names:
            continue

        num_bytes = cmd_info['bytes']
        is_block_op = isinstance(num_bytes, str)
        i2c_command = []
        command_code_hex = f"0x{cmd_info['code']:02X}"

        if is_block_op:
            if "Read" not in cmd_info['type'] and "Block" not in cmd_info['type']:
                continue
            # Use 'i' (I2C Block Read) to prevent <read error> on uninitialized 0xFF registers
            i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'i']
        else:
            if num_bytes == 1:
                i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'b']
            elif num_bytes == 2:
                i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'w']
            else:
                i2c_command = ['i2ctransfer', str(bus), f'w1@{address}', command_code_hex, f'r{num_bytes}']

        try:
            result = subprocess.run(i2c_command, capture_output=True, text=True, check=True)
            output_value = result.stdout.strip()

            if is_block_op and i2c_command[-1] == 'i':
                output_value = clean_i2c_block_data(output_value)

            if decode_flag:
                # Pass vout_exponent down for Linear16 decoding
                decoded_summary = get_decoded_summary(cmd_name, output_value, model, vout_exponent)
                print(f"{cmd_name:<30} | {command_code_hex:<6} | {output_value:<30} | {decoded_summary}")
            else:
                print(f"{cmd_name:<30} | {command_code_hex:<6} | {output_value}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            if decode_flag:
                print(f"{cmd_name:<30} | {command_code_hex:<6} | {'<read error>':<30} |")
            else:
                print(f"{cmd_name:<30} | {command_code_hex:<6} | <read error>")

def handle_vendor_dump(args):
    """Unified handler for vendor-specific dual-loop controllers."""
    bus = args.bus
    address = args.address

    model_arg = args.model
    if model_arg == 'auto':
        model_arg = auto_detect_model(bus, address)

    MODEL_MAP = {
        "1A2G": "XDPE1A2xx",
        "152": "XDPE152x4D",
        "192": "XDPE192xx",
        "1B2": "XDPE1B2xx",
        "RAA": "RAA229641",
        "RAA229641": "RAA229641",
        "Generic": "Generic"
    }
    model = MODEL_MAP.get(model_arg, "XDPE1A2xx")

    CHIP_CONFIGS = {
        "XDPE1A2xx": {
            "PAGE", "OPERATION", "ON_OFF_CONFIG", "CLEAR_FAULTS", "WRITE_PROTECT", "STORE_DEFAULT_ALL",
            "RESTORE_DEFAULT_ALL", "STORE_USER_ALL", "RESTORE_USER_ALL", "STORE_USER_CODE", "RESTORE_USER_CODE",
            "CAPABILITY", "SMBALERT_MASK", "VOUT_MODE", "VOUT_COMMAND", "VOUT_TRIM", "VOUT_CAL_OFFSET",
            "VOUT_MAX", "VOUT_MARGIN_HIGH", "VOUT_MARGIN_LOW", "VOUT_TRANSITION_RATE", "VOUT_DROOP",
            "VOUT_SCALE_LOOP", "VOUT_MIN", "VOUT_MIN_AWARE", "MAX_DUTY", "FREQUENCY_SWITCH", "POWER_MODE",
            "VIN_ON", "VIN_OFF", "INTERLEAVE", "IOUT_CAL_GAIN", "IOUT_CAL_OFFSET", "VOUT_OV_FAULT_LIMIT",
            "VOUT_OV_FAULT_RESPONSE", "VOUT_OV_WARN_LIMIT", "VOUT_UV_WARN_LIMIT", "VOUT_UV_FAULT_LIMIT",
            "VOUT_UV_FAULT_RESPONSE", "IOUT_OC_FAULT_LIMIT", "IOUT_OC_FAULT_RESPONSE", "IOUT_OC_LV_FAULT_LIMIT",
            "IOUT_OC_LV_FAULT_RESPONSE", "IOUT_OC_WARN_LIMIT", "IOUT_UC_FAULT_LIMIT", "IOUT_UC_FAULT_RESPONSE",
            "OT_FAULT_LIMIT", "OT_FAULT_RESPONSE", "OT_WARN_LIMIT", "VIN_OV_FAULT_LIMIT", "VIN_OV_FAULT_RESPONSE",
            "VIN_OV_WARN_LIMIT", "VIN_UV_WARN_LIMIT", "IIN_OC_FAULT_LIMIT", "IIN_OC_FAULT_RESPONSE",
            "IIN_OC_WARN_LIMIT", "POWER_GOOD_ON", "POWER_GOOD_OFF", "TON_DELAY", "TON_RISE", "TON_MAX_FAULT_LIMIT",
            "TON_MAX_FAULT_RESPONSE", "TOFF_DELAY", "TOFF_FALL", "TOFF_MAX_WARN_LIMIT", "POUT_OP_WARN_LIMIT",
            "PIN_OP_WARN_LIMIT", "STATUS_BYTE", "STATUS_WORD", "STATUS_VOUT", "STATUS_IOUT", "STATUS_INPUT",
            "STATUS_TEMPERATURE", "STATUS_CML", "STATUS_OTHER", "STATUS_MFR_SPECIFIC", "STATUS_FANS_1_2",
            "READ_VIN", "READ_IIN", "READ_VOUT", "READ_IOUT", "READ_TEMPERATURE_1", "READ_TEMPERATURE_2",
            "READ_DUTY_CYCLE", "READ_POUT", "READ_PIN", "PMBUS_REVISION", "MFR_ID", "MFR_MODEL", "MFR_REVISION",
            "MFR_LOCATION", "MFR_DATE", "MFR_SERIAL", "MFR_PIN_MAX", "MFR_VOUT_MIN", "MFR_VOUT_MAX",
            "MFR_IOUT_MAX", "MFR_POUT_MAX", "MFR_TAMBIENT_MAX", "IC_DEVICE_ID", "IC_DEVICE_REV", "MFR_IOUT_MIN",
            "USER_DATA_00", "USER_DATA_01", "CRC_CHECKSUM", "FW_CONFIG_REGULATION", "FW_CONFIG_TELEMETRY",
            "MFR_COMMON_FAULT_STATUS1", "FW_CONFIG_FAULTS", "MFR_COMMON_FAULT_STATUS2", "MFR_SETUP_PASSWORD",
            "MFR_DISABLE_SECURITY_ONCE", "MFR_SELECT_TEMPERATURE_SENSOR", "MFR_GAMER", "MFR_AHB_ADDRESS",
            "MFR_DEBUG_BUFF", "SVID_IMON_SCALE_PG_OFFSET", "MFR_SECURITY_BIT_MASK_LOW", "MFR_SECURITY_BIT_MASK_HIGH",
            "PER_PHASE_CURRENT_LIMIT", "ISYS_GAIN", "CLOUD_PHASE_IMBALANCE", "PIN_MAX", "PEAK_PSYS_VALUE",
            "CLOUD_IRQ_MASK", "IOUT_EVENT", "MFR_OVP_RELATIVE_THRESH", "MFR_UVP_RELATIVE_THRESH",
            "P_STAGE_FAULT_ID", "MFR_REG_WRITE", "MFR_REG_READ", "SVID_TRANSACTION_LOG", "SVI3_TRANSACTION_LOG",
            "AVS_TRANSACTION_LOG", "PSYS_PL1_EVENT", "CLOUD_MEAS_PULSE_A_SETUP", "CLOUD_MEAS_PULSE_B_SETUP",
            "CLOUD_MEAS_PULSE_C_SETUP", "CLOUD_MEAS_PULSE_D_SETUP", "CLOUD_MEAS_PULSE_REPORT",
            "CLOUD_PEAK_VALLEY_REPORT", "OUTPUT_CAP_MIN", "OUTPUT_CAP_MEASURE", "MFR_PID", "MFR_COUT_CONFIG",
            "MFR_READ_COUT", "PSYS_PL2_EVENT", "PSYS_PL1_PL2_EVENT_COUNTERS", "SYS_ALERT_MASK", "SVID_IOUT_OFFSET",
            "PHASE_ENABLE", "POWER_STAGE_VENDOR_ID", "PEAK_IOUT_WITH_VOUT", "MFR_FIRMWARE_COMMAND_DATA",
            "MFR_FIRMWARE_COMMAND"
        },
        "XDPE152x4D": {
            "PAGE", "OPERATION", "ON_OFF_CONFIG", "CLEAR_FAULTS", "WRITE_PROTECT", "STORE_DEFAULT_ALL",
            "RESTORE_DEFAULT_ALL", "STORE_USER_ALL", "RESTORE_USER_ALL", "STORE_USER_CODE", "RESTORE_USER_CODE",
            "CAPABILITY", "SMBALERT_MASK", "VOUT_MODE", "VOUT_COMMAND", "VOUT_TRIM", "VOUT_CAL_OFFSET",
            "VOUT_MAX", "VOUT_MARGIN_HIGH", "VOUT_MARGIN_LOW", "VOUT_TRANSITION_RATE", "VOUT_DROOP",
            "VOUT_SCALE_LOOP", "VOUT_MIN", "MFR_OVP_RELATIVE_THRESH_152", "MFR_UVP_RELATIVE_THRESH_152",
            "MAX_DUTY", "FREQUENCY_SWITCH", "POWER_MODE", "VIN_ON", "VIN_OFF", "INTERLEAVE", "IOUT_CAL_GAIN",
            "IOUT_CAL_OFFSET", "VOUT_OV_FAULT_LIMIT", "VOUT_OV_FAULT_RESPONSE", "VOUT_OV_WARN_LIMIT",
            "VOUT_UV_WARN_LIMIT", "VOUT_UV_FAULT_LIMIT", "VOUT_UV_FAULT_RESPONSE", "IOUT_OC_FAULT_LIMIT",
            "IOUT_OC_FAULT_RESPONSE", "IOUT_OC_LV_FAULT_LIMIT", "IOUT_OC_LV_FAULT_RESPONSE", "IOUT_OC_WARN_LIMIT",
            "IOUT_UC_FAULT_LIMIT", "IOUT_UC_FAULT_RESPONSE", "OT_FAULT_LIMIT", "OT_FAULT_RESPONSE", "OT_WARN_LIMIT",
            "VIN_OV_FAULT_LIMIT", "VIN_OV_FAULT_RESPONSE", "VIN_OV_WARN_LIMIT", "VIN_UV_WARN_LIMIT",
            "IIN_OC_FAULT_LIMIT", "IIN_OC_FAULT_RESPONSE", "IIN_OC_WARN_LIMIT", "POWER_GOOD_ON", "POWER_GOOD_OFF",
            "TON_DELAY", "TON_RISE", "TON_MAX_FAULT_LIMIT", "TON_MAX_FAULT_RESPONSE", "TOFF_DELAY", "TOFF_FALL",
            "TOFF_MAX_WARN_LIMIT", "POUT_OP_WARN_LIMIT", "PIN_OP_WARN_LIMIT", "STATUS_BYTE", "STATUS_WORD",
            "STATUS_VOUT", "STATUS_IOUT", "STATUS_INPUT", "STATUS_TEMPERATURE", "STATUS_CML", "STATUS_OTHER",
            "STATUS_MFR_SPECIFIC", "STATUS_FANS_1_2", "READ_EIN", "READ_EOUT", "READ_VIN", "READ_IIN",
            "READ_VOUT", "READ_IOUT", "READ_TEMPERATURE_1", "READ_TEMPERATURE_2", "READ_DUTY_CYCLE", "READ_POUT",
            "READ_PIN", "PMBUS_REVISION", "MFR_ID", "MFR_MODEL", "MFR_REVISION", "MFR_DATE", "MFR_PIN_MAX",
            "MFR_VOUT_MIN", "MFR_VOUT_MAX", "MFR_IOUT_MAX", "MFR_POUT_MAX", "MFR_TAMBIENT_MAX", "IC_DEVICE_ID",
            "IC_DEVICE_REV", "MFR_IOUT_MIN", "USER_DATA_00", "USER_DATA_01", "FW_CONFIG_REGULATION",
            "FW_CONFIG_TELEMETRY", "MFR_COMMON_FAULT_STATUS1", "FW_CONFIG_FAULTS", "MFR_COMMON_FAULT_STATUS2",
            "MFR_SETUP_PASSWORD", "MFR_DISABLE_SECURITY_ONCE", "MFR_SELECT_TEMPERATURE_SENSOR", "MFR_GAMER",
            "MFR_AHB_ADDRESS", "MFR_DEBUG_BUFF", "MFR_SECURITY_BIT_MASK_LOW", "MFR_SECURITY_BIT_MASK_HIGH",
            "MFR_REG_WRITE", "MFR_REG_READ", "MFR_PID", "MFR_COUT_CONFIG", "MFR_READ_COUT", "POWER_STAGE_VENDOR_ID",
            "MFR_FIRMWARE_COMMAND_DATA", "MFR_FIRMWARE_COMMAND"
        },
        "RAA229641": {
            "OPERATION", "ON_OFF_CONFIG", "CLEAR_FAULTS", "PHASE", "PAGE_PLUS_WRITE", "PAGE_PLUS_READ",
            "WRITE_PROTECT", "CAPABILITY", "SMBALERT_MASK", "VOUT_MODE", "VOUT_COMMAND", "VOUT_TRIM",
            "VOUT_CAL_OFFSET", "VOUT_MAX", "VOUT_MARGIN_HIGH", "VOUT_MARGIN_LOW", "VOUT_TRANSITION_RATE",
            "VOUT_DROOP", "VOUT_MIN", "FREQUENCY_SWITCH", "VIN_ON", "VIN_OFF", "VOUT_OV_FAULT_LIMIT",
            "VOUT_OV_FAULT_RESPONSE", "VOUT_UV_FAULT_RESPONSE", "IOUT_OC_FAULT_LIMIT", "IOUT_OC_FAULT_RESPONSE",
            "IOUT_OC_WARN_LIMIT", "OT_FAULT_LIMIT", "OT_FAULT_RESPONSE", "OT_WARN_LIMIT", "UT_FAULT_LIMIT",
            "UT_FAULT_RESPONSE", "VIN_OV_FAULT_LIMIT", "VIN_OV_FAULT_RESPONSE", "VIN_OV_WARN_LIMIT",
            "VIN_UV_WARN_LIMIT", "VIN_UV_FAULT_LIMIT", "VIN_UV_FAULT_RESPONSE", "IIN_OC_FAULT_LIMIT",
            "IIN_OC_FAULT_RESPONSE", "IIN_OC_WARN_LIMIT", "TON_DELAY", "TON_RISE", "TOFF_DELAY", "TOFF_FALL",
            "STATUS_BYTE", "STATUS_WORD", "STATUS_VOUT", "STATUS_IOUT", "STATUS_INPUT", "STATUS_TEMPERATURE",
            "STATUS_CML", "STATUS_MFR_SPECIFIC", "READ_VIN", "READ_IIN", "READ_VOUT", "READ_IOUT",
            "READ_TEMPERATURE_1", "READ_TEMPERATURE_2", "READ_POUT", "READ_PIN", "PMBUS_REVISION", "MFR_ID",
            "MFR_MODEL", "MFR_REVISION", "MFR_DATE", "IC_DEVICE_ID", "IC_DEVICE_REV", "DMAFIX", "DMASEQ",
            "DMAADDR", "READ_VMON_IINSEN", "PEAK_OC_LIMIT", "PEAK_UC_LIMIT", "VMON_ON", "VMON_OFF", "COMPPROP",
            "COMPINTEG", "COMPDIFF", "COMPCFB", "HS_BUS_CURRENT_SCALE", "PHASE_CURRENT", "PEAK_OCUC_COUNT",
            "SLOW_IOUT_OC_LIMIT", "FAST_OC_FILT_COUNT", "SLOW_OC_FILT_COUNT", "LOOPCFG", "RESTORE_CFG"
        }
    }

    CHIP_CONFIGS["XDPE192xx"] = CHIP_CONFIGS["XDPE1A2xx"]
    CHIP_CONFIGS["XDPE1B2xx"] = CHIP_CONFIGS["XDPE1A2xx"]

    allowed_names = CHIP_CONFIGS.get(model)

    print(f"\n--- Starting specific {model} full raw dump ---")
    print(f"Device: Bus {bus}, Address {address}")

    if model != "Generic":
        print("This controller contains two functional loops: Loop A (Page 0x00) and Loop B (Page 0x01).")

    original_page = -1
    try:
        read_page_cmd = ['i2cget', '-y', '-f', str(bus), address, '0x00', 'b']
        result = subprocess.run(read_page_cmd, capture_output=True, text=True, check=True)
        original_page = int(result.stdout.strip(), 16)
    except Exception:
        pass

    try:
        pages = [("Current Page", original_page if original_page != -1 else 0x00)] if model == "Generic" else [("Loop A", 0x00), ("Loop B", 0x01)]

        for loop_name, page_val in pages:
            print("\n" + "=" * 80)
            print(f"--- Setting PAGE to 0x{page_val:02X} ({loop_name}) ---")

            try:
                set_page_cmd = ['i2cset', '-y', '-f', str(bus), address, '0x00', str(page_val), 'b']
                subprocess.run(set_page_cmd, check=True, capture_output=True, text=True)
            except Exception as e:
                print(f"Error: Failed to set PAGE to {page_val}. Aborting. Stderr: {e.stderr}", file=sys.stderr)
                break

            if args.decode:
                print(f"{'Command':<30} | {'Code':<6} | {'Raw Value':<30} | {'Decoded'}")
                print(f"{'-'*30}-+-{'-'*6}-+-{'-'*30}-+-{'-'*25}")
            else:
                print(f"{'Command':<30} | {'Code':<6} | {'Raw Value'}")
                print(f"{'-'*30}-+-{'-'*6}-+-{'-'*40}")

            _perform_dump(bus, address, args.decode, allowed_names=allowed_names, model=model)

    finally:
        if original_page != -1:
            print("\n" + "=" * 80)
            print(f"--- Restoring original PAGE to 0x{original_page:02X} ---")
            try:
                set_page_cmd = ['i2cset', '-y', '-f', str(bus), address, '0x00', str(original_page), 'b']
                subprocess.run(set_page_cmd, check=True, capture_output=True, text=True)
                print("Original page restored.")
            except Exception:
                pass

    print("=" * 80)
    print(f"{model} specific dump complete.")

def handle_list_commands(args):
    print("Supported PMBus Commands:")
    headers = ["Name", "Code", "Access", "Bytes", "Type"]
    max_name = max(len(cmd) for cmd in PMBUS_COMMANDS.keys())
    max_type = max(len(info['type']) for info in PMBUS_COMMANDS.values())

    print(f"{headers[0]:<{max_name}} | {headers[1]:<6} | {headers[2]:<7} | {headers[3]:<5} | {headers[4]:<{max_type}}")
    print(f"{'-' * max_name}-+-{'-' * 6}-+-{'-' * 7}-+-{'-' * 5}-+-{'-' * max_type}")

    for cmd_name in sorted(PMBUS_COMMANDS.keys()):
        info = PMBUS_COMMANDS[cmd_name]
        code_hex = f"0x{info['code']:02X}"
        bytes_str = str(info['bytes'])
        print(f"{cmd_name:<{max_name}} | {code_hex:<6} | {info['access']:<7} | {bytes_str:<5} | {info['type']:<{max_type}}")

def handle_find_command(args):
    command_info = PMBUS_COMMANDS.get(args.command.upper())
    if command_info:
        print(f"Details for command '{args.command.upper()}':")
        print(f"  - Code        : 0x{command_info['code']:02X}")
        print(f"  - Access      : {command_info['access']}")
        print(f"  - Data Bytes  : {command_info['bytes']}")
        print(f"  - SMBus Type  : {command_info['type']}")
    else:
        print(f"Error: Command '{args.command}' not found.", file=sys.stderr)
        sys.exit(1)

def handle_read_command(args):
    command_name = args.command
    bus = args.bus
    address = args.address
    command_info = PMBUS_COMMANDS.get(command_name.upper())

    if not command_info or 'R' not in command_info['access']:
        print(f"Error: Command '{command_name}' is not readable or not found.", file=sys.stderr)
        sys.exit(1)

    num_bytes = command_info['bytes']
    is_block_op = isinstance(num_bytes, str)
    command_code_hex = f"0x{command_info['code']:02X}"

    if is_block_op:
        i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'i']
    else:
        if num_bytes == 1:
            i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'b']
        elif num_bytes == 2:
            i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'w']
        else:
            i2c_command = ['i2ctransfer', str(bus), f'w1@{address}', command_code_hex, f'r{num_bytes}']

    print(f"Executing: {' '.join(i2c_command)}")
    try:
        result = subprocess.run(i2c_command, capture_output=True, text=True, check=True)
        output_value = result.stdout.strip()
        if is_block_op and i2c_command[-1] == 'i':
            output_value = clean_i2c_block_data(output_value)
        print(f"--- Result for {command_name} ---")
        print(f"Raw value: {output_value}")
    except Exception as e:
        print(f"Error during read: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(
        description="A tool to find details for and read/write values of PMBus commands.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Examples:\n" +
               "  sudo python pmbus_tool.py dump 10 0x58 --decode"
    )
    subparsers = parser.add_subparsers(dest='action', required=True, help='Available actions')

    parser_list = subparsers.add_parser('list', help='List all supported PMBus commands.')
    parser_list.set_defaults(func=handle_list_commands)

    parser_find = subparsers.add_parser('find', help='Find details for a specific PMBus command name.')
    parser_find.add_argument('command', type=str, help="The name of the PMBus command.")
    parser_find.set_defaults(func=handle_find_command)

    parser_read = subparsers.add_parser('read', help='Read a value from a PMBus device.')
    parser_read.add_argument('bus', type=int)
    parser_read.add_argument('address', type=str)
    parser_read.add_argument('command', type=str)
    parser_read.add_argument('--decode', action='store_true')
    parser_read.set_defaults(func=handle_read_command)

    parser_smart_dump = subparsers.add_parser('dump', aliases=['xdpe-dump'], help='Specific raw data dump for Infineon/Renesas dual-loop controllers.')
    parser_smart_dump.add_argument('bus', type=int)
    parser_smart_dump.add_argument('address', type=str)
    parser_smart_dump.add_argument('-m', '--model', type=str, choices=['auto', '1A2G', '152', '192', '1B2', 'RAA'], default='auto')
    parser_smart_dump.add_argument('--decode', action='store_true')
    parser_smart_dump.set_defaults(func=handle_vendor_dump)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()