#!/usr/bin/env python3
# ==============================================================================
# PMBus Interaction Tool & Infineon XDPE Specialized Dumper
# Version: 1.2.0
#
# Description: 
#   A tool to find details for, read, write, and dump values of PMBus commands 
#   using i2c-tools. Includes a highly optimized, auto-detecting dump sequence 
#   for Infineon XDPE dual-loop controllers (XDPE1A2GxB & XDPE152x4D).
#
# Revision History:
#   v1.0.0 - Initial release with standard PMBus read/write/dump capabilities.
#   v1.1.0 - Added specific registers and dual-page dump for Infineon XDPE.
#   v1.2.0 - Unified XDPE dump command with hardware auto-detection (IC_DEVICE_ID).
#          - Switched to 'i' (I2C Block Read) instead of 's' (SMBus Block Read) 
#            to prevent crashes on uninitialized registers returning 0xFF.
#          - Implemented `clean_i2c_block_data` to smartly crop redundant 0xFFs 
#            based on the SMBus length byte.
#          - Removed unsupported registers (0x2D, 0x2E) from XDPE1A2GxB whitelist.
# ==============================================================================

import argparse
import subprocess
import sys

__version__ = "1.2.0"

# PMBus command dictionary based on PMBus specification.
# This list is not exhaustive but covers many common commands.
# Updated based on PMBus Specification Part II Revision 1.3.1.
# Structure: { "name": { "code": 0x.., "access": "R/W", "bytes": #, "type": "..." } }
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

    # Command Group: Voltage Control
    "VOUT_MODE": {"code": 0x20, "access": "R", "bytes": 1, "type": "Read Byte"},
    "VOUT_COMMAND": {"code": 0x21, "access": "R/W", "bytes": 2, "type": "Read/Write Word", "format": "Linear16"},
    "VOUT_TRIM": {"code": 0x22, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_CAL_OFFSET": {"code": 0x23, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_MAX": {"code": 0x24, "access": "R", "bytes": 2, "type": "Read Word"},
    "VOUT_MARGIN_HIGH": {"code": 0x25, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_MARGIN_LOW": {"code": 0x26, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_TRANSITION_RATE": {"code": 0x27, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_DROOP": {"code": 0x28, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_SCALE_LOOP": {"code": 0x29, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_SCALE_MONITOR": {"code": 0x2A, "access": "R", "bytes": 2, "type": "Read Word"},
    "VOUT_MIN": {"code": 0x2B, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "OPL_SET": {"code": 0x2D, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OPL_SR": {"code": 0x2E, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VOUT_MIN_AWARE": {"code": 0x2F, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},

    # Command Group: Configuration and Operation
    "MAX_DUTY": {"code": 0x32, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "FREQUENCY_SWITCH": {"code": 0x33, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "POWER_MODE": {"code": 0x34, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "INTERLEAVE": {"code": 0x37, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Input Voltage and Current
    "VIN_ON": {"code": 0x35, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VIN_OFF": {"code": 0x36, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Current Control
    "IOUT_CAL_GAIN": {"code": 0x38, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_CAL_OFFSET": {"code": 0x39, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Fault Warning and Shutdown Thresholds
    "VOUT_OV_FAULT_LIMIT": {"code": 0x40, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_OV_FAULT_RESPONSE": {"code": 0x41, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VOUT_OV_WARN_LIMIT": {"code": 0x42, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_UV_WARN_LIMIT": {"code": 0x43, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_UV_FAULT_LIMIT": {"code": 0x44, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VOUT_UV_FAULT_RESPONSE": {"code": 0x45, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IOUT_OC_FAULT_LIMIT": {"code": 0x46, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_OC_FAULT_RESPONSE": {"code": 0x47, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IOUT_OC_LV_FAULT_LIMIT": {"code": 0x48, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_OC_LV_FAULT_RESPONSE": {"code": 0x49, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IOUT_OC_WARN_LIMIT": {"code": 0x4A, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_UC_FAULT_LIMIT": {"code": 0x4B, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IOUT_UC_FAULT_RESPONSE": {"code": 0x4C, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OT_FAULT_LIMIT": {"code": 0x4F, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "OT_FAULT_RESPONSE": {"code": 0x50, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "OT_WARN_LIMIT": {"code": 0x51, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "UT_WARN_LIMIT": {"code": 0x52, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "UT_FAULT_LIMIT": {"code": 0x53, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "UT_FAULT_RESPONSE": {"code": 0x54, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VIN_OV_FAULT_LIMIT": {"code": 0x55, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VIN_OV_FAULT_RESPONSE": {"code": 0x56, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "VIN_OV_WARN_LIMIT": {"code": 0x57, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VIN_UV_WARN_LIMIT": {"code": 0x58, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VIN_UV_FAULT_LIMIT": {"code": 0x59, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "VIN_UV_FAULT_RESPONSE": {"code": 0x5A, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IIN_OC_FAULT_LIMIT": {"code": 0x5B, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "IIN_OC_FAULT_RESPONSE": {"code": 0x5C, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "IIN_OC_WARN_LIMIT": {"code": 0x5D, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "POWER_GOOD_ON": {"code": 0x5E, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "POWER_GOOD_OFF": {"code": 0x5F, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Timing
    "TON_DELAY": {"code": 0x60, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "TON_RISE": {"code": 0x61, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "TON_MAX_FAULT_LIMIT": {"code": 0x62, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "TON_MAX_FAULT_RESPONSE": {"code": 0x63, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "TOFF_DELAY": {"code": 0x64, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "TOFF_FALL": {"code": 0x65, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "TOFF_MAX_WARN_LIMIT": {"code": 0x66, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

    # Command Group: Power Limiting
    "POUT_OP_FAULT_LIMIT": {"code": 0x68, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "POUT_OP_FAULT_RESPONSE": {"code": 0x69, "access": "R/W", "bytes": 1, "type": "Read/Write Byte"},
    "POUT_OP_WARN_LIMIT": {"code": 0x6A, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},
    "PIN_OP_WARN_LIMIT": {"code": 0x6B, "access": "R/W", "bytes": 2, "type": "Read/Write Word"},

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

    # Command Group: Telemetry
    "READ_VIN": {"code": 0x88, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "READ_IIN": {"code": 0x89, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "A"},
    "READ_VCAP": {"code": 0x8A, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "READ_VOUT": {"code": 0x8B, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "V"},
    "READ_IOUT": {"code": 0x8C, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "A"},
    "READ_TEMPERATURE_1": {"code": 0x8D, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "READ_TEMPERATURE_2": {"code": 0x8E, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "READ_TEMPERATURE_3": {"code": 0x8F, "access": "R", "bytes": 2, "type": "Read Word", "format": "Linear11", "unit": "C"},
    "READ_FAN_SPEED_1": {"code": 0x90, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_FAN_SPEED_2": {"code": 0x91, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_FAN_SPEED_3": {"code": 0x92, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_FAN_SPEED_4": {"code": 0x93, "access": "R", "bytes": 2, "type": "Read Word"},
    "READ_DUTY_CYCLE": {"code": 0x94, "access": "R", "bytes": 2, "type": "Read Word"},
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
    "MFR_VIN_MIN": {"code": 0xA0, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_VIN_MAX": {"code": 0xA1, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_IIN_MAX": {"code": 0xA2, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_PIN_MAX": {"code": 0xA3, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_VOUT_MIN": {"code": 0xA4, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_VOUT_MAX": {"code": 0xA5, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_IOUT_MAX": {"code": 0xA6, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_POUT_MAX": {"code": 0xA7, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_TAMBIENT_MAX": {"code": 0xA8, "access": "R", "bytes": 2, "type": "Read Word"},
    "MFR_TAMBIENT_MIN": {"code": 0xA9, "access": "R", "bytes": 2, "type": "Read Word"},
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

    # === Infineon XDPE Specific Commands (Shared & Individual) ===
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

# --- Custom Manufacturer-Specific Alert Map ---
MFR_ALERTS_MAP = {
    7: "LIQUID_LEAK_DETECTED - A liquid leak has been detected.",
    4: "PUMP_OVER_TEMP - The liquid cooling pump is overheating.",
    1: "FAN_2_FAULT - Fan 2 is not spinning at the correct speed.",
    0: "FAN_1_FAULT - Fan 1 is not spinning at the correct speed.",
}
# --- End Status Bit Definitions ---

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
        
        # Case 1: Register is uninitialized or empty (returns 0xFF as length)
        if length == 0xFF:
            return "0xff (Uninitialized/Empty)"
            
        # Case 2: Normal SMBus block read (length is between 1 and 32)
        # Crop redundant data beyond the specified length (usually 0xFF tails from I2C read)
        if 0 < length <= 32 and length < len(parts):
            # Keep: length byte (1 byte) + actual data (length bytes)
            return " ".join(parts[:length + 1])
            
        # Case 3: Abnormal length, fallback to stripping trailing 0xFFs from the end
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
    # High byte flags are more general
    for bit, desc in STATUS_WORD_HIGH_BYTE_MAP.items():
        if (high_byte >> bit) & 1:
            flags.append(desc.split(':')[0])
    # Low byte flags are more specific
    for bit, desc in STATUS_WORD_LOW_BYTE_MAP.items():
        if (low_byte >> bit) & 1:
            # Shorten "VOUT_OV_FAULT" to "VOUT_OV"
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
        if (exponent_n >> 4) & 1: # Check sign bit
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

# --- End Decoding Summary Functions ---


def decode_status_word(value):
    """Decodes a 16-bit STATUS_WORD value into human-readable flags."""
    high_byte = (value >> 8) & 0xFF
    low_byte = value & 0xFF
    
    messages = []
    print("\nDecoding STATUS_WORD (High Byte):")
    for bit, desc in STATUS_WORD_HIGH_BYTE_MAP.items():
        if (high_byte >> bit) & 1:
            messages.append(desc)
            print(f"  - Bit {bit+8}: SET - {desc}")
    
    print("\nDecoding STATUS_WORD (Low Byte):")
    for bit, desc in STATUS_WORD_LOW_BYTE_MAP.items():
        if (low_byte >> bit) & 1:
            messages.append(desc)
            print(f"  - Bit {bit}: SET - {desc}")

    if not messages:
        print("  (No status bits set - All OK)")

def decode_status_byte(value):
    """Decodes an 8-bit STATUS_BYTE value into human-readable flags."""
    messages = []
    print("\nDecoding STATUS_BYTE:")
    for bit, desc in STATUS_WORD_LOW_BYTE_MAP.items():
        if (value >> bit) & 1:
            messages.append(desc)
            print(f"  - Bit {bit}: SET - {desc}")
    
    if not messages:
        print("  (No status bits set - All OK)")

def decode_vout_mode(value):
    """Decodes the VOUT_MODE byte."""
    mode = (value >> 5) & 0b111
    parameter = value & 0b11111
    
    mode_str = VOUT_MODE_MAP.get(mode, "Reserved")
    
    print("\nDecoding VOUT_MODE:")
    print(f"  - Mode: {mode_str}")

    if mode_str == "Linear":
        # Parameter is a 5-bit signed two's complement exponent N
        exponent_n = parameter
        if (exponent_n >> 4) & 1: # Check sign bit
            exponent_n = -((~exponent_n & 0b11111) + 1)
        print(f"  - Parameter (Exponent N): {exponent_n}")
    else: # For VID modes, the parameter is usually 0.
        print(f"  - Parameter: 0b{parameter:05b} (Meaning is mode-specific)")

def decode_operation(value):
    """Decodes the OPERATION byte (0x01) based on the PMBus specification."""
    on_off_state = (value >> 7) & 1
    soft_off = (value >> 6) & 1
    margin_state = (value >> 4) & 0b11

    on_off_str = "ON" if on_off_state else "OFF"
    off_mode_str = "Soft-Off" if soft_off else "Immediate Off"

    margin_str = "Margin Off"
    if margin_state == 0b00:
        margin_str = "Margin Off"
    elif margin_state == 0b01:
        margin_str = "Margin Low"
    elif margin_state == 0b10:
        margin_str = "Margin High"
    elif margin_state == 0b11:
        margin_str = "Margin via CONTROL pin"

    print("\nDecoding OPERATION:")
    print(f"  - Output State: {on_off_str}")
    print(f"  - Off Mode: {off_mode_str}")
    print(f"  - Margining: {margin_str}")

def decode_mfr_alerts(value):
    """Decodes the custom MFR_ALERTS byte into human-readable flags."""
    messages = []
    print("\nDecoding MFR_ALERTS:")
    for bit, desc in MFR_ALERTS_MAP.items():
        if (value >> bit) & 1:
            messages.append(desc)
            print(f"  - Bit {bit}: SET - {desc}")
    
    if not messages:
        print("  (No manufacturer alerts set)")

def decode_value(command_name, raw_hex_value, fail_on_unsupported=False):
    """
    Decodes a raw hex value for a given command name.
    Prints the decoded information.
    If fail_on_unsupported is True, it will exit if no decoder is found.
    """
    command_name_upper = command_name.upper()
    
    # A map of command names to their decoding functions
    decode_funcs = {
        "STATUS_WORD": decode_status_word,
        "STATUS_BYTE": decode_status_byte,
        "STATUS_VOUT": decode_status_byte,
        "STATUS_IOUT": decode_status_byte,
        "STATUS_INPUT": decode_status_byte,
        "STATUS_TEMPERATURE": decode_status_byte,
        "STATUS_CML": decode_status_byte,
        "STATUS_OTHER": decode_status_byte,
        "STATUS_MFR_SPECIFIC": decode_mfr_alerts,
        "MFR_ALERTS": decode_mfr_alerts,
        "VOUT_MODE": decode_vout_mode,
        "OPERATION": decode_operation,
    }

    func = decode_funcs.get(command_name_upper)
    if func:
        try:
            # Don't try to decode block reads
            if ' ' in str(raw_hex_value):
                if fail_on_unsupported: # Only show this note for explicit `decode` command
                    print(f"Note: Decoding not supported for block read value '{raw_hex_value}'.")
                return
            value = int(str(raw_hex_value).strip(), 16)
            func(value)
        except (ValueError, TypeError):
            print(f"Warning: Could not decode value '{raw_hex_value}' for command '{command_name}'.", file=sys.stderr)
    elif fail_on_unsupported:
        print(f"Error: Decoding for command '{command_name}' is not currently supported.", file=sys.stderr)
        sys.exit(1)

def convert_linear11_to_float(raw_value):
    """
    Converts a 16-bit PMBus Linear11 format value to a floating-point number.
    The format is Y * 2^N, where Y is a signed 11-bit mantissa and
    N is a signed 5-bit exponent.
    """
    # Exponent is the top 5 bits (signed, two's complement)
    exponent = (raw_value >> 11) & 0b11111
    # Check the sign bit (bit 4 of the 5-bit exponent)
    if (exponent >> 4) & 1:
        # Negative exponent: compute two's complement
        exponent = -((~exponent & 0b11111) + 1)

    # Mantissa is the bottom 11 bits (signed, two's complement)
    mantissa = raw_value & 0b11111111111
    # Check the sign bit (bit 10 of the 11-bit mantissa)
    if (mantissa >> 10) & 1:
        # Negative mantissa: compute two's complement
        mantissa = -((~mantissa & 0b11111111111) + 1)
        
    return mantissa * (2 ** exponent)

def convert_linear16_to_float(raw_value, n_exponent):
    """
    Converts a 16-bit PMBus Linear16 format value to a floating-point number.
    The format is Y * 2^N, where Y is an unsigned 16-bit integer and
    N is a scaling exponent.
    """
    # The raw_value is a U16.0 unsigned integer.
    return raw_value * (2 ** n_exponent)

def convert_float_to_linear16(real_value, n_exponent):
    """
    Converts a floating-point number to a 16-bit PMBus Linear16 format value.
    The formula is Y = X * 2^(-N), where X is the real-world value.
    """
    # The formula is RawValue = RealValue * (2 ** -n_exponent)
    raw_val_float = real_value * (2 ** -n_exponent)
    # Round to the nearest integer and ensure it's within U16 range
    raw_val_int = int(round(raw_val_float))
    if not (0 <= raw_val_int <= 65535):
        raise ValueError(f"Converted value {raw_val_int} is out of U16 range (0-65535).")
    return raw_val_int

def get_decoded_summary(command_name, raw_value):
    """Dispatcher that returns a compact string summary for a given command and raw value."""
    try:
        # Do not attempt to decode multi-byte block read values
        if ' ' in str(raw_value):
            return ""
        value = int(str(raw_value).strip(), 16)
    except (ValueError, TypeError):
        return "" # Not a hex value we can decode

    # --- Try status summary first ---
    summary_funcs = {
        "STATUS_WORD": get_decoded_summary_status_word,
        "STATUS_BYTE": get_decoded_summary_status_byte,
        "MFR_ALERTS": get_decoded_summary_mfr_alerts,
        "VOUT_MODE": get_decoded_summary_vout_mode,
        "OPERATION": get_decoded_summary_operation,
    }
    # Add all status registers to use the same summary function
    for name in PMBUS_COMMANDS:
        if name.startswith("STATUS_") and name not in summary_funcs:
            summary_funcs[name] = get_decoded_summary_status_byte

    func = summary_funcs.get(command_name.upper())
    if func:
        try:
            return func(value)
        except Exception:
            return "<decode error>"

    # --- If not a status register, try format conversion ---
    command_info = get_pmbus_command_info(command_name)
    if command_info:
        data_format = command_info.get('format')
        unit = command_info.get('unit', '')
        if data_format == 'Linear11':
            try:
                real_value = convert_linear11_to_float(value)
                return f"{real_value:.3f} {unit}".strip()
            except Exception:
                return "<convert error>"
    
    return ""

def get_linear16_exponent_from_vout_mode(vout_mode_byte):
    """
    Parses the VOUT_MODE byte and returns the exponent N for Linear16 format.
    Raises ValueError if the mode is not 'Linear'.
    """
    mode = (vout_mode_byte >> 5) & 0b111
    parameter = vout_mode_byte & 0b11111
    
    mode_str = VOUT_MODE_MAP.get(mode, "Reserved")
    
    if mode_str != "Linear":
        raise ValueError(f"VOUT_MODE is '{mode_str}', not 'Linear'. Auto-conversion is not supported.")
        
    # Parameter is a 5-bit signed two's complement exponent N
    exponent_n = parameter
    if (exponent_n >> 4) & 1: # Check sign bit
        exponent_n = -((~exponent_n & 0b11111) + 1)
    return exponent_n

def get_pmbus_command_info(command_name):
    """
    Retrieves the full info dictionary for a given PMBus command name.
    """
    return PMBUS_COMMANDS.get(command_name.upper())

def handle_list_commands(args):
    """Handler for the 'list' action."""
    print("Supported PMBus Commands:")
    # Define headers and calculate column widths
    headers = ["Name", "Code", "Access", "Bytes", "Type"]
    # Find max length for each column for alignment
    max_name = max(len(cmd) for cmd in PMBUS_COMMANDS.keys())
    max_type = max(len(info['type']) for info in PMBUS_COMMANDS.values())

    # Header
    print(f"{headers[0]:<{max_name}} | {headers[1]:<6} | {headers[2]:<7} | {headers[3]:<5} | {headers[4]:<{max_type}}")
    # Separator
    print(f"{'-' * max_name}-+-{'-' * 6}-+-{'-' * 7}-+-{'-' * 5}-+-{'-' * max_type}")

    for cmd_name in sorted(PMBUS_COMMANDS.keys()):
        info = PMBUS_COMMANDS[cmd_name]
        code_hex = f"0x{info['code']:02X}"
        # Ensure 'bytes' is a string for consistent formatting
        bytes_str = str(info['bytes'])
        
        print(f"{cmd_name:<{max_name}} | {code_hex:<6} | {info['access']:<7} | {bytes_str:<5} | {info['type']:<{max_type}}")

def handle_find_command(args):
    """Handler for the 'find' action."""
    command_info = get_pmbus_command_info(args.command)
    if command_info:
        print(f"Details for command '{args.command.upper()}':")
        print(f"  - Code        : 0x{command_info['code']:02X}")
        print(f"  - Access      : {command_info['access']}")
        print(f"  - Data Bytes  : {command_info['bytes']}")
        print(f"  - SMBus Type  : {command_info['type']}")
    else:
        print(f"Error: Command '{args.command}' not found.", file=sys.stderr)
        print("Use 'pmbus_tool.py list' to see all supported commands.", file=sys.stderr)
        sys.exit(1)

def handle_read_command(args):
    """Handler for the 'read' action to get a value from a device."""
    command_name = args.command
    bus = args.bus
    address = args.address

    command_info = get_pmbus_command_info(command_name)

    if not command_info:
        print(f"Error: Command '{command_name}' not found.", file=sys.stderr)
        print("Use 'pmbus_tool.py list' to see all supported commands.", file=sys.stderr)
        sys.exit(1)

    # Check if command is readable
    if 'R' not in command_info['access']:
        print(f"Error: Command '{command_name}' is not readable (access: {command_info['access']}).", file=sys.stderr)
        sys.exit(1)

    # Determine i2cget mode (byte or word)
    num_bytes = command_info['bytes']
    is_block_op = isinstance(num_bytes, str)
    i2c_command = []
    command_code_hex = f"0x{command_info['code']:02X}"

    if is_block_op: # Variable length block op (e.g., "1-N")
        if "Read" not in command_info['type'] and "Block" not in command_info['type']:
            print(f"Error: Command '{command_name}' is not a block read command.", file=sys.stderr)
            sys.exit(1)
        # Use 'i' (I2C Block Read) for maximum compatibility with raw data
        i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'i']
    else: # Fixed number of bytes
        if num_bytes == 1:
            i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'b']
        elif num_bytes == 2:
            i2c_command = ['i2cget', '-y', '-f', str(bus), address, command_code_hex, 'w']
        else: # Fixed length > 2, use i2ctransfer
            print("Note: Using 'i2ctransfer' for fixed-length read operation.")
            # Format: i2ctransfer <bus> w1@<addr> <cmd_code> r<num_bytes>
            i2c_command = ['i2ctransfer', str(bus), f'w1@{address}', command_code_hex, f'r{num_bytes}']

    print(f"Executing: {' '.join(i2c_command)}")
    
    try:
        result = subprocess.run(
            i2c_command,
            capture_output=True,
            text=True,
            check=True
        )
        
        output_value = result.stdout.strip()
        
        # Clean up I2C block read data based on the length byte
        if is_block_op and i2c_command[-1] == 'i':
            output_value = clean_i2c_block_data(output_value)
            
        print(f"--- Result for {command_name} ---")
        
        # Check which tool was used to format the output message
        if i2c_command[0] == 'i2cget' and i2c_command[-1] in ['s', 'i']:
            print(f"Raw value (length byte followed by data bytes): {output_value}")
        elif i2c_command[0] == 'i2ctransfer':
            print(f"Raw value (space-separated bytes): {output_value}")
        else:
            print(f"Raw value: {output_value}")

        # --- Optional: Decode the value if requested ---
        if args.decode:
            decode_value(command_name, output_value, fail_on_unsupported=False)

    except FileNotFoundError:
        print("\nError: `i2cget` command not found.", file=sys.stderr)
        print("Please ensure the 'i2c-tools' package is installed and in your system's PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\nError: `i2cget` command failed with exit code {e.returncode}.", file=sys.stderr)
        print(f"Stderr: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

def _perform_dump(bus, address, decode_flag, allowed_codes=None):
    """Internal helper to perform the core dump logic for the current page."""
    # Sort commands by their hexadecimal code for a more logical dump order
    sorted_commands = sorted(PMBUS_COMMANDS.items(), key=lambda item: item[1]['code'])

    for cmd_name, cmd_info in sorted_commands:
        if 'R' not in cmd_info['access']:
            continue
        
        # In a paged dump, the PAGE command is managed externally, so skip reading it here.
        if cmd_name == "PAGE":
            continue

        # Filter out commands that are not supported by the specific device
        if allowed_codes is not None and cmd_info['code'] not in allowed_codes:
            continue

        # Determine i2c command based on command info
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
            
            # Clean up I2C block read data based on the length byte
            if is_block_op and i2c_command[-1] == 'i':
                output_value = clean_i2c_block_data(output_value)
                
            if decode_flag:
                decoded_summary = get_decoded_summary(cmd_name, output_value)
                print(f"{cmd_name:<30} | {command_code_hex:<6} | {output_value:<20} | {decoded_summary}")
            else:
                print(f"{cmd_name:<30} | {command_code_hex:<6} | {output_value}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            if decode_flag:
                print(f"{cmd_name:<30} | {command_code_hex:<6} | {'<read error>':<20} |")
            else:
                print(f"{cmd_name:<30} | {command_code_hex:<6} | <read error>")

def handle_dump_command(args):
    """Handler for the 'dump' action to read all readable raw data."""
    bus = args.bus
    address = args.address
    print(f"Dumping all readable PMBus commands from device at bus {bus}, address {address}...")
    print("=" * 80)

    if args.decode:
        print(f"{'Command':<30} | {'Code':<6} | {'Raw Value':<20} | {'Decoded'}")
        print(f"{'-'*30}-+-{'-'*6}-+-{'-'*20}-+-{'-'*25}")
    else:
        print(f"{'Command':<30} | {'Code':<6} | {'Raw Value'}")
        print(f"{'-'*30}-+-{'-'*6}-+-{'-'*45}")

    _perform_dump(bus, address, args.decode)
    
    print("=" * 80)
    print("Dump complete.")

def handle_decode_command(args):
    """Handler for the 'decode' action."""
    # For the standalone decode command, we want to fail if the command is not supported.
    decode_value(args.command, args.value, fail_on_unsupported=True)

def handle_paged_dump_command(args):
    """Handler for the 'paged-dump' action to dump data from all pages."""
    bus = args.bus
    address = args.address
    num_pages = args.pages

    print(f"Starting paged dump for {num_pages} pages from device at bus {bus}, address {address}...")
    
    original_page = -1
    try:
        # Read and save the original page to restore it later.
        read_page_cmd = ['i2cget', '-y', '-f', str(bus), address, '0x00', 'b']
        result = subprocess.run(read_page_cmd, capture_output=True, text=True, check=True)
        original_page = int(result.stdout.strip(), 16)
        print(f"Note: Original page was {original_page}. It will be restored after the dump.")
    except Exception as e:
        print(f"Warning: Could not read original page setting. Will not restore. Reason: {e}")

    try:
        for page in range(num_pages):
            print("\n" + "=" * 80)
            print(f"--- Setting PAGE to {page} ---")
            
            # Set the page
            try:
                set_page_cmd = ['i2cset', '-y', '-f', str(bus), address, '0x00', str(page), 'b']
                subprocess.run(set_page_cmd, check=True, capture_output=True, text=True)
                print(f"--- Dumping data for PAGE {page} ---")
            except Exception as e:
                print(f"Error: Failed to set PAGE to {page}. Aborting page dump. Stderr: {e.stderr}", file=sys.stderr)
                break # Stop if we can't set the page

            # Print table header for this page
            if args.decode:
                print(f"{'Command':<30} | {'Code':<6} | {'Raw Value':<20} | {'Decoded'}")
                print(f"{'-'*30}-+-{'-'*6}-+-{'-'*20}-+-{'-'*25}")
            else:
                print(f"{'Command':<30} | {'Code':<6} | {'Raw Value'}")
                print(f"{'-'*30}-+-{'-'*6}-+-{'-'*45}")
                
            # Perform the dump for the current page
            _perform_dump(bus, address, args.decode)
    finally:
        # Restore original page if we read it successfully
        if original_page != -1:
            print("\n" + "=" * 80)
            print(f"--- Restoring original PAGE to {original_page} ---")
            try:
                set_page_cmd = ['i2cset', '-y', '-f', str(bus), address, '0x00', str(original_page), 'b']
                subprocess.run(set_page_cmd, check=True, capture_output=True, text=True)
                print("Original page restored.")
            except Exception as e:
                print(f"Error: Failed to restore original page setting. Stderr: {e.stderr}", file=sys.stderr)
    
    print("=" * 80)
    print("Paged dump complete.")

def auto_detect_xdpe_model(bus, address):
    """
    Attempts to auto-detect the XDPE model by reading IC_DEVICE_ID (0xAD),
    which contains the hardcoded silicon product ID.
    """
    try:
        # Execute I2C Block Read ('i') on 0xAD (IC_DEVICE_ID)
        result = subprocess.run(['i2cget', '-y', '-f', str(bus), address, '0xAD', 'i'], 
                                capture_output=True, text=True, check=True)
        raw_data = result.stdout.strip()
        parts = raw_data.split()
        
        # Block Read format: Length Byte | Data LSB | Data MSB
        if len(parts) >= 3:
            # Parse the 16-bit Product ID (Little-Endian)
            low_byte = parts[1]
            high_byte = parts[2]
            
            # Concatenate into a string like '0x9e01'
            product_id = f"0x{high_byte[-2:]}{low_byte[-2:]}".lower()
            
            # XDPE1A2GxB Family Product IDs: 0x9e01, 0x9b01, 0xb201
            if product_id in ['0x9e01', '0x9b01', '0xb201']:
                print(f"[*] Auto-detected model XDPE1A2GxB from IC_DEVICE_ID ({product_id})")
                return "1A2G"
                
            # XDPE152x4D Family Product IDs typically start with 0x8a, 0x8c, 0x90
            elif product_id.startswith('0x8a') or product_id.startswith('0x8c') or product_id.startswith('0x90'):
                print(f"[*] Auto-detected model XDPE152x4D from IC_DEVICE_ID ({product_id})")
                return "152"
                
            print(f"[!] Unrecognized IC_DEVICE_ID: {product_id}. Defaulting to 1A2G.")
            return "1A2G"
            
    except Exception as e:
        pass # Silently skip if read or parse fails
        
    # Fallback to default state if I2C error occurs
    print("[!] Warning: Auto-detection via IC_DEVICE_ID failed. Defaulting to XDPE1A2GxB (1A2G).")
    return "1A2G"

def handle_infineon_xdpe_dump(args):
    """Unified handler for Infineon XDPE dual-loop controllers."""
    bus = args.bus
    address = args.address
    
    # Auto-detection logic
    model_arg = args.model
    if model_arg == 'auto':
        model_arg = auto_detect_xdpe_model(bus, address)
        
    MODEL_MAP = {
        "1A2G": "XDPE1A2GxB",
        "152": "XDPE152x4D"
    }
    model = MODEL_MAP.get(model_arg, "XDPE1A2GxB")
    
    # Define allowed command whitelists for different chip families
    CHIP_CONFIGS = {
        "XDPE1A2GxB": {
            0x00, 0x01, 0x02, 0x03, 0x10, 0x11, 0x12, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1B,
            0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2B, 0x2F,
            0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4F, 0x50, 0x51, 0x55, 0x56, 0x57, 0x58, 
            0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x6A, 0x6B,
            0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F, 0x80, 0x81, 0x88, 0x89, 0x8B, 0x8C, 
            0x8D, 0x8E, 0x94, 0x96, 0x97, 0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9D, 0x9E, 0xA3, 0xA4, 
            0xA5, 0xA6, 0xA7, 0xA8, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB8, 0xC5, 0xC6, 0xC7, 0xC8, 
            0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 
            0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF, 0xE0, 0xE1, 0xE2, 0xE8, 0xE9, 0xEA, 
            0xEB, 0xEC, 0xED, 0xEE, 0xF0, 0xF1, 0xF2, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 
            0xFB, 0xFC, 0xFD, 0xFE
        },
        "XDPE152x4D": {
            0x00, 0x01, 0x02, 0x03, 0x10, 0x11, 0x12, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1B,
            0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2B, 0x2C, 0x2D,
            0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
            0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4F,
            0x50, 0x51, 0x55, 0x56, 0x57, 0x58, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
            0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x6A, 0x6B,
            0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F, 0x80, 0x81,
            0x86, 0x87, 0x88, 0x89, 0x8B, 0x8C, 0x8D, 0x8E,
            0x94, 0x96, 0x97, 0x98, 0x99, 0x9A, 0x9B, 0x9D,
            0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xAD, 0xAE, 0xAF,
            0xB0, 0xB1,
            0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF,
            0xD2, 0xD3, 0xDE, 0xDF,
            0xF2, 0xF4, 0xF5, 0xFB, 0xFD, 0xFE
        }
    }

    allowed_codes = CHIP_CONFIGS.get(model)
    
    print(f"\n--- Starting specific {model} full raw dump ---")
    print(f"Device: Bus {bus}, Address {address}")
    print("This controller contains two functional loops: Loop A (Page 0x00) and Loop B (Page 0x01).")
    
    original_page = -1
    try:
        read_page_cmd = ['i2cget', '-y', '-f', str(bus), address, '0x00', 'b']
        result = subprocess.run(read_page_cmd, capture_output=True, text=True, check=True)
        original_page = int(result.stdout.strip(), 16)
    except Exception:
        pass 

    try:
        for loop_name, page_val in [("Loop A", 0x00), ("Loop B", 0x01)]:
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
                
            _perform_dump(bus, address, args.decode, allowed_codes=allowed_codes)
            
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

def handle_convert_command(args):
    """Handler for the 'convert' action to translate raw values."""
    command_name = args.command.upper()
    try:
        raw_value = int(args.value, 16)
    except (ValueError, TypeError):
        print(f"Error: Invalid hexadecimal value '{args.value}'", file=sys.stderr)
        sys.exit(1)

    command_info = get_pmbus_command_info(command_name)
    if not command_info:
        print(f"Error: Command '{command_name}' not found.", file=sys.stderr)
        sys.exit(1)

    data_format = command_info.get('format')

    if data_format == 'Linear11':
        real_value = convert_linear11_to_float(raw_value)
        print(f"Converting '{command_name}' value {args.value} (format: Linear11):")
        print(f"  Real-world value: {real_value}")
    elif data_format == 'Linear16':
        if args.exponent is None:
            print(f"Error: The Linear16 format requires an exponent. Please provide one with --exponent.", file=sys.stderr)
            print(f"Hint: For {command_name}, the exponent N can often be found by decoding the VOUT_MODE register.", file=sys.stderr)
            sys.exit(1)
        real_value = convert_linear16_to_float(raw_value, args.exponent)
        print(f"Converting '{command_name}' value {args.value} (format: Linear16) with exponent N={args.exponent}:")
        print(f"  Real-world value: {real_value}")
    else:
        print(f"Error: Conversion for format '{data_format}' is not currently supported for command '{command_name}'.", file=sys.stderr)
        sys.exit(1)

def handle_write_command(args):
    """Handler for the 'write' action to set a value on a device."""
    command_name = args.command
    bus = args.bus
    address = args.address
    values_to_write = args.value # This is now a list

    command_info = get_pmbus_command_info(command_name)

    if not command_info:
        print(f"Error: Command '{command_name}' not found.", file=sys.stderr)
        sys.exit(1)

    # Check if command is writable
    if 'W' not in command_info['access']:
        print(f"Error: Command '{command_name}' is not writable (access: {command_info['access']}).", file=sys.stderr)
        sys.exit(1)

    # Determine i2c command and validate arguments
    num_bytes = command_info['bytes']
    command_code_hex = f"0x{command_info['code']:02X}"
    is_block_op = isinstance(num_bytes, str)
    i2c_command = []

    if is_block_op: # Variable length block op (e.g., "1-N")
        if "Write" not in command_info['type'] and "Block" not in command_info['type']:
            print(f"Error: Command '{command_name}' is not a block write command.", file=sys.stderr)
            sys.exit(1)
        if not values_to_write:
            print(f"Error: Command '{command_name}' is a block write and requires at least one data byte.", file=sys.stderr)
            sys.exit(1)
        # Use i2cset with 'i' for standard SMBus block write
        values_for_i2cset = ",".join(values_to_write)
        i2c_command = ['i2cset', '-y', '-f', str(bus), address, command_code_hex, values_for_i2cset, 'i']
    else:
        # Fixed number of bytes
        if num_bytes == 0: # Send Byte
            if values_to_write:
                print(f"Warning: Command '{command_name}' is a Send Byte command and does not take a value. Ignoring provided value(s).", file=sys.stderr)
            print("Note: Using 'i2ctransfer' for Send Byte operation.")
            i2c_command = ['i2ctransfer', '-f', str(bus), f"w1@{address}", command_code_hex]
        elif num_bytes == 1: # Write Byte
            if not values_to_write or len(values_to_write) != 1:
                print(f"Error: Command '{command_name}' requires a single byte value.", file=sys.stderr)
                sys.exit(1)
            i2c_command = ['i2cset', '-y', '-f', str(bus), address, command_code_hex, values_to_write[0], 'b']
        elif num_bytes == 2: # Write Word
            if not values_to_write or len(values_to_write) != 1:
                print(f"Error: Command '{command_name}' requires a single word value.", file=sys.stderr)
                sys.exit(1)
            i2c_command = ['i2cset', '-y', '-f', str(bus), address, command_code_hex, values_to_write[0], 'w']
        else: # Fixed length > 2, use i2ctransfer
            if not values_to_write or len(values_to_write) != num_bytes:
                print(f"Error: Command '{command_name}' requires exactly {num_bytes} data bytes.", file=sys.stderr)
                sys.exit(1)
            print("Note: Using 'i2ctransfer' for fixed-length write operation.")
            data_len = num_bytes + 1
            i2c_command = ['i2ctransfer', str(bus), f'w{data_len}@{address}', command_code_hex] + values_to_write

    print(f"Executing: {' '.join(i2c_command)}")
    
    try:
        tool_name = i2c_command[0]
        subprocess.run(i2c_command, capture_output=True, text=True, check=True)
        print(f"--- Successfully wrote to {command_name} ---")

    except FileNotFoundError:
        print(f"\nError: `{tool_name}` command not found.", file=sys.stderr)
        print("Please ensure the 'i2c-tools' package is installed and in your system's PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\nError: `{tool_name}` command failed with exit code {e.returncode}.", file=sys.stderr)
        print(f"Stderr: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="A tool to find details for and read/write values of PMBus commands.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Examples:\n" +
               "  python pmbus_tool.py list\n" +
               "  python pmbus_tool.py find VOUT_COMMAND\n\n" +
               "  # Dump all readable raw values from a device\n" +
               "  sudo python pmbus_tool.py dump 10 0x50\n" +
               "  sudo python pmbus_tool.py dump 10 0x50 --decode\n\n" +
               "  # Dump data from a multi-page device (e.g., 4 pages)\n" +
               "  sudo python pmbus_tool.py paged-dump 10 0x50 --pages 4 --decode\n\n" +
               "  # Read a word value\n" +
               "  sudo python pmbus_tool.py read 10 0x50 READ_VOUT\n" +
               "  sudo python pmbus_tool.py read 10 0x50 STATUS_WORD --decode\n\n" +
               "  # Read a variable-length block (SMBus block)\n" +
               "  sudo python pmbus_tool.py read 10 0x50 MFR_ID\n\n" +
               "  # Read a fixed-length block (e.g., 5 bytes)\n" +
               "  sudo python pmbus_tool.py read 10 0x50 MFR_EFFICIENCY_LL\n\n" +
               "  # Write a word value\n" +
               "  sudo python pmbus_tool.py write 10 0x50 VOUT_COMMAND 0x1234\n\n" +
               "  # Write a variable-length block\n" +
               "  sudo python pmbus_tool.py write 10 0x50 USER_DATA_00 0xDE 0xAD 0xBE 0xEF\n\n" +
               "  # Decode a known raw value without reading from a device\n" +
               "  python pmbus_tool.py decode STATUS_WORD 0x8000\n" +
               "  python pmbus_tool.py decode VOUT_MODE 0x1B\n" +
               "  python pmbus_tool.py decode OPERATION 0x80\n" +
               "  # Convert a raw Linear11 value to a real-world number\n" +
               "  python pmbus_tool.py convert READ_VOUT 0xB8E0\n" +
               "  python pmbus_tool.py convert VOUT_COMMAND 0x0026 --exponent -5\n" +
               "  # Write a real-world voltage value (1.2V) to VOUT_COMMAND (auto-fetches exponent)\n" +
               "  sudo python pmbus_tool.py write 10 0x50 VOUT_COMMAND 1.2\n\n" +
               "  # Specialized full dump for Infineon XDPE chips (Auto-detects XDPE1A2GxB vs XDPE152x4D)\n" +
               "  sudo python pmbus_tool.py xdpe-dump 10 0x58\n\n" +
               "  # Send a command with no data\n" +
               "  sudo python pmbus_tool.py write 10 0x50 CLEAR_FAULTS"
    )
    subparsers = parser.add_subparsers(dest='action', required=True, help='Available actions')

    # --- List action ---
    parser_list = subparsers.add_parser('list', help='List all supported PMBus commands.')
    parser_list.set_defaults(func=handle_list_commands)

    # --- Find action ---
    parser_find = subparsers.add_parser('find', help='Find details for a specific PMBus command name.')
    parser_find.add_argument('command', type=str, help="The name of the PMBus command to look up (e.g., 'VOUT_COMMAND').")
    parser_find.set_defaults(func=handle_find_command)

    # --- Read action ---
    parser_read = subparsers.add_parser('read', help='Read a value from a PMBus device using i2cget (requires root/sudo).')
    parser_read.add_argument('bus', type=int, help='The I2C bus number.')
    parser_read.add_argument('address', type=str, help='The I2C device address (e.g., 0x50).')
    parser_read.add_argument('command', type=str, help='The name of the PMBus command to read.')
    parser_read.add_argument('--decode', action='store_true', help='Attempt to decode the read value into a human-readable format.')
    parser_read.set_defaults(func=handle_read_command)

    # --- Write action ---
    parser_write = subparsers.add_parser('write', help='Write a value to a PMBus device using i2cset (requires root/sudo).')
    parser_write.add_argument('bus', type=int, help='The I2C bus number.')
    parser_write.add_argument('address', type=str, help='The I2C device address (e.g., 0x50).')
    parser_write.add_argument('command', type=str, help='The name of the PMBus command to write to.')
    parser_write.add_argument('value', nargs='*', help='The value(s) to write (e.g., 0x1a, 1.2, 0x1234, or 0xDE 0xAD for block). Not used for Send Byte.')
    parser_write.add_argument('--exponent', type=int, help='The scaling exponent (N) for formats like Linear16. If omitted, the tool will try to read it from VOUT_MODE.')
    parser_write.set_defaults(func=handle_write_command)

    # --- Dump action ---
    parser_dump = subparsers.add_parser('dump', help='Read all readable commands from a PMBus device (requires root/sudo).')
    parser_dump.add_argument('bus', type=int, help='The I2C bus number.')
    parser_dump.add_argument('address', type=str, help='The I2C device address (e.g., 0x50).')
    parser_dump.add_argument('--decode', action='store_true', help='Attempt to decode the read values into a human-readable format.')
    parser_dump.set_defaults(func=handle_dump_command)

    # --- Paged Dump action ---
    parser_paged_dump = subparsers.add_parser('paged-dump', help='Read all readable commands from all pages of a PMBus device (requires root/sudo).')
    parser_paged_dump.add_argument('bus', type=int, help='The I2C bus number.')
    parser_paged_dump.add_argument('address', type=str, help='The I2C device address (e.g., 0x50).')
    parser_paged_dump.add_argument('--pages', type=int, required=True, help='The total number of pages to dump (e.g., 4 for pages 0-3).')
    parser_paged_dump.add_argument('--decode', action='store_true', help='Attempt to decode the read values into a human-readable format.')
    parser_paged_dump.set_defaults(func=handle_paged_dump_command)

    # --- Decode action ---
    parser_decode = subparsers.add_parser('decode', help='Decode a raw PMBus value into human-readable flags (e.g., for STATUS_WORD).')
    parser_decode.add_argument('command', type=str, help='The name of the PMBus command to decode (e.g., STATUS_WORD, VOUT_MODE, OPERATION).')
    parser_decode.add_argument('value', type=str, help='The raw hexadecimal value to decode (e.g., 0x8000).')
    parser_decode.set_defaults(func=handle_decode_command)

    # --- Convert action ---
    parser_convert = subparsers.add_parser('convert', help='Convert a raw PMBus value into a real-world value (e.g., for Linear11 format).')
    parser_convert.add_argument('command', type=str, help='The name of the PMBus command whose value you are converting (e.g., READ_VOUT).')
    parser_convert.add_argument('value', type=str, help='The raw 16-bit hexadecimal value to convert (e.g., 0xB8E0).')
    parser_convert.add_argument('--exponent', type=int, help='The scaling exponent (N) for formats like Linear16.')
    parser_convert.set_defaults(func=handle_convert_command)

    # --- XDPE Dump action (Unified with Auto-Detection) ---
    parser_xdpe_dump = subparsers.add_parser('xdpe-dump', help='Specific raw data dump for Infineon XDPE dual-loop controllers.')
    parser_xdpe_dump.add_argument('bus', type=int, help='The I2C bus number.')
    parser_xdpe_dump.add_argument('address', type=str, help='The I2C device address (e.g., 0x50).')
    
    # Add -m parameter with 'auto' option as default
    parser_xdpe_dump.add_argument('-m', '--model', type=str, choices=['auto', '1A2G', '152'], default='auto', 
                                  help='Target chip family. "auto" will detect via PMBus ASCII info. Default: auto.')
    parser_xdpe_dump.add_argument('--decode', action='store_true', help='Attempt to decode standard flags.')
    parser_xdpe_dump.set_defaults(func=handle_infineon_xdpe_dump)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()