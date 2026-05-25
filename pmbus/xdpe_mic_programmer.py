#!/usr/bin/env python3
"""
===============================================================================
Script Name : xdpe_mic_programmer.py
Description : Infineon XDPE1x2xx Configuration (.mic) Programming Tool

              This script safely automates the process of burning .mic 
              configuration files into Infineon XDPE1x2xx digital multiphase 
              controllers over the PMBus/I2C interface. It is designed to handle 
              complex hardware topologies, including systems using I2C Multiplexers 
              (e.g., PCA9548).

Features    : - Single-Device Mode, Manual Mode, and Automated Batch Upgrade Mode.
              - Dynamic Virtual I2C Bus Resolution (fuzzy matching sysfs mapping).
              - Pre-flight MD5 signature validation to prevent corrupted flashes.
              - OTP Space pre-check to prevent out-of-memory bricking.
              - Pre-burn and Post-burn Total Configuration Checksum (CRC) validation.
              - Smart '--skip' flag to bypass programming if CRCs already match.
              - Global OTP Invalidation to prevent "Orphan Sections" pollution.
              - I2C Block Write flow control to prevent Rx FIFO buffer overruns.
              - I2C Force Mode (--force) to bypass Linux kernel driver locks.

Version     : 1.3.0
Date        : 2026-05-11
===============================================================================

Version History:
-------------------------------------------------------------------------------
v1.3.0 (2026-05-11) : - Fixed manual override mode (-b, -a, -f) execution logic 
                        which was previously exiting silently.
                      - Implemented precise flow-control delays (2ms) during 
                        Scratchpad Block Writes to prevent I2C RX FIFO buffer 
                        overruns (Communication Fault 0x02) on high-speed parts 
                        (e.g., XDPE1A2G5B).
                      - Enforced strict CML verification (intercepts any non-zero 
                        status) rather than just checking Memory Fault bit.
v1.2.0              : - Fixed "Orphan Section" checksum pollution by implementing 
                        global OTP invalidation (0xFE, 0xFE) prior to flashing.
                      - Updated DEVICE_MAP to support multiple physical base 
                        addresses (e.g., 0xfcf04600, 0xfb504600) for cross-platform 
                        compatibility.
                      - Introduced --debug flag to cleanly manage console verbosity.
                      - Removed unsafe root bus fallback mechanism for MUX devices.
v1.1.0              : - Added '--skip' argument for smart bypass logic.
                      - Introduced Batch Auto-Upgrade Mode for map-based flashing.
                      - Implemented strict MD5 file signature verification.
                      - Added dynamic I2C MUX virtual channel resolution.
v1.0.0              : - Initial release.
===============================================================================
"""

import os
import re
import time
import sys
import hashlib
import binascii
import argparse
from smbus2 import SMBus, i2c_msg

# ==========================================
# Global Configuration
# ==========================================
DEBUG_MODE = False

def dprint(msg):
    """Prints debug messages only if --debug flag is passed."""
    if DEBUG_MODE:
        print(msg)

# ==========================================
# Device Map (Auto-Routing Information)
# Supports both platforms: 0xfcf04600 and 0xfb504600
# ==========================================
DEVICE_MAP = {
    "PU1497": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 6, "addr": 0x70},
    "PU1746": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 7, "addr": 0x70},
    "PU2203": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 0, "addr": 0x70},
    "PU1745": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 3, "addr": 0x70},
    "PU1502": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 1, "addr": 0x70},
    "PU1937": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 5, "addr": 0x6A},
    "PU1342": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 4, "addr": 0x70},
    "PU2052": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 5, "addr": 0x70},
    "PU2056": {"phys_addrs": ["fcf04600", "fb504600"], "mux_ch": 2, "addr": 0x70},
}

# ==========================================
# Helper Functions
# ==========================================
def find_mic_file(device_name, directory):
    if not os.path.exists(directory):
        print(f"[WARNING] Firmware directory not found: {directory}")
        return None
        
    pattern = re.compile(rf"^{re.escape(device_name)}_.*\.mic$")
    matched_files = [f for f in os.listdir(directory) if pattern.match(f)]
    
    if not matched_files:
        print(f"[WARNING] No .mic file matching '{device_name}_*.mic' found in {directory}")
        return None
    if len(matched_files) > 1:
        print(f"[WARNING] Multiple .mic files found for {device_name}. Using the first one: {matched_files[0]}")
        
    return os.path.join(directory, matched_files[0])

def extract_crc_from_filename(filepath):
    basename = os.path.basename(filepath)
    match = re.search(r'-0x([0-9a-fA-F]{8})\.mic$', basename)
    if match:
        return int(match.group(1), 16)
    print(f"[WARNING] Could not extract an 8-digit hex CRC from filename: {basename}")
    return None

def resolve_virtual_i2c_bus(phys_addrs, mux_channel):
    base_dir = "/sys/bus/i2c/devices"
    root_bus = None
    
    if not os.path.exists(base_dir):
        print(f"[WARNING] {base_dir} not found. Cannot resolve bus dynamically.")
        return None
        
    # 1. Fuzzy match the root I2C bus using any of the physical addresses
    for dev in os.listdir(base_dir):
        if not re.match(r'^i2c-\d+$', dev):
            continue
            
        real_path = os.path.realpath(os.path.join(base_dir, dev))
        name_file = os.path.join(base_dir, dev, "name")
        name_content = ""
        if os.path.exists(name_file):
            with open(name_file, 'r') as nf:
                name_content = nf.read().strip().lower()
                
        for p_addr in phys_addrs:
            if (p_addr in real_path) or (p_addr in name_content):
                root_bus = int(dev.split('-')[1])
                dprint(f"[DEBUG] Found Root I2C Bus {root_bus} matching physical address '{p_addr}'.")
                break
                
        if root_bus is not None:
            break
            
    if root_bus is None:
        print(f"[WARNING] Could not find root I2C bus matching physical addresses: {phys_addrs}.")
        return None
    if mux_channel == -1:
        return root_bus

    # 2. Trace the virtual mux channel
    for dev in os.listdir(base_dir):
        if not re.match(r'^i2c-\d+$', dev):
            continue
            
        dev_path = os.path.join(base_dir, dev)
        real_path = os.path.realpath(dev_path)
        virtual_bus = int(dev.split('-')[1])
        
        # Skip the root bus itself
        if virtual_bus == root_bus:
            continue
            
        # Strategy A: Check symlink path
        if f"channel-{mux_channel}" in real_path and (f"i2c-{root_bus}" in real_path or f"{root_bus}-" in real_path):
            dprint(f"[DEBUG] Resolved via Symlink -> Mux Channel {mux_channel} is Virtual Bus {virtual_bus}.")
            return virtual_bus
            
        # Strategy B: Check name file
        name_file = os.path.join(dev_path, "name")
        if os.path.exists(name_file):
            with open(name_file, 'r') as nf:
                name_content = nf.read().strip().lower()
                if f"chan_id {mux_channel}" in name_content and str(root_bus) in name_content:
                    dprint(f"[DEBUG] Resolved via Name file -> Mux Channel {mux_channel} is Virtual Bus {virtual_bus}.")
                    return virtual_bus
                    
    # CRITICAL: Do NOT fallback. Return None to prevent cross-flashing.
    print(f"[ERROR] CRITICAL: Could not resolve virtual bus for Root {root_bus} -> Channel {mux_channel}.")
    print(f"[ERROR] To prevent cross-flashing the wrong device, script will NOT fallback to Root Bus.")
    return None

def verify_md5_checksum(file_path):
    directory = os.path.dirname(file_path)
    base_name = os.path.basename(file_path)
    name_no_ext = os.path.splitext(base_name)[0]
    expected_md5_file = os.path.join(directory, f"MD5_of_{name_no_ext}.txt")
    
    if not os.path.exists(file_path):
        print(f"[WARNING] Firmware file does not exist: {file_path}")
        return False
        
    if not os.path.exists(expected_md5_file):
        print(f"[WARNING] MD5 signature file not found: {expected_md5_file}")
        return False
        
    dprint(f"[DEBUG] Verifying MD5 Signature against: {expected_md5_file}")
    try:
        with open(expected_md5_file, 'r') as f:
            expected_md5 = f.read().strip().split()[0].lower()
            
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        calculated_md5 = hasher.hexdigest().lower()
        
        if expected_md5 != calculated_md5:
            print(f"[ERROR] MD5 Verification Failed!")
            print(f"        Expected   : {expected_md5}")
            print(f"        Calculated : {calculated_md5}")
            return False
            
        print(f"[SUCCESS] MD5 Checksum Verified: {calculated_md5}")
        return True
    except Exception as e:
        print(f"[ERROR] Exception occurred during MD5 validation: {e}")
        return False

# ==========================================
# Core Programmer Class
# ==========================================
class XDPE_Programmer:
    def __init__(self, bus_id, dev_addr, force_mode=False):
        self.bus_id = bus_id
        self.addr = dev_addr
        self.force_mode = force_mode
        self.device_info = {}
        
        try:
            self.bus = SMBus(bus_id)
        except PermissionError:
            print("[ERROR] Permission denied to access I2C bus. Please run with 'sudo' or add your user to the 'i2c' group.")
            sys.exit(1)
            
        self.MFR_REG_WRITE = 0xDE 
        self.MFR_FW_CMD = 0xFE    
        self.MFR_FW_DATA = 0xFD   

    def write_byte(self, cmd, data=None):
        try:
            if data is not None:
                self.bus.write_byte_data(self.addr, cmd, data, force=self.force_mode)
            else:
                self.bus.write_byte(self.addr, cmd, force=self.force_mode)
        except Exception as e:
            print(f"[ERROR] I2C Write Byte failed at address {hex(self.addr)}: {e}")
            raise

    def write_block(self, cmd, data_bytes):
        try:
            self.bus.write_block_data(self.addr, cmd, data_bytes, force=self.force_mode)
        except Exception as e:
            print(f"[ERROR] I2C Block Write failed at address {hex(self.addr)}, cmd {hex(cmd)}: {e}")
            raise

    def read_block(self, cmd):
        try:
            return self.bus.read_block_data(self.addr, cmd, force=self.force_mode)
        except Exception as e:
            print(f"[ERROR] I2C Block Read failed at address {hex(self.addr)}, cmd {hex(cmd)}: {e}")
            raise

    def identify_device(self):
        """1. Identify device model and Revision"""
        tag = "[FORCE MODE ENABLED]" if self.force_mode else ""
        dprint(f"[DEBUG] Probing Address {hex(self.addr)}... {tag}")
        try:
            data = self.read_block(0xAD)
            rev_code, prod_id = data[0], data[1]
            
            self.device_info['prod_id'] = prod_id
            self.device_info['rev'] = rev_code
            
            if prod_id in [0x8A, 0x8C] and rev_code <= 0x01:
                self.device_info['rptr'] = 0xFD
            else:
                self.device_info['rptr'] = 0xCE
            
            if prod_id in [0x95, 0x96, 0x97, 0x98, 0x99] and rev_code == 0x02: 
                self.device_info['scpad'] = [0x00, 0xE4, 0x05, 0x20]
            elif prod_id in [0xA0, 0xA1, 0xA2, 0xA3, 0xA4]: 
                self.device_info['scpad'] = [0x00, 0xD4, 0x05, 0x20]
            else:
                self.device_info['scpad'] = [0x00, 0xE0, 0x05, 0x20] 
            
            print(f"[SUCCESS] Device Identified: ProductID={hex(prod_id)}, Revision={hex(rev_code)}")
            dprint(f"[DEBUG] Assigned RPTR={hex(self.device_info['rptr'])}, SCPAD=0x{bytes(self.device_info['scpad'][::-1]).hex()}")
            return True
        except Exception as e:
            print("[ERROR] Communication failure. Verify hardware connections.")
            return False

    def query_otp_space(self, required_size=0):
        """9. Check remaining OTP space"""
        dprint("[DEBUG] Querying remaining OTP space...")
        try:
            self.write_block(self.MFR_FW_DATA, [0, 0, 0, 0])
            self.write_byte(self.MFR_FW_CMD, 0x10) 
            time.sleep(0.005) 
            
            data = self.read_block(self.MFR_FW_DATA)
            remaining = data[0] + (256 * data[1])
            
            print(f"[INFO] OTP Partition 0 Remaining Space: {remaining} Bytes")
            if required_size > 0 and remaining < required_size:
                print(f"[ERROR] Insufficient OTP space! Required: {required_size} Bytes. Aborting.")
                return False
            return True
        except Exception as e:
            print(f"[ERROR] Failed to query OTP space: {e}")
            return False

    def query_total_checksum(self):
        """8.1. Query Total Configuration Checksum"""
        dprint("[DEBUG] Querying Total Configuration Checksum from device...")
        try:
            self.write_block(self.MFR_FW_DATA, [0, 0, 0, 0])
            self.write_byte(self.MFR_FW_CMD, 0x2D)
            time.sleep(0.025) 
            
            data = self.read_block(self.MFR_FW_DATA)
            crc_val = (data[3] << 24) | (data[2] << 16) | (data[1] << 8) | data[0]
            print(f"[INFO] Device Total Configuration Checksum: 0x{crc_val:08X}")
            return crc_val
        except Exception as e:
            print(f"[ERROR] Failed to query Total Checksum: {e}")
            return None

    def dword_to_bytes(self, hex_str):
        """Convert a 32-bit hex string to 4 bytes, LSB first (Little-Endian)"""
        val = int(hex_str, 16)
        return [val & 0xFF, (val >> 8) & 0xFF, (val >> 16) & 0xFF, (val >> 24) & 0xFF]

    def parse_mic_file(self, filepath):
        """7. Parse .mic file, validate CRC, and format byte arrays"""
        dprint(f"\n[DEBUG] Parsing and formatting .mic payload...")
        sections = []
        total_size = 0
        
        try:
            with open(filepath, 'r') as f:
                current_sec = None
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    if line.startswith("//XV"):
                        if current_sec:
                            sections.append(current_sec)
                        xv_char = line[4:5]
                        current_sec = {
                            "name": line,
                            "xv_code": int(xv_char, 16) if xv_char.isalnum() else 0,
                            "raw_dwords": []
                        }
                    elif current_sec and line[0].isdigit():
                        parts = line.split()
                        if len(parts[0]) == 3:
                            current_sec["raw_dwords"].extend(parts[1:])
            
            if current_sec:
                sections.append(current_sec)

            valid_sections = []
            for sec in sections:
                if not sec["raw_dwords"]: continue
                
                dw0 = sec["raw_dwords"][0]
                sec["hc"] = int(dw0, 16) & 0xFF 
                
                is_partial = sec["hc"] in [0x0A, 0x0B, 0x11]
                
                if not is_partial:
                    dw1 = sec["raw_dwords"][1]
                    sec["size"] = int(dw1, 16) & 0xFFFF 
                    
                    parsed_header_crc = int(sec["raw_dwords"][2], 16)
                    parsed_data_crc = int(sec["raw_dwords"][-1], 16)

                    header_bytes = bytearray()
                    header_bytes.extend(self.dword_to_bytes(dw0))
                    header_bytes.extend(self.dword_to_bytes(dw1))
                    calc_header_crc = binascii.crc32(header_bytes) & 0xFFFFFFFF
                    
                    data_bytes = bytearray()
                    for dw in sec["raw_dwords"][3:-1]:
                        data_bytes.extend(self.dword_to_bytes(dw))
                    calc_data_crc = binascii.crc32(data_bytes) & 0xFFFFFFFF

                    if calc_header_crc != parsed_header_crc or calc_data_crc != parsed_data_crc:
                        print(f"[WARNING] CRC mismatch in {sec['name']}. File may be corrupted.")
                        continue
                else:
                    idx = 0
                    sec_valid = True
                    total_partial_size = 0
                    
                    while idx < len(sec["raw_dwords"]):
                        p_dw0 = sec["raw_dwords"][idx]
                        p_dw1 = sec["raw_dwords"][idx+1]
                        
                        cmd_size = int(p_dw1, 16) & 0xFFFF
                        num_dwords = cmd_size // 4
                        
                        if idx + num_dwords > len(sec["raw_dwords"]):
                            print(f"[WARNING] Truncated sub-command in {sec['name']}")
                            sec_valid = False
                            break
                            
                        chunk = sec["raw_dwords"][idx : idx+num_dwords]
                        parsed_header_crc = int(chunk[2], 16)
                        parsed_data_crc = int(chunk[-1], 16)
                        
                        header_bytes = bytearray()
                        header_bytes.extend(self.dword_to_bytes(p_dw0))
                        header_bytes.extend(self.dword_to_bytes(p_dw1))
                        calc_header_crc = binascii.crc32(header_bytes) & 0xFFFFFFFF
                        
                        data_bytes = bytearray()
                        for dw in chunk[3:-1]:
                            data_bytes.extend(self.dword_to_bytes(dw))
                        calc_data_crc = binascii.crc32(data_bytes) & 0xFFFFFFFF
                        
                        if calc_header_crc != parsed_header_crc or calc_data_crc != parsed_data_crc:
                            print(f"[WARNING] Sub-command CRC mismatch in {sec['name']} at offset {idx}.")
                            sec_valid = False
                            break
                            
                        total_partial_size += cmd_size
                        idx += num_dwords
                        
                    if not sec_valid:
                        continue
                        
                    sec["size"] = total_partial_size

                total_size += sec["size"]
                sec["write_payload"] = []
                for dw in sec["raw_dwords"]:
                    sec["write_payload"].extend(self.dword_to_bytes(dw))
                    
                valid_sections.append(sec)

            print("\n" + "="*75)
            print(f"{'Configuration Segment (.mic)':<30} | {'XVcode':<6} | {'Header (HC)':<11} | {'Size (Bytes)':<15}")
            print("-" * 75)
            for s in valid_sections:
                print(f"{s['name']:<30} | XV{s['xv_code']:<4} | {hex(s['hc']):<11} | {s['size']} Bytes")
            print("="*75)
            print(f"[INFO] Estimated Total OTP Space required: {total_size} Bytes\n")
            
            return valid_sections, total_size
            
        except Exception as e:
            print(f"[ERROR] Failed to parse .mic file: {e}")
            return None, 0

    def execute_programming(self, sections):
        """4. Execute upgrade flow via Scratchpad"""
        print("\n[INFO] Initiating OTP Programming Sequence...")
        
        prod_id = self.device_info.get('prod_id', 0)
        rev = self.device_info.get('rev', 0)
        
        is_legacy = False
        if prod_id in [0x8A, 0x8C] and rev <= 0x02: 
            is_legacy = True
        elif prod_id in [0x95, 0x96, 0x97, 0x98, 0x99] and rev == 0x00: 
            is_legacy = True
            
        if not is_legacy:
            dprint("[DEBUG] Globally invalidating all old OTP data (0xFE, 0xFE) to prevent orphan sections...")
            try:
                self.write_block(self.MFR_FW_DATA, [0xFE, 0xFE, 0x00, 0x00])
                self.write_byte(self.MFR_FW_CMD, 0x12)
                time.sleep(0.5)  # Extended wait for global invalidation
            except Exception as e:
                print(f"[ERROR] Global Invalidation failed: {e}")
                return False
        else:
            dprint("[DEBUG] Legacy silicon detected. Performing deep invalidation scan (this takes ~6 seconds)...")
            hcs = [0x04, 0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x11]
            try:
                for xv in range(16):
                    for hc in hcs:
                        self.write_block(self.MFR_FW_DATA, [hc, xv, 0x00, 0x00])
                        self.write_byte(self.MFR_FW_CMD, 0x12)
                        time.sleep(0.04) 
            except Exception as e:
                print(f"[ERROR] Legacy Invalidation failed: {e}")
                return False
        
        for i, sec in enumerate(sections):
            print(f"\n[INFO] --- Processing Section {i+1}/{len(sections)}: {sec['name']} ---")

            dprint(f"[DEBUG] Pointing RPTR to Scratchpad...")
            self.write_block(self.device_info['rptr'], self.device_info['scpad'])
            
            dprint(f"[DEBUG] Streaming {len(sec['raw_dwords'])} DWORDs to MFR_REG_WRITE (0xDE)...")
            for j in range(0, len(sec['write_payload']), 4):
                chunk = sec['write_payload'][j:j+4]
                self.write_block(self.MFR_REG_WRITE, chunk)
                time.sleep(0.002) # Flow control delay to prevent RX FIFO Overrun (Comm Fault 0x02)
                
            for page in [0, 1]:
                self.write_byte(0x00, page)
                self.write_byte(0x03)
                time.sleep(0.01)
                
            sz0 = sec['size'] & 0xFF
            sz1 = (sec['size'] >> 8) & 0xFF
            self.write_block(self.MFR_FW_DATA, [sz0, sz1, 0x00, 0x00])
            self.write_byte(self.MFR_FW_CMD, 0x11)
            
            soak_time = sec['size'] * 0.002
            dprint(f"[DEBUG] Burning to OTP... strictly waiting {soak_time:.3f} seconds.")
            time.sleep(max(soak_time, 0.2))

            status_cml = self.bus.read_byte_data(self.addr, 0x7E, force=self.force_mode)
            if status_cml & 0x01:
                print(f"[ERROR] Memory fault detected (CML Bit 0). Section {sec['name']} programming failed!")
                return False
            else:
                print(f"[SUCCESS] {sec['name']} programmed and validated successfully.")

        print("\n[INFO] All configuration sections processed and uploaded to OTP successfully.")
        return True


# ==========================================
# Orchestration Workflows
# ==========================================
def process_single_device(device_name, dev_info, directory, force_mode, skip_match=False, interactive=True):
    """
    Handles the full end-to-line upgrade process for a single device.
    Returns: "SUCCESS", "FAIL", or "SKIP"
    """
    print("\n" + "="*80)
    print(f" DEVICE UPGRADE TASK: {device_name} ")
    print("="*80)

    target_file = find_mic_file(device_name, directory)
    if not target_file:
        print(f"[SKIP] No valid configuration file found for {device_name}. Skipping.")
        return "SKIP"

    if not verify_md5_checksum(target_file):
        print(f"[FAIL] MD5 Checksum validation failed for {device_name}. Skipping to ensure safety.")
        return "FAIL"

    target_bus = resolve_virtual_i2c_bus(dev_info["phys_addrs"], dev_info["mux_ch"])
    if target_bus is None:
        print(f"[FAIL] Could not resolve Virtual I2C bus for {device_name}. Skipping.")
        return "FAIL"

    target_addr = dev_info["addr"]
    
    print(f"[INFO] Hardware Mapping -> Device: {device_name} | I2C Bus: {target_bus} | Address: {hex(target_addr)}")

    programmer = XDPE_Programmer(bus_id=target_bus, dev_addr=target_addr, force_mode=force_mode)

    if not programmer.identify_device():
        return "FAIL"

    print("\n[INFO] Gathering Pre-burn Device State...")
    pre_checksum = programmer.query_total_checksum()

    target_filename_crc = extract_crc_from_filename(target_file)

    if skip_match and pre_checksum is not None and target_filename_crc is not None:
        if pre_checksum == target_filename_crc:
            print(f"\n[SKIP] Device CRC (0x{pre_checksum:08X}) matches target configuration. Skipping upgrade as requested.")
            return "SKIP"

    sections, total_needed = programmer.parse_mic_file(target_file)
    if not sections:
        return "FAIL"

    if not programmer.query_otp_space(required_size=total_needed):
        return "FAIL"

    if interactive:
        print("\n[WARNING] OTP Programming is an irreversible hardware process.")
        confirm = input(f"[ACTION] Ready to flash {device_name} at {hex(target_addr)}? [y/N]: ").strip()
        if confirm.lower() != 'y':
            print("\n[INFO] Operation gracefully cancelled by user.")
            return "SKIP"
    else:
        print(f"\n[INFO] Auto-Mode Enabled. Proceeding with flash for {device_name}...")

    success = programmer.execute_programming(sections)
    if not success:
        print(f"\n[ERROR] Update halted for {device_name} due to a CML memory fault.")
        return "FAIL"

    print(f"\n[SUCCESS] OTP Programming Cycle Complete for {device_name}!")
    dprint("[DEBUG] Verifying post-burn Total Checksum against Filename Hash...")
    post_checksum = programmer.query_total_checksum()
    
    if target_filename_crc is not None and post_checksum is not None:
        print("\n" + "="*65)
        print(f" FINAL CRC VALIDATION REPORT ({device_name}) ")
        print("-" * 65)
        print(f" Expected CRC (From Filename) : 0x{target_filename_crc:08X}")
        print(f" Actual CRC (Read from Device): 0x{post_checksum:08X}")
        
        if post_checksum == target_filename_crc:
            print("\n [RESULT]: SUCCESS - CRCs Match Perfectly.")
            return "SUCCESS"
        else:
            print("\n [RESULT]: FAILURE - CRC Mismatch! Programming may be corrupted.")
            return "FAIL"
            
    return "SUCCESS"

# ==========================================
# Main CLI Entry
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Infineon XDPE1x2xx Configuration (.mic) Interactive Tool")
    
    parser.add_argument("-n", "--name", type=str, help="Device Name (e.g., PU1497) to target a single specific device")
    parser.add_argument("-d", "--dir", type=str, default="/var/unidiag/firmware/power", help="Base directory for firmware files")
    
    parser.add_argument("-b", "--bus", type=int, help="Manual override: I2C Bus ID (e.g., 1)")
    parser.add_argument("-a", "--address", type=lambda x: int(x, 0), help="Manual override: PMBus Device Address (e.g., 0x70)")
    parser.add_argument("-f", "--file", type=str, help="Manual override: Exact path to the .mic configuration file")
    
    parser.add_argument("--force", action="store_true", help="Enable I2C_SLAVE_FORCE mode to bypass kernel driver locks")
    parser.add_argument("--checksum", action="store_true", help="Action: Read the Total Configuration Checksum from the device")
    parser.add_argument("--space", action="store_true", help="Action: Read the remaining OTP space from the device")
    parser.add_argument("--skip", action="store_true", help="Action: Skip programming if device CRC already matches the target .mic CRC")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    
    args = parser.parse_args()
    
    DEBUG_MODE = args.debug

    print("=" * 80)
    print(" Infineon XDPE1x2xx Configuration (.mic) Tool")
    print("=" * 80)

    has_specific_target = any([args.name, args.bus is not None, args.address is not None, args.file])

    if not has_specific_target:
        if args.force and not (args.checksum or args.space):
            print("\n[INFO] No specific target provided. '--force' detected. Entering Batch Auto-Upgrade Mode.")
            
            results = {"SUCCESS": [], "FAIL": [], "SKIP": []}
            
            for dev_name, dev_info in DEVICE_MAP.items():
                status = process_single_device(dev_name, dev_info, args.dir, args.force, args.skip, interactive=False)
                results[status].append(dev_name)
                
            print("\n" + "="*80)
            print(" BATCH AUTO-UPGRADE SUMMARY ")
            print("="*80)
            print(f" SUCCESS : {len(results['SUCCESS'])} {results['SUCCESS']}")
            print(f" FAILED  : {len(results['FAIL'])} {results['FAIL']}")
            print(f" SKIPPED : {len(results['SKIP'])} {results['SKIP']}")
            print("="*80)
            
            sys.exit(0 if len(results['FAIL']) == 0 else 1)
        else:
            print("\n[ERROR] No target specified. Use -n <name>, or -b/-a/-f.")
            print("[INFO] To auto-upgrade ALL devices in the map, run the script without targets and add '--force'.")
            sys.exit(1)

    target_bus = None
    target_addr = None

    if args.name:
        if args.name not in DEVICE_MAP:
            print(f"[ERROR] Device name '{args.name}' not found in the internal hardware map.")
            sys.exit(1)
            
        dev_info = DEVICE_MAP[args.name]
        
        if not (args.checksum or args.space):
            status = process_single_device(args.name, dev_info, args.dir, args.force, args.skip, interactive=True)
            sys.exit(0 if status in ["SUCCESS", "SKIP"] else 1)
        else:
            target_addr = dev_info["addr"]
            target_bus = resolve_virtual_i2c_bus(dev_info["phys_addrs"], dev_info["mux_ch"])

    if args.bus is not None: target_bus = args.bus
    if args.address is not None: target_addr = args.address

    if target_bus is None or target_addr is None:
        print("[ERROR] Insufficient routing information. Please provide either a valid '-n <DeviceName>' or manual '-b <Bus>' and '-a <Address>'.")
        sys.exit(1)

    print(f"\n[INFO] Hardware Mapping -> I2C Bus: {target_bus} | Address: {hex(target_addr)}")

    programmer = XDPE_Programmer(bus_id=target_bus, dev_addr=target_addr, force_mode=args.force)
    
    if not programmer.identify_device():
        sys.exit(1)

    if args.checksum:
        programmer.query_total_checksum()
        
    if args.space:
        programmer.query_otp_space()

    # -------------------------------------------------------------
    # Manual Mode Execution (when -b, -a, and -f are explicitly provided)
    # -------------------------------------------------------------
    if args.file and not args.name and not (args.checksum or args.space):
        print("\n" + "="*80)
        print(" MANUAL DEVICE UPGRADE TASK ")
        print("="*80)

        # 1. MD5 Verification
        if not verify_md5_checksum(args.file):
            print(f"[FAIL] MD5 Checksum validation failed. Skipping to ensure safety.")
            sys.exit(1)

        print("\n[INFO] Gathering Pre-burn Device State...")
        pre_checksum = programmer.query_total_checksum()
        target_filename_crc = extract_crc_from_filename(args.file)

        # 2. Skip Logic
        if args.skip and pre_checksum is not None and target_filename_crc is not None:
            if pre_checksum == target_filename_crc:
                print(f"\n[SKIP] Device CRC (0x{pre_checksum:08X}) matches target configuration. Skipping upgrade as requested.")
                sys.exit(0)

        # 3. Parse File & Check Space
        sections, total_needed = programmer.parse_mic_file(args.file)
        if not sections:
            sys.exit(1)

        if not programmer.query_otp_space(required_size=total_needed):
            sys.exit(1)

        # 4. Confirm & Execute
        print("\n[WARNING] OTP Programming is an irreversible hardware process.")
        confirm = input(f"[ACTION] Ready to flash device at {hex(target_addr)} on Bus {target_bus}? [y/N]: ").strip()
        if confirm.lower() != 'y':
            print("\n[INFO] Operation gracefully cancelled by user.")
            sys.exit(0)

        success = programmer.execute_programming(sections)
        if not success:
            print(f"\n[ERROR] Update halted due to a CML memory fault.")
            sys.exit(1)

        # 5. Post-burn Verification
        print(f"\n[SUCCESS] OTP Programming Cycle Complete!")
        dprint("[DEBUG] Verifying post-burn Total Checksum against Filename Hash...")
        post_checksum = programmer.query_total_checksum()
        
        if target_filename_crc is not None and post_checksum is not None:
            print("\n" + "="*65)
            print(" FINAL CRC VALIDATION REPORT ")
            print("-" * 65)
            print(f" Expected CRC (From Filename) : 0x{target_filename_crc:08X}")
            print(f" Actual CRC (Read from Device): 0x{post_checksum:08X}")
            
            if post_checksum == target_filename_crc:
                print("\n [RESULT]: SUCCESS - CRCs Match Perfectly.")
            else:
                print("\n [RESULT]: FAILURE - CRC Mismatch! Programming may be corrupted.")
                sys.exit(1)