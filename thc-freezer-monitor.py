
import time
import random
import sys
import paho.mqtt.client as mqtt
import ssl
import glob
import os
import threading
import fourletterphat as flp
import inspect
from datetime import datetime

#default W1 pin is BCM4 (GPIO4). Can add more w1-overlay's.
conn_flag = False
TEMP_INTERVAL_CHECK = 1 
TEMP_INTERVAL_PUBLISH  = 10
TEMP_BAD = -100.0
BASE_DIR = '/sys/bus/w1/devices/'


def lineno():
    return inspect.currentframe().f_back.f_lineno

class FourLetterTemperature:
    def __init__(self):
        self.temp_f = 0.0
        self.temp_a = 0.0
        self.n = int(time.time())
        flp.clear()
        flp.set_brightness(4)
        self.update_called = False
        self.display_id = object()

    def __display_f(self):
        if self.display_id != self.__display_f:
            flp.set_blink(flp.HT16K33_BLINK_OFF)
            self.display_id = self.__display_f
            #flp.scroll_print("FREEZER")
            flp.print_str("FRZR")
            flp.show()
            time.sleep(2)

        flp.print_float(self.temp_f, decimal_digits=1)
        flp.show()
        flp.glow()

    def __display_a(self):
        if self.display_id != self.__display_a:
            self.display_id = self.__display_a
            flp.print_str("LOGC")
            flp.show()
            time.sleep(2)

        flp.print_float(self.temp_a, decimal_digits=1)
        flp.set_blink(flp.HT16K33_BLINK_2HZ)
        flp.show()

    def display(self, value):
        flp.print_str(value)
        flp.show()
        time.sleep(5)

    def loop_forever(self):
        while not self.update_called:
            time.sleep(0.1)

        while True:
            # Display freezer for 20 sec and ambient for 10 sec
            nn = self.n % 30
            if nn in range(0, 20):
                self.__display_f()
            if nn in range(20, 30):
                self.__display_a()

            self.n = int(time.time())
            time.sleep(1)

    def update(self, temp_f, temp_a):
        self.update_called = True
        self.temp_f = temp_f
        self.temp_a = temp_a

def on_log(client, userdata, level, buf):
    print("log: ", buf)

def on_connect(client, userdata, flags, rc):
    global conn_flag
    if rc!=0:
        print("Connect() FAILED: " + str(rc))
        return
    if conn_flag:
        print("DUP Connected: " + str(rc))
        return
    conn_flag = True
    print("Connected " + str(rc))
    if ts_sub_enabled:
        client.subscribe(ts_sub, 0)

def on_disconnect(client, userdata, rc):
    global conn_flag
    conn_flag = False
    # rc == 0 is disonnect by call to disconnect(). Otherwise due to
    # network error.
    print("Disconnected " + str(rc))

def on_message(client, userdata, msg):
    print("ON MESSAGE")
    print(msg.topic + " " + str(msg.payload))
    flt.display("OWND")

def read_temp_raw(dev_file):
    lines = ('Blah', 'Blub')
    try:
        f = open(dev_file, 'r')
    except OSError:
        print("ERROR open(" + dev_file + ")")
        return lines
    lines = f.readlines()
    f.close()
    return lines

# example:
#88 01 4b 46 7f ff 08 10 76 : crc=76 YES
#88 01 4b 46 7f ff 08 10 76 t=24500
def read_temp_to_float(device_file):
    temp = TEMP_BAD
    lines = read_temp_raw(device_file)
    while lines[0].strip()[-3:] != 'YES':
        return temp
    equals_pos = lines[1].find('t=')
    if equals_pos == -1:
        return temp
    temp_string = lines[1][equals_pos+2:]
    # If the sensor fails it returns a straight t=0
    temp_val = float(temp_string) / 1000.0
    if temp_val == 0:
        return temp

    temp = temp_val

    return temp

def read_temp():
    temp_amb = read_temp_to_float(device_file_amb)
    temp_fre = read_temp_to_float(device_file_fre)

    return temp_amb, temp_fre

ts_username = 'user'
ts_mqtt_key = 'XXXXXXXXXXXXXXXX'
ts_channelID = '10XXXXX'
ts_key = 'XXXXXXXXXXXXXXXX'
ts_topic = "channels/"+ ts_channelID +"/publish/" + ts_key

ts_sub_enabled = False
#ts_sub_enabled = True
if ts_sub_enabled:
    ts_key_sub = 'XXXXXXXXXXXXXXXX'
    ts_chnlsubID = '105XXXXX'
    ts_sub   = "channels/"+ ts_chnlsubID +"/subscribe/fields/field1/" + ts_key_sub


# Check if two temperature sensors exist
# example:
# /sys/bus/w1/devices/28-00000a74ce75/w1_slave
try:
    device_folder_fre = glob.glob(BASE_DIR + '28*')[1]
    device_folder_amb = glob.glob(BASE_DIR + '28*')[0]
except IndexError:
    print("No temperature device found: " + BASE_DIR + '28*')
    exit(-1)
device_file_amb = device_folder_amb + '/w1_slave'
device_file_fre = device_folder_fre + '/w1_slave'

# Thread to update Four Letter pHat with Temperature readings
flt = FourLetterTemperature()
flt_thread = threading.Thread(target=flt.loop_forever, daemon=True)
flt_thread.start()

# Setup MQTT
client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
#client.on_log = on_log

client.tls_set()
client.username_pw_set(ts_username, ts_mqtt_key)
#client.tls_insecure_set(True)

# ThingSpeak does not support LWT yet:
#client.will_set(ts_topic, "field1=-5", 1, False);

client.connect("mqtt.thingspeak.com", 8883, 60)

temp_last_check = 0
temp_last_publish = 0
temp = ("", "")

# loop_start creates a thread to handle all network traffic.
client.loop_start()
while True:

    # Read the Temperature every 60 seconds and submit to TS
    time_current = time.time()
    if time_current > temp_last_check + TEMP_INTERVAL_CHECK:
        temp_last_check = time_current
        temp = read_temp()
        if temp[0] == TEMP_BAD:
            continue
        if temp[1] == TEMP_BAD:
            continue
        flt.update(temp[0], temp[1])
        temp_f_str = "{:.1f}".format(temp[0])
        temp_a_str = "{:.1f}".format(temp[1])
        print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Freezer: "+ temp_f_str +", Ambient: " + temp_a_str)
        # Show on display if motion is detected...

    if not conn_flag:
        time.sleep(0.1)
        continue

    if time_current > temp_last_publish + TEMP_INTERVAL_PUBLISH:
        temp_last_publish = time_current
        if temp[0] != TEMP_BAD and temp[1] != TEMP_BAD:
            #print("field1=" + temp_f_str +"&field2=" + temp_a_str)
            client.publish(ts_topic, "field1=" + temp_f_str+ "&field2=" + temp_a_str)


exit(0)

