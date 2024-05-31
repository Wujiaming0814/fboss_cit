#! /usr/bin/env python
""" test port leds /sys/class/leds
    file
"""
import time
import os
from fboss_utils import *

LEDS_CLASS = "/sys/class/leds/"
INPUT_MSG = "Light led mode: [A]Automated or [M]Manual running leds"

LED_ON = 1
LED_OFF = 0

TABLE_FLAG = "-----+-----+-----+-----+"

def test_led_udev_path():
    """check port led udev"""
    stat = True
    rtn_msg = "PASS"
    if not os.path.exists(LEDS_CLASS) or    \
            not os.listdir(LEDS_CLASS):
        stat = False
        rtn_msg = "\033[31mFAIL\033[0m\t, LED driver error."
    if not os.path.exists(LEDS_CLASS):
        stat = False
        rtn_msg = "\033[31mFAIL\033[0m\t, UDEV path error."
    if not os.listdir(LEDS_CLASS):
        stat = False
        rtn_msg = "\033[31mFAIL\033[0m\t, leds udev mapping error."
    return stat, rtn_msg

def get_port_led_status(leds_path, portid, ledidx):
    """get port led status"""
    #port10_led1:yellow:status
    for color in ["yellow", "blue", "green"]:
        led_status = f"port{portid}_led{ledidx}:{color}:status/brightness"
        devfile = f'{leds_path}{led_status}'
        color_val = read_sysfile_value(devfile)
        if not color_val:
            return None

        if int(color_val):
            return color

    return "off"

def save_led_default_status(ports) -> dict:
    """save port led status"""
    port_info_dict = {}
    for num in range(ports):
        port = num +1
        for ledidx in range(1,3):
            port_info = f'{port}_{ledidx}'
            color = get_port_led_status(LEDS_CLASS, port, ledidx)
            port_info_dict.update({port_info:color})

    return port_info_dict

def port_led_on(portid, ledidx, color):
    """light on port led"""
    status = "PASS"
    led_status = f"port{portid}_led{ledidx}:{color}:status/brightness"
    devfile = f'{LEDS_CLASS}{led_status}'
    stat = write_sysfile_value(devfile, LED_ON)
    if not stat:
        status = "\033[31mFAIL\033[0m\tcontrol led command error"
    return status

def port_led_off(portid, ledidx):
    """light off port led"""
    status = "PASS"
    color = get_port_led_status(LEDS_CLASS, portid, ledidx)
    led_status = f"port{portid}_led{ledidx}:{color}:status/brightness"
    devfile = f'{LEDS_CLASS}{led_status}'
    stat = write_sysfile_value(devfile, LED_OFF)
    if not stat:
        status = "\033[31mFAIL\033[0m\tcontrol led command error"
    return status

def restore_leds_default_status(leds_status:dict):
    """save port led status"""
    for items in leds_status.items():
        if items[1] == "off":
            port_led_off(int(items[0].split('_')[0]), items[0].split('_')[1])
        else:
            port_led_on(int(items[0].split('_')[0]), items[0].split('_')[1], items[1])

def turn_off_ports_led(port_nums):
    """turn off all ports led"""
    status = "PASS"
    for i in range(port_nums):
        portid = i + 1
        for ledidx in range(1, 3):
            status = port_led_off(portid, ledidx)

    if status == "PASS":
        print("\nled:turn off all port leds.\n")

    return status

def turn_on_ports_left_led(port_nums, color):
    status = "PASS"
    for i in range(port_nums):
        portid = i + 1
        status = port_led_on(portid, 1, color)
    return status

def turn_on_ports_right_led(port_nums, color):
    status = "PASS"
    for i in range(port_nums):
        portid = i + 1
        status = port_led_on(portid, 2, color)
    return status

def loop_port_leds(portid):
    """loop light on ports led"""
    status = "PASS"
    for ledidx in range(1, 3):
        for color in ["yellow", "blue", "green"]:
            stat = port_led_on(portid, ledidx, color)
            if not stat:
                status = "\033[31mFAIL\033[0m\tcontrol led command error"
            time.sleep(0.2) #switch color delay 0.2 seconds
            print(f'led:turn on port_{portid} index_{ledidx} {color}\r\n' ,end='')
    return status

def port_led_status(pnum, portid, status:list):
    line_info = ""
    for i in range(pnum):
        _left = status[portid + 6 * i]
        _right = status[portid + 1 + 6 * i]
        left_flag = f'{"x" if _left == "off" else _left}'
        right_flag = f'{"x" if _right == "off" else _right}'
        line_info += f" {left_flag.upper()[0]} {right_flag.upper()[0]} |"
    return line_info

def janga_port_led_status(status:list):
    port_left = f'{"x" if status[0] == "off" else status[0]}'
    port_right = f'{"x" if status[1] == "off" else status[1]}'
    first_line = f'| {port_left.upper()[0]} {port_right.upper()[0]} |'
    port_left = f'{"x" if status[2] == "off" else status[2]}'
    port_right = f'{"x" if status[3] == "off" else status[3]}'
    second_line = f"| {port_left.upper()[0]} {port_right.upper()[0]} |"
    third_line = "|     |     |"
    first_line += port_led_status(15, 6, status)
    second_line += port_led_status(15, 4, status)
    third_line += port_led_status(14, 8, status)

    return first_line, second_line, third_line

def tahan_port_led_status(status:list):
    first_line = "|"
    second_line = "|"
    third_line = "|     |"
    first_line += port_led_status(11, 2, status)
    second_line += port_led_status(11, 0, status)
    third_line += port_led_status(11, 4, status)

    return first_line, second_line, third_line

def janga_port_led_status_test(port_count):
    """janga blade ports led status test"""
    current_color_dict = {}
    #show ports led status
    current_color_dict = save_led_default_status(port_count)
    if not bool(current_color_dict):
        return False, "FAIL"
    color_info = list(current_color_dict.values())
    first_line, second_line, third_line = janga_port_led_status(color_info)
    print("+" + TABLE_FLAG * 4)
    print(first_line)
    print("+" + TABLE_FLAG * 4)
    print(second_line)
    print("+" + TABLE_FLAG * 4)
    print(third_line)
    print("+" + TABLE_FLAG * 4)

    return True, "PASS"

def tahan_port_led_status_test(port_count):
    """tahan blade ports led status test"""
    current_color_dict = {}
    #show ports led status
    current_color_dict = save_led_default_status(port_count)
    #print(current_color_dict)
    if not bool(current_color_dict):
        return False, "FAIL"
    color_info = list(current_color_dict.values())
    first_line, second_line, third_line = tahan_port_led_status(color_info)
    print("+" + TABLE_FLAG * 3)
    print(first_line)
    print("+" + TABLE_FLAG * 3)
    print(second_line)
    print("+" + TABLE_FLAG * 3)
    print(third_line)
    print("+" + TABLE_FLAG * 3)

    return True, "PASS"

def montblanc_port_led_status_test(port_count):
    """janga blade ports led status test"""
    current_color_dict = {}
    #show ports led status
    current_color_dict = save_led_default_status(port_count)
    if not bool(current_color_dict):
        return False, "FAIL"
    color_info = list(current_color_dict.values())
    for n in range(4):
        line_info = ""
        print(("+" + TABLE_FLAG * 2) * 2)
        for i in range(16):
            _left = color_info[2 * n + 8 * i]
            _right = color_info[2 * n + 1 + 8 * i]
            left_flag = f'{"x" if _left == "off" else _left}'
            right_flag = f'{"x" if _right == "off" else _right}'
            line_info += f" {left_flag.upper()[0]} {right_flag.upper()[0]} |"
            if i == 7:
                line_info += "|"
        leds_status = "".join(line_info)
        print("|" + leds_status)
    print(("+" + TABLE_FLAG * 2) * 2)

    return True, "PASS"

def port_led_turn_on_off(port_nums, platform = "janga"):
    status = "PASS"
    # turn off all ports
    status = turn_off_ports_led(port_nums)
    # turn on port led one by one
    for num in range(1, port_nums + 1):
        loop_port_leds(num)

    status = turn_off_ports_led(port_nums)

    return status

def ports_led_light_status_test(port_nums, platform = "tahan"):
    stat = True
    status = "PASS"
    default_color_dict = {}
    stat, status = test_led_udev_path()
    if not stat:
        return stat, status

    func_name = f'{platform}_port_led_status_test'
    #save port led default color
    default_color_dict = save_led_default_status(port_nums)
    if not bool(default_color_dict):
        return False, "FAIL"
    # show ports led default status
    print('-------------------------------------------------------------------------\n'
            '                   |    Ports Led Default status    |')
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status
    time.sleep(0.5) #wait 0.5 seconds check leds status
    status = turn_off_ports_led(port_nums)
    print('-------------------------------------------------------------------------\n'
            '                  |    Turn off all ports Led Test    |')
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status
    time.sleep(0.5) #wait 0.5 seconds check leds status
    # turn on left side leds color green
    tatus = turn_on_ports_left_led(port_nums, "green")
    print('-------------------------------------------------------------------------\n'
            '               |    Turn on left ports Led green Test    |')
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status
    time.sleep(0.5) #wait 0.5 seconds check leds status
    status = turn_off_ports_led(port_nums)
    status = turn_on_ports_right_led(port_nums, "blue")
    print('-------------------------------------------------------------------------\n'
            '               |    Turn on right ports Led blue Test    |')
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status
    time.sleep(0.5) #wait 0.5 seconds check leds status

    # restore port led status
    restore_leds_default_status(default_color_dict)

    return stat, status

if __name__=="__main__":
    ports_led_light_status_test(33)
