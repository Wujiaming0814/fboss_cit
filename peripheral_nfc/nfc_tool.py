#!/usr/bin/env python3
"""
NXP PN54x NFC Tool via I2C and NCI Protocol.

This script demonstrates how to interact with an NXP PN54x NFC controller
(like the PN7150 or PN7120) directly over an I2C bus using the NCI
(NFC Controller Interface) protocol.

Version History:
    v1.5.0 (2026-05-28):
        - Expanded ASCII table layout width to exactly 80 columns.
        - Implemented dynamic string wrapping logic for unlimited payload data output.
    v1.4.0 (2026-05-28):
        - Added --verbose (-v) command-line flag to control low-level NCI diagnostics.
        - Cleaned up default console output for production runs while preserving debugging tools.
        - Enforced strict 4-byte block size constraints for standard T5T tags.
        - Resolved trailing NCI packet padding calculations that caused write timeouts and read shifts.
        - Added comprehensive raw NCI hex data logging for T5T write path diagnostics.
        - Introduced a mandatory 50ms RF Turnaround Guard Time before each write command.
        - Added native ISO 15693 error code decoder to diagnose explicit tag write rejections.
    v1.3.0 (2026-05-27):
        - Added full support for T5T (ISO/IEC 15693 / Type V) tags.
        - Updated NCI RF_DISCOVER_MAP and RF_DISCOVER to enable NFC-V Passive Poll.
        - Implemented `read_ndef_t5t` and `write_ndef_t5t` block-based I/O functions.
        - Added graceful error handling for missing NFC controllers (I2C failures).
        - Implemented a configurable polling timeout (--timeout) to exit if no tag is found.
    v1.2.0 (2026-05-25):
        - Updated --i2c-bus parameter to accept just the bus number (e.g., 7)
          and automatically resolve it to the full device path (/dev/i2c-7).
        - Removed redundant polling wait prompts.
        - Redesigned the standard output into a clean ASCII table format.
        - Refactored read/write functions to return data dictionaries for UI rendering.
        - Refactored main execution logic into a dedicated main() function.
        - Added --i2c-bus and --i2c-addr parameters with defaults.
        - Script now displays help menu by default if run without arguments.
    v1.1.0 (2026-05-22):
        - Added argparse for command-line parameter support (--mode, --data).
        - Implemented NDEF writing functionality for ISO-DEP (Type 4A) tags.
    v1.0.0 (2026-05-22):
        - Initial working version.

Author: Lucas/celestica
License: GPL-3.0 License
"""

import sys
import time
import select
import os
import fcntl
import argparse

# --- Hardware Reset Configuration Constants ---
I2C_BUS_PATH = "/dev/i2c-7"
I2C_ADDR = 0x28
RESET_I2C_BUS_PATH = "/dev/i2c-15"
RESET_CHIP_ADDR = 0x60
RESET_REG = 0x13
RESET_VAL_ENABLE = 0xff
RESET_VAL_DISABLE = 0xef
# ----------------------------------------------

I2C_SLAVE_FORCE = 0x0706
NORMAL_MODE_HEADER_LEN = 3
NORMAL_MODE_LEN_OFFSET = 2

class NciPacket:
    """A helper class to build and parse NCI data packets."""
    MT_DATA = 0
    MT_CMD = 1
    MT_RSP = 2
    MT_NTF = 3
    GID_CORE = 0x00
    GID_RF = 0x01
    OID_RF_DISCOVER = 0x03
    OID_RF_DEACTIVATE = 0x06
    OID_RF_INTF_ACTIVATED = 0x05

    @staticmethod
    def build(mt, gid, oid, payload=b''):
        header0 = (mt << 5) | gid
        header1 = oid
        return bytes([header0, header1, len(payload)]) + payload

    @staticmethod
    def parse(data):
        if not data or len(data) < 3: return None
        mt = (data[0] >> 5) & 0x07
        gid = data[0] & 0x0F
        oid = data[1] & 0x3F
        length = data[2]
        payload = data[3:3+length]
        return {
            'mt': mt,
            'mt_name': ['DATA', 'CMD', 'RSP', 'NTF'][mt] if mt < 4 else '?',
            'gid': gid, 'oid': oid, 'length': length, 'payload': payload,
            'raw': data[:3+length]
        }

def parse_ndef_text(ndef_bytes):
    """Minimalist parser for NDEF Text records."""
    try:
        if len(ndef_bytes) < 7: return None
        if ndef_bytes[0] == 0xD1 and ndef_bytes[3] == 0x54:
            payload_len = ndef_bytes[2]
            payload = ndef_bytes[4 : 4 + payload_len]
            status_byte = payload[0]
            lang_len = status_byte & 0x3F
            text_bytes = payload[1 + lang_len :]
            return text_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return None
    return None

def build_ndef_text_payload(text_data):
    """Constructs a raw NDEF Text Record (English) byte array."""
    text_bytes = text_data.encode('utf-8')
    payload_len = 1 + 2 + len(text_bytes)
    header = bytes([0xD1, 0x01, payload_len, 0x54, 0x02, 0x65, 0x6E])
    return header + text_bytes

def parse_intf_activated_ntf(pkt_payload):
    """Parses an RF_INTF_ACTIVATED_NTF notification."""
    if not pkt_payload or len(pkt_payload) < 7: return None

    protocols = {
        0x01: 'T1T', 0x02: 'T2T (MIFARE/ISO14443-3A)', 0x03: 'T3T',
        0x04: 'ISO-DEP (ISO14443-4)', 0x05: 'NFC-DEP', 0x06: 'T5T (ISO15693)'
    }
    techs = {
        0x00: 'NFC-A Passive Poll', 0x01: 'NFC-B Passive Poll',
        0x02: 'NFC-F Passive Poll', 0x06: 'NFC-V Passive Poll'
    }

    info = {
        'rf_intf': pkt_payload[1],
        'protocol': protocols.get(pkt_payload[2], f'Unknown (0x{pkt_payload[2]:02x})'),
        'tech': techs.get(pkt_payload[3], f'Unknown (0x{pkt_payload[3]:02x})'),
    }

    if pkt_payload[3] == 0x00: # NFC-A
        tech_params_len = pkt_payload[6]
        tech_params = pkt_payload[7:7+tech_params_len]
        if len(tech_params) >= 3:
            nfcid1_len = tech_params[2]
            if len(tech_params) >= 3 + nfcid1_len:
                nfcid1 = tech_params[3:3+nfcid1_len]
                info['uid'] = ':'.join(f'{b:02X}' for b in nfcid1)

    elif pkt_payload[3] == 0x06: # NFC-V
        tech_params_len = pkt_payload[6]
        tech_params = pkt_payload[7:7+tech_params_len]
        if len(tech_params) >= 10:
            nfcid2 = tech_params[2:10]
            info['uid'] = ':'.join(f'{b:02X}' for b in nfcid2)

    return info


def print_nfc_table(tag_info, ndef_info, mode="Read"):
    """Prints the tag and NDEF information in a formatted 80-column ASCII table with line wrapping."""
    uid_str = tag_info.get('uid', 'N/A').replace(':', ' ')
    protocol = tag_info.get('protocol', 'N/A')

    # Expanded outer bounds to 80 characters wide
    print("\n+" + "-"*78 + "+")
    print(f"|{'NFC Tag Information (Mode: ' + mode.capitalize() + ')':^78}|")
    print("+" + "-"*20 + "+" + "-"*57 + "+")
    print(f"| {'UID':<18} | {uid_str:<55} |")
    print(f"| {'Protocol':<18} | {protocol:<55} |")

    if ndef_info:
        print("+" + "-"*20 + "+" + "-"*57 + "+")
        print(f"| {'Max Capacity':<18} | {str(ndef_info.get('max_capacity', 'N/A')) + ' bytes':<55} |")

        if mode.lower() == 'read':
            print(f"| {'Content Length':<18} | {str(ndef_info.get('content_length', 'N/A')) + ' bytes':<55} |")
        else:
            print(f"| {'Written Length':<18} | {str(ndef_info.get('written_length', 'N/A')) + ' bytes':<55} |")

        print(f"| {'Record Type':<18} | {ndef_info.get('type', 'N/A'):<55} |")

        print("+" + "-"*20 + "+" + "-"*57 + "+")
        data_str = ndef_info.get('data', 'N/A')
        if not data_str:
            data_str = "No Data"

        # Dynamically wrap long strings cleanly across lines using chunks of 55 characters
        chunks = [data_str[i:i+55] for i in range(0, len(data_str), 55)]
        print(f"| {'Payload Data':<18} | {chunks[0]:<55} |")
        for chunk in chunks[1:]:
            print(f"| {'':<18} | {chunk:<55} |")

    print("+" + "-"*20 + "+" + "-"*57 + "+\n")


class PN54x:
    """Class to interact with a PN54x NFC chip via I2C."""
    def __init__(self, i2c_path, i2c_addr, reset_bus_path, reset_chip_addr, reset_reg, reset_val_enable, reset_val_disable):
        self.reset_reg = reset_reg
        self.reset_val_enable = reset_val_enable
        self.reset_val_disable = reset_val_disable
        self.i2c_fd = None
        self.reset_fd = None

        try:
            self.i2c_fd = os.open(i2c_path, os.O_RDWR)
            fcntl.ioctl(self.i2c_fd, I2C_SLAVE_FORCE, i2c_addr)
            self.reset_fd = os.open(reset_bus_path, os.O_RDWR)
            fcntl.ioctl(self.reset_fd, I2C_SLAVE_FORCE, reset_chip_addr)
        except OSError as e:
            raise Exception(f"Failed to open I2C bus {i2c_path} or {reset_bus_path}: {e}")

        self.reset_chip()

    def reset_chip(self):
        try:
            os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_enable]))
            time.sleep(0.1)
            os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_disable]))
            time.sleep(0.1)
            os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_enable]))
            time.sleep(0.1)
        except Exception:
            pass

    def write_packet(self, data, suppress_error=False):
        for attempt in range(3):
            try:
                os.write(self.i2c_fd, bytes(data))
                return True
            except Exception:
                if attempt == 2 and not suppress_error: pass
                else: time.sleep(0.1)
        return False

    def read_packet(self, timeout_sec=2.0):
        r, _, _ = select.select([self.i2c_fd], [], [], timeout_sec)
        if not r: return None
        time.sleep(0.001)

        header_data = None
        for attempt in range(3):
            try:
                header_data = os.read(self.i2c_fd, NORMAL_MODE_HEADER_LEN)
                break
            except Exception:
                if attempt < 2: time.sleep(0.05)

        if not header_data or len(header_data) != NORMAL_MODE_HEADER_LEN: return None

        payload_len = header_data[NORMAL_MODE_LEN_OFFSET]
        if payload_len > 0:
            for attempt in range(3):
                try:
                    payload_data = os.read(self.i2c_fd, payload_len)
                    break
                except Exception:
                    if attempt < 2: time.sleep(0.05)
            if len(payload_data) != payload_len: return None
            return header_data + payload_data
        return header_data

    def transceive_data(self, payload, verbose=False):
        nci_data_packet = NciPacket.build(NciPacket.MT_DATA, 0, 0, payload=bytes(payload))

        if verbose:
            print(f"    [NCI TX] -> {bytes(payload).hex().upper()}")

        if not self.write_packet(nci_data_packet): return None

        start_time = time.time()
        while time.time() - start_time < 2.0:
            response_pkt_raw = self.read_packet(timeout_sec=0.5)
            if not response_pkt_raw: continue
            response_pkt = NciPacket.parse(response_pkt_raw)
            if not response_pkt: continue

            if response_pkt['mt'] == NciPacket.MT_DATA:
                if verbose:
                    print(f"    [NCI RX] <- {bytes(response_pkt['payload']).hex().upper()}")
                return response_pkt['payload']

            if response_pkt['mt'] == NciPacket.MT_NTF and response_pkt['gid'] == NciPacket.GID_CORE and response_pkt['oid'] == 0x06:
                continue
        return None

    def rf_deactivate(self):
        return self.write_packet([0x21, 0x06, 0x01, 0x00], suppress_error=True)

    def close(self):
        if self.reset_fd:
            try: os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_disable]))
            except: pass
            os.close(self.reset_fd)
        if self.i2c_fd: os.close(self.i2c_fd)


# ========================================================
#                  ISO-DEP (TYPE 4A) OPS
# ========================================================
def read_ndef_iso_dep(nfc_chip, verbose=False):
    if not (resp := nfc_chip.transceive_data([0x00, 0xA4, 0x04, 0x00, 0x07, 0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01, 0x00], verbose=verbose)) or resp[-2:] != b'\x90\x00': return None
    if not (resp := nfc_chip.transceive_data([0x00, 0xA4, 0x00, 0x0C, 0x02, 0xE1, 0x03], verbose=verbose)) or resp[-2:] != b'\x90\x00': return None
    if not (cc_data := nfc_chip.transceive_data([0x00, 0xB0, 0x00, 0x00, 0x0F], verbose=verbose)) or cc_data[-2:] != b'\x90\x00': return None

    cc_file = cc_data[:-2]
    max_size = int.from_bytes(cc_file[3:5], 'big')
    ndef_file_id = int.from_bytes(cc_file[9:11], 'big')

    if not (resp := nfc_chip.transceive_data([0x00, 0xA4, 0x00, 0x0C, 0x02, (ndef_file_id >> 8) & 0xFF, ndef_file_id & 0xFF], verbose=verbose)) or resp[-2:] != b'\x90\x00': return None
    if not (len_data := nfc_chip.transceive_data([0x00, 0xB0, 0x00, 0x00, 0x02], verbose=verbose)) or len(len_data) < 4 or len_data[-2:] != b'\x90\x00': return None

    ndef_len = int.from_bytes(len_data[:2], 'big')
    if ndef_len == 0:
        return {'max_capacity': max_size, 'content_length': 0, 'type': 'Empty', 'data': 'No Data'}

    le = ndef_len if ndef_len <= 255 else 0x00
    if not (ndef_data := nfc_chip.transceive_data([0x00, 0xB0, 0x00, 0x02, le], verbose=verbose)) or ndef_data[-2:] != b'\x90\x00': return None

    ndef_content = ndef_data[:-2]
    parsed_text = parse_ndef_text(ndef_content)

    return {
        'max_capacity': max_size,
        'content_length': ndef_len,
        'type': 'Text' if parsed_text else 'Raw Hex',
        'data': parsed_text if parsed_text else ' '.join(f'{b:02X}' for b in ndef_content)
    }

def write_ndef_iso_dep(nfc_chip, text_data, verbose=False):
    ndef_payload = build_ndef_text_payload(text_data)
    total_len = len(ndef_payload)

    if not (resp := nfc_chip.transceive_data([0x00, 0xA4, 0x04, 0x00, 0x07, 0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01, 0x00], verbose=verbose)) or resp[-2:] != b'\x90\x00': return None
    if not (resp := nfc_chip.transceive_data([0x00, 0xA4, 0x00, 0x0C, 0x02, 0xE1, 0x03], verbose=verbose)) or resp[-2:] != b'\x90\x00': return None
    if not (cc_data := nfc_chip.transceive_data([0x00, 0xB0, 0x00, 0x00, 0x0F], verbose=verbose)) or cc_data[-2:] != b'\x90\x00': return None

    max_size = int.from_bytes(cc_data[3:5], 'big')
    if total_len > max_size:
        print(f"\n  [Error] Data too large ({total_len}B). Max capacity is {max_size}B.")
        return None

    ndef_file_id = int.from_bytes(cc_data[9:11], 'big')
    if not (resp := nfc_chip.transceive_data([0x00, 0xA4, 0x00, 0x0C, 0x02, (ndef_file_id >> 8) & 0xFF, ndef_file_id & 0xFF], verbose=verbose)) or resp[-2:] != b'\x90\x00': return None

    reset_len_apdu = [0x00, 0xD6, 0x00, 0x00, 0x02, 0x00, 0x00]
    if not (resp := nfc_chip.transceive_data(reset_len_apdu, verbose=verbose)) or resp[-2:] != b'\x90\x00': return None

    write_data_apdu = [0x00, 0xD6, 0x00, 0x02, total_len] + list(ndef_payload)
    if not (resp := nfc_chip.transceive_data(write_data_apdu, verbose=verbose)) or resp[-2:] != b'\x90\x00': return None

    update_len_apdu = [0x00, 0xD6, 0x00, 0x00, 0x02, (total_len >> 8) & 0xFF, total_len & 0xFF]
    if not (resp := nfc_chip.transceive_data(update_len_apdu, verbose=verbose)) or resp[-2:] != b'\x90\x00': return None

    return {
        'max_capacity': max_size,
        'written_length': total_len,
        'type': 'Text',
        'data': text_data
    }


# ========================================================
#                  T5T (ISO15693 / TYPE V) OPS
# ========================================================
def decode_t5t_error(error_byte):
    codes = {
        0x01: "Command not supported",
        0x02: "Command not recognized (format error)",
        0x03: "Option not supported",
        0x0F: "Unknown Error",
        0x10: "Block not available (Out of bounds)",
        0x11: "Block already Locked (Write Protected)",
        0x12: "Block is locked and cannot be unlocked",
        0x13: "Block programming failed (Erase/Write error)",
        0x14: "Block locking failed"
    }
    return codes.get(error_byte, f"Vendor Specific Error (0x{error_byte:02X})")

def read_ndef_t5t(nfc_chip, verbose=False):
    """Executes NDEF read sequence with conditional diagnostic hex streaming."""
    if verbose: print("  [Step 1] Extracting CC configuration...")
    resp = nfc_chip.transceive_data([0x02, 0x20, 0x00], verbose=verbose)
    if not resp or resp[0] != 0x00: return None
    cc_data = resp[1:]

    if not cc_data or cc_data[0] not in (0xE1, 0xE2): return None

    block_size = 4
    max_size = cc_data[2] * 8
    memory = bytearray()
    current_block = 1

    if verbose: print("  [Step 2] Streaming tag allocation block space...")
    while len(memory) < 16:
        resp = nfc_chip.transceive_data([0x02, 0x20, current_block], verbose=verbose)
        if not resp or resp[0] != 0x00: break
        memory.extend(resp[1:1+block_size])
        current_block += 1

    idx = 0
    while idx < len(memory) and memory[idx] != 0x03:
        if memory[idx] == 0x00: idx += 1
        elif memory[idx] == 0xFE: return None
        else:
            l = memory[idx+1] if idx+1 < len(memory) else 0
            idx += (4 + (memory[idx+2]<<8 | memory[idx+3])) if l == 0xFF else (2 + l)

    if idx >= len(memory) or memory[idx] != 0x03: return None

    idx += 1
    if memory[idx] == 0xFF:
        if idx + 2 >= len(memory): return None
        ndef_len = (memory[idx+1] << 8) | memory[idx+2]
        idx += 3
    else:
        ndef_len = memory[idx]
        idx += 1

    if ndef_len == 0:
        return {'max_capacity': max_size, 'content_length': 0, 'type': 'Empty', 'data': 'No Data'}

    required_mem_len = idx + ndef_len
    while len(memory) < required_mem_len:
        resp = nfc_chip.transceive_data([0x02, 0x20, current_block], verbose=verbose)
        if not resp or resp[0] != 0x00: break
        memory.extend(resp[1:1+block_size])
        current_block += 1

    ndef_data = memory[idx : idx+ndef_len]
    if len(ndef_data) < ndef_len: return None

    parsed_text = parse_ndef_text(ndef_data)

    return {
        'max_capacity': max_size,
        'content_length': ndef_len,
        'type': 'Text' if parsed_text else 'Raw Hex',
        'data': parsed_text if parsed_text else ' '.join(f'{b:02X}' for b in ndef_data)
    }


def write_ndef_t5t(nfc_chip, text_data, verbose=False):
    """Executes NDEF write sequence with conditional NCI diagnostic logging."""
    ndef_payload = build_ndef_text_payload(text_data)
    ndef_len = len(ndef_payload)

    if verbose: print("  [Step 1] Extracting CC configuration...")
    resp = nfc_chip.transceive_data([0x02, 0x20, 0x00], verbose=verbose)
    if not resp or resp[0] != 0x00: return None
    cc_data = resp[1:]

    block_size = 4
    max_size = cc_data[2] * 8

    if ndef_len + 4 > max_size:
        print(f"\n  [Error] Data too large ({ndef_len}B). Max capacity is {max_size}B.")
        return None

    if ndef_len >= 0xFF:
        tlv = bytearray([0x03, 0xFF, (ndef_len>>8)&0xFF, ndef_len&0xFF]) + ndef_payload + bytearray([0xFE])
    else:
        tlv = bytearray([0x03, ndef_len]) + ndef_payload + bytearray([0xFE])

    while len(tlv) % block_size != 0: tlv.append(0x00)
    blocks_to_write = [tlv[i : i+block_size] for i in range(0, len(tlv), block_size)]

    write_flags = 0x02

    def write_and_verify(block_num, data_bytes):
        if verbose: print(f"\n  === Diagnosing Block {block_num} ===")
        time.sleep(0.05)

        write_success = False
        resp = nfc_chip.transceive_data([write_flags, 0x21, block_num] + list(data_bytes), verbose=verbose)
        if resp:
            if resp[0] == 0x00:
                write_success = True
            elif resp[0] & 0x01:
                err_label = decode_t5t_error(resp[1])
                print(f"  [Error] Card explicitly rejected transaction: {err_label}")
                return False

        if not write_success:
            print(f"  [Error] Write execution timed out / dropped at block {block_num}")
            return False

        if verbose: print(f"  [Verify] Polling block {block_num} memory check...")
        for check in range(5):
            time.sleep(0.03)
            verify_resp = nfc_chip.transceive_data([0x02, 0x20, block_num], verbose=verbose)
            if verify_resp and verify_resp[0] == 0x00:
                if bytes(verify_resp[1:1+len(data_bytes)]) == bytes(data_bytes):
                    if verbose: print(f"  [Verify] Block {block_num} verified successfully.")
                    return True
                else:
                    if verbose: print(f"  [Verify] Block {block_num} data mismatch!")
                    return False

        print(f"  [Error] Timeout verifying block {block_num} state.")
        return False

    if verbose: print("\n  [Step 2] Securing length field layout...")
    erase_blk = bytearray([0x03, 0x00, 0x00, 0x00])[:block_size]
    if not write_and_verify(1, erase_blk):
        return None

    if verbose: print("\n  [Step 3] Flushing data blocks...")
    for i, blk in enumerate(blocks_to_write[1:], start=2):
        if not write_and_verify(i, bytearray(blk)):
            return None

    if verbose: print("\n  [Step 4] Committing length block verification...")
    if not write_and_verify(1, bytearray(blocks_to_write[0])):
        return None

    return {
        'max_capacity': max_size,
        'written_length': ndef_len,
        'type': 'Text',
        'data': text_data
    }

def main():
    parser = argparse.ArgumentParser(
        description="NXP PN54x NDEF Read/Write Tool",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument('-m', '--mode', type=str, choices=['read', 'write'], default='read',
                        help="Operation mode:\n  'read'  - Wait for a tag and print its contents.\n  'write' - Wait for a tag and write data to it.")
    parser.add_argument('-d', '--data', type=str, default="hello world",
                        help="The text data to write to the tag (used only in 'write' mode).")
    parser.add_argument('--i2c-bus', type=str, default=I2C_BUS_PATH,
                        help="The I2C bus number (e.g., 7) or full path (e.g., /dev/i2c-7) (default: 7)")
    parser.add_argument('--i2c-addr', type=lambda x: int(x,0), default=I2C_ADDR,
                        help="The I2C slave address of the NFC controller (default: 0x28)")
    parser.add_argument('-t', '--timeout', type=int, default=30,
                        help="Timeout in seconds to wait for an NFC tag (0 for infinite, default: 30)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Enable low-level NCI data stream trace logging.")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    i2c_bus_str = str(args.i2c_bus)
    actual_i2c_path = f"/dev/i2c-{i2c_bus_str}" if i2c_bus_str.isdigit() else i2c_bus_str

    nfc_chip = None

    try:
        try:
            nfc_chip = PN54x(actual_i2c_path, args.i2c_addr, RESET_I2C_BUS_PATH, RESET_CHIP_ADDR, RESET_REG, RESET_VAL_ENABLE, RESET_VAL_DISABLE)
        except Exception as e:
            print(f"\n[Error] Hardware initialization failed. {e}")
            sys.exit(1)

        if not nfc_chip.write_packet([0x20, 0x00, 0x01, 0x01]):
            print(f"\n[Error] NFC Controller not found or unreachable on {actual_i2c_path} at addr 0x{args.i2c_addr:02X}.")
            sys.exit(1)

        nfc_chip.read_packet()
        nfc_chip.write_packet([0x20, 0x01, 0x00]); nfc_chip.read_packet()

        discover_map_cmd = [
            0x21, 0x00, 0x0D,
            0x04,
            0x04, 0x01, 0x02,
            0x05, 0x01, 0x03,
            0x02, 0x01, 0x01,
            0x06, 0x01, 0x01,
        ]
        nfc_chip.write_packet(discover_map_cmd); nfc_chip.read_packet()

        discover_cmd = [
            0x21, 0x03, 0x09,
            0x04,
            0x00, 0x00,
            0x01, 0x00,
            0x02, 0x00,
            0x06, 0x00,
        ]

        if nfc_chip.write_packet(discover_cmd):
            resp = nfc_chip.read_packet()
            if resp and len(resp) > 3 and resp[3] == 0x00:
                print(f"Polling started... waiting for tag (Timeout: {args.timeout}s)")
                polling_start_time = time.time()

                while True:
                    if args.timeout > 0 and (time.time() - polling_start_time) > args.timeout:
                        print(f"\n[Error] NFC Tag not found within {args.timeout} seconds. Timeout reached.")
                        break

                    notification = nfc_chip.read_packet(timeout_sec=0.5)
                    if notification is None: continue

                    pkt = NciPacket.parse(notification)
                    if not pkt: continue

                    if pkt['mt'] == NciPacket.MT_NTF and pkt['gid'] == NciPacket.GID_RF and pkt['oid'] == NciPacket.OID_RF_INTF_ACTIVATED:
                        tag_info = parse_intf_activated_ntf(pkt['payload'])
                        if tag_info:
                            protocol = tag_info.get('protocol')

                            if protocol == 'ISO-DEP (ISO14443-4)':
                                if args.mode == 'read':
                                    result = read_ndef_iso_dep(nfc_chip, verbose=args.verbose)
                                    if result:
                                        print_nfc_table(tag_info, result, mode='Read')
                                        break
                                elif args.mode == 'write':
                                    result = write_ndef_iso_dep(nfc_chip, args.data, verbose=args.verbose)
                                    if result:
                                        print_nfc_table(tag_info, result, mode='Write')
                                        break

                            elif protocol == 'T5T (ISO15693)':
                                if args.mode == 'read':
                                    result = read_ndef_t5t(nfc_chip, verbose=args.verbose)
                                    if result:
                                        print_nfc_table(tag_info, result, mode='Read')
                                        break
                                elif args.mode == 'write':
                                    result = write_ndef_t5t(nfc_chip, args.data, verbose=args.verbose)
                                    if result:
                                        print_nfc_table(tag_info, result, mode='Write')
                                        break

                        time.sleep(1)
                        nfc_chip.rf_deactivate()
                        polling_start_time = time.time()

                    elif pkt['mt'] == NciPacket.MT_NTF and pkt['gid'] == NciPacket.GID_RF and pkt['oid'] == NciPacket.OID_RF_DEACTIVATE:
                        if nfc_chip.write_packet(discover_cmd): nfc_chip.read_packet()
            else:
                print("\n[Error] Failed to start RF discovery protocol.")
    except KeyboardInterrupt:
        print("\nOperation aborted by user.")
    finally:
        if nfc_chip:
            nfc_chip.rf_deactivate()
            time.sleep(0.2)
            nfc_chip.close()

if __name__ == '__main__':
    main()