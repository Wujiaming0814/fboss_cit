# NXP PN54x NFC NDEF Tool

A lightweight, purely user-space Python script to interact with NXP PN54x (such as PN7120 and PN7150) NFC controllers over I2C. This tool utilizes the NCI (NFC Controller Interface) protocol to perform NDEF (NFC Data Exchange Format) read and write operations, entirely bypassing the need for complex, hardware-specific kernel space drivers.

## Features
- **No Kernel Driver Required:** Communicates directly with the NFC chip via I2C (`/dev/i2c-x`).
- **NCI Protocol Stack in Python:** Implements core NCI commands (Reset, Init, Discover, Map) and ISO-DEP / NDEF APDU sequences natively.
- **Robust Error Handling:** Built-in I2C retry mechanisms and NCI flow-control (Credit NTF) filtering.
- **Read & Write Modes:** Supports both reading existing NDEF text records and writing new text payloads to ISO-DEP (Type 4A) tags.
- **Clean Output:** Renders NFC tag UID and NDEF payload information in a clean, human-readable ASCII table.

## Prerequisites
1. **Linux Environment:** Tested on standard Linux distributions (e.g., Ubuntu, Debian, Raspbian) running on embedded boards or Raspberry Pi.
2. **I2C & GPIO Access:** The tool requires standard `i2c-dev` support. The user executing the script must have permission to read/write to `/dev/i2c-*` devices.
3. **Hardware Setup:**
   - An NXP NFC controller connected via I2C.
   - The VEN (Reset/Enable) pin of the NFC chip connected to a controllable I/O expander or GPIO (this is adaptable in the code).

## Installation
The tool relies entirely on Python 3 standard libraries (`sys`, `time`, `select`, `os`, `fcntl`, `argparse`). No third-party packages are required.

Just download the script and ensure it is executable:
```bash
chmod +x nfc_tool.py
```

## Usage
You can display the help menu and parameter details by running:
```bash
python3 nfc_tool.py --help
```

## Command Line Arguments
```bash
 -h, --help            show this help message and exit
  -m {read,write}, --mode {read,write}
                        Operation mode:
                          'read'  - Wait for a tag and print its contents.
                          'write' - Wait for a tag and write data to it.
  -d DATA, --data DATA  The text data to write to the tag (used only in 'write' mode).
  --i2c-bus I2C_BUS     The I2C bus number (e.g., 7) or full path (e.g., /dev/i2c-7) (default: 7)
  --i2c-addr I2C_ADDR   The I2C slave address of the NFC controller (default: 0x28)
  -t TIMEOUT, --timeout TIMEOUT
                        Timeout in seconds to wait for an NFC tag (0 for infinite, default: 30)
  -v, --verbose         Enable low-level NCI data stream trace logging.
```

## Examples
1. Reading an NFC Tag (Default)

Run the script in read mode and tap an ISO-DEP (Type 4A) formatted tag to the antenna.
```bash
python3 nfc_tool.py -m read --i2c-bus 7 --i2c-addr 0x28
```

### Expected Output:

```Plaintext
Polling started... waiting for tag (Timeout: 30s)

+------------------------------------------------------------------------------+
|                       NFC Tag Information (Mode: Read)                       |
+--------------------+---------------------------------------------------------+
| UID                | 04 C7 48 92 06 10 90                                    |
| Protocol           | ISO-DEP (ISO14443-4)                                    |
+--------------------+---------------------------------------------------------+
| Max Capacity       | 256 bytes                                               |
| Content Length     | 34 bytes                                                |
| Record Type        | Text                                                    |
+--------------------+---------------------------------------------------------+
| Payload Data       | CLS NFC Testing 2026 May 29                             |
+--------------------+---------------------------------------------------------+
```

2. Writing to an NFC Tag
Run the script in write mode and provide the text payload using the -d argument. The script will wait until a tag is detected and then execute the UPDATE BINARY APDU sequence.

Bash
python3 nfc_tool.py -m write -d "Hello World" --i2c-bus 7
Hardware Reset Configuration
By default, the script triggers a hardware reset (Low-High-Low sequence) to stabilize the PN54x chip before sending any NCI commands. The current implementation uses an I2C I/O expander located at RESET_CHIP_ADDR (0x60) on RESET_I2C_BUS_PATH.

If your VEN/Reset pin is connected to a standard Linux GPIO instead, you can modify the reset_chip function inside the PN54x class to write to /sys/class/gpio/gpioX/value.

## Acknowledgements

This project is a lightweight, user-space Python implementation inspired by and derived from the official NXP [linux_libnfc-nci](https://github.com/NXPNFCLinux/linux_libnfc-nci) stack. The goal was to create a dependency-free tool for basic NDEF operations without needing the full kernel-space driver and library.

-   **Original NXP Project:** NXPNFCLinux/linux_libnfc-nci

## License
This project is licensed under the GPL-3.0 License.
