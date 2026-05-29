# StrataKit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)

**StrataKit** is an all-in-one hardware engineering, low-level diagnostics, and bare-metal provisioning toolkit. It manages the entire lifecycle of open compute infrastructure and white-box network systems—spanning from silicon-level bus debugging up to data center rack-level automated deployments.

The name **StrataKit** represents its capability to operate seamlessly across multiple layers (*strata*) of the hardware and infrastructure stack.

---

## 🏗️ Technical Architecture (The Strata Stack)

StrataKit organizes its mixture of tools into vertical, function-driven layers, allowing hardware engineers and infrastructure SREs to interact safely with different levels of the machine:

```text
       ┌────────────────────────────────────────────────────────┐
       │ Layer 4: Rack Provisioning (DHCP, iPXE, OS Install)    │  --> rack_provisioning/
       └────────────────────────────────────────────────────────┘
                                   │
       ┌────────────────────────────────────────────────────────┐
       │ Layer 3: System Control & Automation (Runners, Boot)   │  --> platform_eng/ (High-level)
       └────────────────────────────────────────────────────────┘
                                   │
       ┌────────────────────────────────────────────────────────┐
       │ Layer 2: Power Telemetry & Peripherals (PMBus, NFC)    │  --> power_telemetry/, peripheral_nfc/
       └────────────────────────────────────────────────────────┘
                                   │
       ┌────────────────────────────────────────────────────────┐
       │ Layer 1: Hardware Interface Bus (I2C, SPI, GPIO, FPGA) │  --> platform_eng/ (Low-level)
       └────────────────────────────────────────────────────────┘

## 📂 Repository Structure & Components

### 1. `rack_provisioning/` — Layer 4: Rack Orchestration & OS Deployment
Handles automated hardware discovery, bare-metal environment setups, and multi-node coordination.
*   **`dhcptool.py`**: Manages network lease mapping, device identification, and tracking hooks.
*   **`pxe_env_setup.py` & `setup_pxe_server.sh`**: Automated configuration tools to spin up local deployment environments.
*   **`install_os.sh`**: Unattended operating system installation scripts.
*   **`multitool.py`**: Parallel execution engines designed to run diagnostics or commands across multiple remote rack units simultaneously.

### 2. `platform_eng/` — Layer 3 & Layer 1: Platform Engineering & Bus Control
A dual-purpose directory combining abstract software runners with microscopic hardware hooks tailored for platform execution and diagnostics.
*   **System Automation (Layer 3)**: `runner.py`, `fboss.py`, `bootstrap.py` (Manages system environment setup and verification execution).
*   **Bus Debugging (Layer 1)**: `i2cbus.py`, `spibus.py`, `spi-utils.py` (Direct bit-banging and data bus read/writes).
*   **Hardware Lines (Layer 1)**: `gpio.py`, `pci_config.py`, `xadc.py` (Reads analog-to-digital converters, general-purpose pins, and PCI registers).
*   **Peripherals (Layer 1)**: `leds.py`, `sensors.py`, `hwmon.py`, `xcvr.py` (Hardware monitoring, optical transceiver interaction, and chassis indicators).

### 3. `power_telemetry/` — Layer 2: Power Management & Voltage Regulation
Focuses on telemetry data and active profiling for high-density power distribution units and regulators.
*   **`pmbus_tool.py`**: Core utility to interface with power management buses.
*   **`tps25990_energy.py`**: Specific energy monitoring and profiling module.
*   **`xdpe_mic_programmer.py`**: Memory flash/programming tool for on-board voltage regulators.

### 4. `peripheral_nfc/` — Layer 2: Near Field Communication
*   **`nfc_tool.py`**: Implements host controller interface (NCI) interactions for hardware variants equipped with NFC physical assets.

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.8+** or higher.
- **Linux environment** with direct hardware bus access (`/dev/i2c-*`, `/dev/spidev*`) for low-level layers.
- **Root or sudo privileges** for network automation hooks (`rack_provisioning`).

### Installation
Clone the repository and jump into your target layer:

```bash
git clone https://github.com/clslucas/StrataKit.git
cd StrataKit
```

### Example 1: Setting up the PXE Server Environment
To initialize a provisioning base station on your rack controller:

```bash
cd rack_provisioning
sudo ./setup_pxe_server.sh
python3 pxe_env_setup.py
```

### Example 2: Inspecting Low-Level Sensors
To run local telemetry collection using the platform engineering utilities:

```bash
cd platform_eng
python3 sensors.py --summary
```

## 📖 Documentation
Detailed guides, deployment readmes, and step-by-step operating system configurations are available inside the `/docs` directory:
- **CentOS Stream 9 PXE Automated Installation**
- **Comprehensive PXE Boot Guide**
- **DHCP Tool Specification**

## 🤝 Contributing
Contributions across all strata of the project are welcome. Please ensure that modifications to low-level drivers (I2C, SPI) include appropriate register-level fallback testing to prevent bricking live equipment.

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.