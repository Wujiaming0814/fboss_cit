"""Module providing spi master and spidev test."""

# spi master, spidev and spi udev test
import os
import pathlib
import re
from ast import literal_eval
from fboss_utils import execute_shell_cmd

DEVMAP_SPI = "/run/devmap/flashes/"
SPI_VENDOR_PATTERN = re.compile(r"vendor=\"([\w\d]+)\"\sname=\"([\w\d.]+)\"")

FMTOUT = "\u001b[31m{}\u001b[0m"


def generate_spidev():
    """Generate spidev devices"""
    for busid in range(8):
        drv_path = f"/sys/bus/spi/devices/spi{busid}.0/driver_override"
        dev_path = f"/dev/spidev{busid}.0"
        bind_path = "/sys/bus/spi/drivers/spidev/bind"
        if not pathlib.Path(drv_path).exists() or not pathlib.Path(bind_path).exists():
            break
        if not pathlib.Path(dev_path).exists():
            with open(drv_path, "w", encoding="utf-8") as fd:
                fd.write("spidev")
            with open(bind_path, "w", encoding="utf-8") as fd:
                fd.write(f"spi{busid}.0")


class SPIBUS:
    """spi master and spidev class"""

    def __init__(self, spi_info, fpga_path):
        self._fpga_path = fpga_path
        self.spi_dict = spi_info
        generate_spidev()

    def _get_spidev_from_udev(self, spidev_name):
        """get spidev info"""
        stat = True
        spidev = "NA"
        dev_name = f"{DEVMAP_SPI}{spidev_name}"
        if pathlib.Path(dev_name).exists():
            chardev = os.readlink(dev_name)
            if pathlib.Path(chardev).exists():
                spidev_info = os.path.basename(chardev)
                spidev = spidev_info
            else:
                stat = False
        else:
            stat = False
        return stat, spidev

    def _detect_gpio(self):
        """detect gpio info"""
        stat, stdout = execute_shell_cmd("gpiodetect")
        if stat:
            gpioid = stdout.strip().split(" ")

        return gpioid[0]

    def parse_spidev_udev(self, busid):
        """parse spidev info"""
        spidev_info = ""
        spidev_udev = ""
        udev_flag = False
        # get spi flash device udev
        if not pathlib.Path(DEVMAP_SPI).exists():
            errcode, spidev_udev = False, "NA"
            spidev_info = FMTOUT.format("FAIL - No udev file.")
        else:
            spi_udev = os.listdir(DEVMAP_SPI)
            for value in self.spi_dict.values():
                errcode = True
                if busid == value["bus"]:
                    udev_flag = True
                    spidev_udev = value["udev"]
                    if spidev_udev in spi_udev:
                        sta, spidev_dev = self._get_spidev_from_udev(spidev_udev)
                        if not sta:
                            errcode = False
                            spidev_info = FMTOUT.format("FAIL - udev Invalid.")
                        else:
                            spidev_info = re.findall(r"\d+?d*", spidev_dev)[0]
                    else:
                        errcode = False
                        spidev_info = FMTOUT.format(f"FAIL - match error {spi_udev}.")
                else:
                    continue

            if not udev_flag:
                errcode, spidev_udev = True, "NA"
                spidev_info = busid

        return errcode, spidev_info, spidev_udev

    def spi_master_detect(self) -> bool:
        """detect spi master info"""
        for busid in range(8):
            errcode, status = True, "PASS"
            dev_path = f"/sys/bus/spi/devices/spi{busid}.0"
            master_path = f"{self._fpga_path}fbiob_pci.spi_master.{busid}"

            if pathlib.Path(dev_path).exists() and pathlib.Path(master_path).exists():
                cmd_str = f"basename {dev_path}"
                sta, res = execute_shell_cmd(cmd_str)
                if sta:
                    spibus = res.split()[0]
                    masterid = re.findall(r"\d+?d*", spibus)[0]
                    spidev_info = f"spidev{masterid}.0"
                else:
                    errcode = False
                    spidev_info = "NA"
                    status = FMTOUT.format("FAIL - SPI Bus devive Error.")

                sta, spidevid, spidev_udev = self.parse_spidev_udev(busid)
                if not sta:
                    if spidevid != str(busid):
                        errcode = False
                else:
                    if int(spidevid) != int(masterid):
                        errcode = False
                        status = FMTOUT.format(
                            f"FAIL - UDEV map Error.[spi.{spidevid}]"
                        )
            else:
                spibus = spidev_info = spidev_udev = "NA"
                errcode = False
                status = FMTOUT.format("FAIL - SPI Master or Driver Error.")

            print(
                f'{busid:>7d}  {spibus:>12}{"":5}{spidev_info:>10} '
                + f'{spidev_udev:>15s}{"":7}{status:<7s}  \n',
                end="",
            )
        return errcode, status

    def spi_scan(self, dev: str) -> bool:
        """detect spi flash chip info"""
        dev_info = self.spi_dict.get(dev)
        res = True
        vendor, name, size = "NA", "NA", "NA"
        gpiopin = self.spi_dict[dev]["gpiopin"]

        gpiochip = self._detect_gpio()
        while True:
            if dev_info is None:
                res = False
                break

            if gpiopin:
                for pinid in gpiopin:
                    cmd = f"gpioset {gpiochip} {pinid}=1"
                    stat, stdout = execute_shell_cmd(cmd)
                    if not stat:
                        res = False
                        break

            spidev = f'/dev/spidev{self.spi_dict[dev]["bus"]}.0'
            if not os.path.exists(spidev):
                res = False
                break

            if dev == "iob":
                cmd = (
                    f"flashrom -p linux_spi:dev={spidev} -c"
                    + f' {self.spi_dict[dev]["chip"]} --flash-name'
                )
                stat, stdout = execute_shell_cmd(cmd)

            cmd = (
                f"flashrom -p linux_spi:dev={spidev} -c"
                + f' {self.spi_dict[dev]["chip"]} --flash-name'
            )
            stat, stdout = execute_shell_cmd(cmd)
            if not stat:
                res = False
            else:
                try:
                    vendor, name = SPI_VENDOR_PATTERN.findall(stdout.splitlines()[-1])[
                        0
                    ]
                except ValueError:
                    res = False
                    break
                cmd = (
                    f"flashrom -p linux_spi:dev={spidev} -c"
                    + f' {self.spi_dict[dev]["chip"]} --flash-size'
                )
                stat, stdout = execute_shell_cmd(cmd)
                if not stat:
                    res, size = False, "NA"
                else:
                    size = f"{literal_eval(stdout.splitlines()[-1])//1024} KB"

            if gpiopin:
                for pinid in gpiopin:
                    cmd = f"gpioget {gpiochip} {pinid}"
                    stat, stdout = execute_shell_cmd(cmd)
                    if not stat:
                        res = False
                        break

            break

        mux = self.spi_dict[dev]["gpiopin"]
        print(
            f'{dev.upper():>7s} Flash   {self.spi_dict[dev]["bus"]:>3d}   '
            + f'{"".join(map(str, mux)) if mux else "NA":>6}{"":7}{vendor.ljust(7)}  '
            + f" {name.ljust(10)}{size:>9} ",
            end="",
        )

        return res
