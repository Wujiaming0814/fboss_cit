#!/usr/bin/env python3
"""
NXP PN54x NFC Tool via I2C and NCI Protocol.

This script demonstrates how to interact with an NXP PN54x NFC controller
(like the PN7150 or PN7120) directly over an I2C bus using the NCI
(NFC Controller Interface) protocol.

Version History:
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
# ----------------------------------------

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
    OID_RF_DISCOVER_MAP = 0x00
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
    except Exception as e:
        return f"(Parsing exception: {e})"
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
    protocols = {0x01: 'T1T', 0x02: 'T2T (MIFARE/ISO14443-3A)', 0x03: 'T3T', 0x04: 'ISO-DEP (ISO14443-4)', 0x05: 'NFC-DEP'}
    techs = {0x00: 'NFC-A Passive Poll', 0x01: 'NFC-B Passive Poll', 0x02: 'NFC-F Passive Poll'}
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
    return info


def print_nfc_table(tag_info, ndef_info, mode="Read"):
    """Prints the tag and NDEF information in a formatted ASCII table."""
    uid_str = tag_info.get('uid', 'N/A').replace(':', ' ')
    protocol = tag_info.get('protocol', 'N/A')

    print("\n+" + "-"*60 + "+")
    print(f"|{'NFC Tag Information (Mode: ' + mode.capitalize() + ')':^60}|")
    print("+" + "-"*20 + "+" + "-"*39 + "+")
    print(f"| {'UID':<18} | {uid_str:<37} |")
    print(f"| {'Protocol':<18} | {protocol:<37} |")

    if ndef_info:
        print("+" + "-"*20 + "+" + "-"*39 + "+")
        print(f"| {'Max Capacity':<18} | {str(ndef_info.get('max_capacity', 'N/A')) + ' bytes':<37} |")

        if mode.lower() == 'read':
            print(f"| {'Content Length':<18} | {str(ndef_info.get('content_length', 'N/A')) + ' bytes':<37} |")
        else:
            print(f"| {'Written Length':<18} | {str(ndef_info.get('written_length', 'N/A')) + ' bytes':<37} |")

        print(f"| {'Record Type':<18} | {ndef_info.get('type', 'N/A'):<37} |")

        print("+" + "-"*20 + "+" + "-"*39 + "+")
        data_str = ndef_info.get('data', 'N/A')
        # Handle string truncation for the table display
        if len(data_str) > 37:
            data_str = data_str[:34] + "..."
        print(f"| {'Payload Data':<18} | {data_str:<37} |")

    print("+" + "-"*20 + "+" + "-"*39 + "+\n")


class PN54x:
    """Class to interact with a PN54x NFC chip via I2C."""
    def __init__(self, i2c_path, i2c_addr, reset_bus_path, reset_chip_addr, reset_reg, reset_val_enable, reset_val_disable):
        self.reset_reg, self.reset_val_enable, self.reset_val_disable = reset_reg, reset_val_enable, reset_val_disable
        self.i2c_fd, self.reset_fd = None, None
        try:
            self.i2c_fd = os.open(i2c_path, os.O_RDWR)
            fcntl.ioctl(self.i2c_fd, I2C_SLAVE_FORCE, i2c_addr)
            self.reset_fd = os.open(reset_bus_path, os.O_RDWR)
            fcntl.ioctl(self.reset_fd, I2C_SLAVE_FORCE, reset_chip_addr)
        except Exception as e:
            print(f"Error opening I2C buses: {e}")
            raise
        self.reset_chip()

    def reset_chip(self):
        try:
            os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_enable]))
            time.sleep(0.1)
            os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_disable]))
            time.sleep(0.1)
            os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_enable]))
            time.sleep(0.1)
        except Exception as e:
            print(f"Error during I2C reset: {e}")

    def write_packet(self, data):
        for attempt in range(3):
            try:
                os.write(self.i2c_fd, bytes(data))
                return True
            except Exception as e:
                if attempt == 2: print(f"I2C write error (final attempt): {e}")
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
            except Exception as e:
                if attempt == 2: print(f"I2C read error (header, final attempt): {e}")
                else: time.sleep(0.05)
        if not header_data or len(header_data) != NORMAL_MODE_HEADER_LEN: return None

        payload_len = header_data[NORMAL_MODE_LEN_OFFSET]
        if payload_len > 0:
            for attempt in range(3):
                try:
                    payload_data = os.read(self.i2c_fd, payload_len)
                    break
                except Exception as e:
                    if attempt == 2: print(f"I2C read error (payload, final attempt): {e}")
                    else: time.sleep(0.05)
            if len(payload_data) != payload_len: return None
            return header_data + payload_data
        return header_data

    def transceive_data(self, payload):
        nci_data_packet = NciPacket.build(NciPacket.MT_DATA, 0, 0, payload=bytes(payload))
        if not self.write_packet(nci_data_packet): return None

        start_time = time.time()
        while time.time() - start_time < 2.0:
            response_pkt_raw = self.read_packet(timeout_sec=0.5)
            if not response_pkt_raw: continue
            response_pkt = NciPacket.parse(response_pkt_raw)
            if not response_pkt: continue

            if response_pkt['mt'] == NciPacket.MT_DATA:
                return response_pkt['payload']
            if response_pkt['mt'] == NciPacket.MT_NTF and response_pkt['gid'] == NciPacket.GID_CORE and response_pkt['oid'] == 0x06:
                continue # Filter Credit NTFs
        return None

    def iso_dep_transceive(self, apdu):
        return self.transceive_data(apdu)

    def rf_deactivate(self):
        return self.write_packet([0x21, 0x06, 0x01, 0x00])

    def close(self):
        if self.reset_fd:
            try: os.write(self.reset_fd, bytes([self.reset_reg, self.reset_val_disable]))
            except: pass
            os.close(self.reset_fd)
        if self.i2c_fd: os.close(self.i2c_fd)


def read_ndef_iso_dep(nfc_chip):
    """Executes NDEF read sequence for ISO-DEP tags."""
    if not (resp := nfc_chip.iso_dep_transceive([0x00, 0xA4, 0x04, 0x00, 0x07, 0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01, 0x00])) or resp[-2:] != b'\x90\x00': return None
    if not (resp := nfc_chip.iso_dep_transceive([0x00, 0xA4, 0x00, 0x0C, 0x02, 0xE1, 0x03])) or resp[-2:] != b'\x90\x00': return None
    if not (cc_data := nfc_chip.iso_dep_transceive([0x00, 0xB0, 0x00, 0x00, 0x0F])) or cc_data[-2:] != b'\x90\x00': return None

    cc_file = cc_data[:-2]
    max_size = int.from_bytes(cc_file[3:5], 'big')
    ndef_file_id = int.from_bytes(cc_file[9:11], 'big')

    if not (resp := nfc_chip.iso_dep_transceive([0x00, 0xA4, 0x00, 0x0C, 0x02, (ndef_file_id >> 8) & 0xFF, ndef_file_id & 0xFF])) or resp[-2:] != b'\x90\x00': return None

    if not (len_data := nfc_chip.iso_dep_transceive([0x00, 0xB0, 0x00, 0x00, 0x02])) or len(len_data) < 4 or len_data[-2:] != b'\x90\x00': return None
    ndef_len = int.from_bytes(len_data[:2], 'big')

    if ndef_len == 0:
        return {'max_capacity': max_size, 'content_length': 0, 'type': 'Empty', 'data': 'No Data'}

    le = ndef_len if ndef_len <= 255 else 0x00
    if not (ndef_data := nfc_chip.iso_dep_transceive([0x00, 0xB0, 0x00, 0x02, le])) or ndef_data[-2:] != b'\x90\x00': return None

    ndef_content = ndef_data[:-2]
    parsed_text = parse_ndef_text(ndef_content)

    return {
        'max_capacity': max_size,
        'content_length': ndef_len,
        'type': 'Text' if parsed_text else 'Raw Hex',
        'data': parsed_text if parsed_text else ' '.join(f'{b:02X}' for b in ndef_content)
    }

def write_ndef_iso_dep(nfc_chip, text_data):
    """Executes NDEF write sequence for ISO-DEP tags using UPDATE BINARY."""
    ndef_payload = build_ndef_text_payload(text_data)
    total_len = len(ndef_payload)

    if not (resp := nfc_chip.iso_dep_transceive([0x00, 0xA4, 0x04, 0x00, 0x07, 0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01, 0x00])) or resp[-2:] != b'\x90\x00': return None
    if not (resp := nfc_chip.iso_dep_transceive([0x00, 0xA4, 0x00, 0x0C, 0x02, 0xE1, 0x03])) or resp[-2:] != b'\x90\x00': return None
    if not (cc_data := nfc_chip.iso_dep_transceive([0x00, 0xB0, 0x00, 0x00, 0x0F])) or cc_data[-2:] != b'\x90\x00': return None

    max_size = int.from_bytes(cc_data[3:5], 'big')
    if total_len > max_size: return None

    ndef_file_id = int.from_bytes(cc_data[9:11], 'big')
    if not (resp := nfc_chip.iso_dep_transceive([0x00, 0xA4, 0x00, 0x0C, 0x02, (ndef_file_id >> 8) & 0xFF, ndef_file_id & 0xFF])) or resp[-2:] != b'\x90\x00': return None

    reset_len_apdu = [0x00, 0xD6, 0x00, 0x00, 0x02, 0x00, 0x00]
    if not (resp := nfc_chip.iso_dep_transceive(reset_len_apdu)) or resp[-2:] != b'\x90\x00': return None

    write_data_apdu = [0x00, 0xD6, 0x00, 0x02, total_len] + list(ndef_payload)
    if not (resp := nfc_chip.iso_dep_transceive(write_data_apdu)) or resp[-2:] != b'\x90\x00': return None

    update_len_apdu = [0x00, 0xD6, 0x00, 0x00, 0x02, (total_len >> 8) & 0xFF, total_len & 0xFF]
    if not (resp := nfc_chip.iso_dep_transceive(update_len_apdu)) or resp[-2:] != b'\x90\x00': return None

    return {
        'max_capacity': max_size,
        'written_length': total_len,
        'type': 'Text',
        'data': text_data
    }

def main():
    parser = argparse.ArgumentParser(
        description="NXP PN54x NDEF Read/Write Tool",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument('-m', '--mode', type=str, choices=['read', 'write'],
                        help="Operation mode:\n  'read'  - Wait for a tag and print its contents.\n  'write' - Wait for a tag and write data to it.")
    parser.add_argument('-d', '--data', type=str, default="hello world",
                        help="The text data to write to the tag (used only in 'write' mode).")
    parser.add_argument('--i2c-bus', type=str, default=I2C_BUS_PATH,
                        help="The I2C bus number (e.g., 7) or full path (e.g., /dev/i2c-7) (default: 7)")
    parser.add_argument('--i2c-addr', type=lambda x: int(x,0), default=I2C_ADDR,
                        help="The I2C slave address of the NFC controller (default: 0x28)")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    # Parse the I2C bus parameter gracefully
    i2c_bus_str = str(args.i2c_bus)
    actual_i2c_path = f"/dev/i2c-{i2c_bus_str}" if i2c_bus_str.isdigit() else i2c_bus_str

    nfc_chip = None

    try:
        nfc_chip = PN54x(actual_i2c_path, args.i2c_addr, RESET_I2C_BUS_PATH, RESET_CHIP_ADDR, RESET_REG, RESET_VAL_ENABLE, RESET_VAL_DISABLE)

        # Init & Map
        nfc_chip.write_packet([0x20, 0x00, 0x01, 0x01]); nfc_chip.read_packet()
        nfc_chip.write_packet([0x20, 0x01, 0x00]); nfc_chip.read_packet()
        nfc_chip.write_packet([0x21, 0x00, 0x0A, 0x03, 0x04, 0x01, 0x02, 0x05, 0x01, 0x03, 0x02, 0x01, 0x01])
        nfc_chip.read_packet()

        # Start Discovery
        discover_cmd = [0x21, 0x03, 0x07, 0x03, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00]

        if nfc_chip.write_packet(discover_cmd):
            resp = nfc_chip.read_packet()
            if resp and len(resp) > 3 and resp[3] == 0x00:
                while True:
                    notification = nfc_chip.read_packet(timeout_sec=2.0)
                    if notification is None: continue

                    pkt = NciPacket.parse(notification)
                    if not pkt: continue

                    if pkt['mt'] == NciPacket.MT_NTF and pkt['gid'] == NciPacket.GID_RF and pkt['oid'] == NciPacket.OID_RF_INTF_ACTIVATED:
                        tag_info = parse_intf_activated_ntf(pkt['payload'])
                        if tag_info and tag_info.get('protocol') == 'ISO-DEP (ISO14443-4)':

                            if args.mode == 'read':
                                result = read_ndef_iso_dep(nfc_chip)
                                if result:
                                    print_nfc_table(tag_info, result, mode='Read')
                                    break

                            elif args.mode == 'write':
                                result = write_ndef_iso_dep(nfc_chip, args.data)
                                if result:
                                    print_nfc_table(tag_info, result, mode='Write')
                                    break

                        # Briefly deactivate if read/write failed to try again
                        time.sleep(1)
                        nfc_chip.rf_deactivate()

                    elif pkt['mt'] == NciPacket.MT_NTF and pkt['gid'] == NciPacket.GID_RF and pkt['oid'] == NciPacket.OID_RF_DEACTIVATE:
                        if nfc_chip.write_packet(discover_cmd): nfc_chip.read_packet()
            else:
                print("Failed to start discovery.")
    except KeyboardInterrupt:
        print("\nOperation aborted by user.")
    finally:
        if nfc_chip:
            nfc_chip.rf_deactivate()
            time.sleep(0.2)
            nfc_chip.close()

if __name__ == '__main__':
    main()