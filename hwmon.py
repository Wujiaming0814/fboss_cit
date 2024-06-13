import os

from fboss_utils import print_dict

class Hwmon():

    def __init__(self):
        self.master_path = '/sys/class/hwmon'
        self.attributes_list = ["_max", "_min", "_crit", "_lcrit"]

    def value_format(self, attributes_file, value):

         # See https://www.kernel.org/doc/Documentation/hwmon/sysfs-interface
        if attributes_file.lower().startswith('in'):
            return str(int(value) / 1000) + ' V'
        elif attributes_file.lower().startswith('fan'):
            return value + ' RPM'
        elif attributes_file.lower().startswith('pwm'):
            return str(int(value) / 255) + ' PWM (%)'
        elif attributes_file.lower().startswith('temp'):
            return str(int(value) / 1000) + ' C'
        elif attributes_file.lower().startswith('curr'):
            return str(int(value) / 1000) + ' A'
        elif attributes_file.lower().startswith('power'):
            return str(int(value) / 1000000) + ' W'
        elif attributes_file.lower().startswith('freq'):
            return str(int(value) / 1000000) + ' MHz'

    def read_data(self, data_path):
        file = open(data_path, 'r')
        data = file.read().strip()
        file.close()
        return data

    def extract_data(self, sub_folder_path, file_):

        # initial hwmon data list
        hwmon_data = []
        data = dict()
        # split file header
        file_key = file_.split('_')[0]

        # read in/fan/temp/curr/power/energy/humidity[0-*]_input data
        if os.path.exists(os.path.join(sub_folder_path, file_key + '_label')):

            label_name = file_key + '_label'

            label_name = self.read_data(os.path.join(sub_folder_path, label_name))
            # only read input data, not to read the "*_input_highest" and "*_input_lowest"
            if '_input_' not in file_:
                value = self.read_data(os.path.join(sub_folder_path, file_))

        else:

            label_name = file_key
            value = self.read_data(os.path.join(sub_folder_path, file_))

        data[label_name] = self.value_format(file_, value)
        hwmon_data.append(data)

        for file in self.attributes_list:
            file_id = file_key + file
            file_name = label_name + file
            if os.path.exists(os.path.join(sub_folder_path, file_id)):
                value = self.read_data(os.path.join(sub_folder_path, file_id))
                data[file_name] = self.value_format(file_id, value)
                hwmon_data.append(data)

        return hwmon_data
    
    def data(self):

        data = dict()

        folders = os.listdir(self.master_path)

        for folder in folders:

            name_key = None

            sub_folder_path = os.path.join(self.master_path, folder)

            files = os.listdir(sub_folder_path)

            if os.path.exists(os.path.join(sub_folder_path, 'name')):
                name_key = self.read_data(os.path.join(sub_folder_path, 'name'))

            symlink = os.readlink(os.path.join(sub_folder_path, 'device'))
            symlink = symlink.strip().split("/")[-1]
            sensor_name = f"{name_key}-{symlink}"

            data[sensor_name] = dict()

            for file_ in files:

                try:

                    if '_input' in file_:
                        hwmon_data = self.extract_data(sub_folder_path, file_)
                        for label_name in hwmon_data:
                            data[sensor_name].update(label_name)

                    if '_average' in file_:
                        hwmon_data = self.extract_data(sub_folder_path, file_)
                        for label_name in hwmon_data:
                            data[sensor_name].update(label_name)

                except Exception:
                    pass

            estimate_w = []

            for sensor in data.keys():

                for value in data[sensor].keys():

                    if data[sensor][value].endswith("v"):

                        try:
                            v = float(data[sensor][value].split(" ")[0])
                            i = float(data[sensor]["I" + value[1:]].split(" ")[0])
                            estimate_w.append([sensor, "W" + value[1:] + "*", round(v*i,4)])
                        except Exception:
                            pass

            for value in estimate_w:
                data[value[0]][value[1]] = str(value[2]) + " w"

        return data

    def print_data(self, colors=True):
        print_dict(self.data(), indent=0, colors=colors)
    
    def print_data_format(self):
        TABLE_FLAG = "-----+-----+-----+-----+"
        print("+" + TABLE_FLAG * 4)
        print("|")
        print("+" + TABLE_FLAG * 4)