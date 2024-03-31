#!/usr/bin/env python3
"""
Main module for Growatt / Inverters ModBus RTU data to MQTT
"""


import sys
import time

# Check if Python version is greater than 3.9
if sys.version_info < (3, 9):
    print("==================================================")
    print("WARNING: python version 3.9 or higher is recommended")
    print("Current version: " + sys.version)
    print("Please upgrade your python version to 3.9")
    print("==================================================")
    time.sleep(4)


import argparse

import atexit
import glob
import random
import re

import os
import json
import logging
import sys
import traceback
from configparser import RawConfigParser
import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes

import importlib

from protocol_settings import protocol_settings,Data_Type,registry_map_entry,Registry_Type,WriteMode
from readers.reader_base import reader_base
from pymodbus.exceptions import ModbusIOException



__logo = """
   ____                        _   _   ____  __  __  ___ _____ _____ 
  / ___|_ __ _____      ____ _| |_| |_|___ \|  \/  |/ _ \_   _|_   _|
 | |  _| '__/ _ \ \ /\ / / _` | __| __| __) | |\/| | | | || |   | |  
 | |_| | | | (_) \ V  V / (_| | |_| |_ / __/| |  | | |_| || |   | |  
  \____|_|  \___/ \_/\_/ \__,_|\__|\__|_____|_|  |_|\__\_\|_|   |_|  
                                                                      
    """


class InverterModBusToMQTT:
    """
    Main class, implementing the Growatt / Inverters to MQTT functionality
    """
    # Global variables, defined private, all variables will be configured via cfg file
    # settings --> from config file
    __settings = None
    # interval in seconds for pulling modbus data [s]
    __interval = None
    # in case inverter is offline the script will sleep that defined time [s]
    __offline_interval = None
    # error interval in [s]
    __error_interval = None
    # device name of serial usb connection [/dev/tty...]
    __port = None
    # baudrate to access modbus connection
    __baudrate = -1
    # mqtt server host address
    __mqtt_host = None
    # mqtt client handle
    __mqtt_client = None

    # mqtt port of mqtt broker
    __mqtt_port = -1
    # mqtt topic the inverter data will be published
    __mqtt_topic = ""
    
    __mqtt_discovery_topic : str = "homeassistant"

    __mqtt_discovery_enabled : bool = True

    __mqtt_json : bool = False

    __mqtt_reconnect_delay : int = 7

    __mqtt_reconnect_attempts : int = 21
    ''' max number of reconnects during a disconnect '''

    __mqtt_reconnecting : float = 0
    ''' keep track of if reconnecting. so we can determine if mqtt event bugged out'''

    __mqtt_connected : bool = False
    ''' flag to keep track of if mqtt is connected because mqtt events / functions are unreliable '''

    # mqtt error topic in case the growatt2mqtt runs in error moder or inverter is powered off
    __mqtt_error_topic = ""
    # mqtt properties handle for publishing data
    __properties = None
    # logging module
    __log = None
    # log level, available log levels are CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG
    __log_level = 'DEBUG'

    __device_serial_number = "hotnoob"

    __max_precision : int = -1

    __write : bool = False
    ''' enable / disable write mode - setting'''

    __analyze_protocol : bool = False
    ''' enable / disable analyze mode'''

    __analyze_protocol_save_load : bool = False
    ''' if enabled, saves registry scan; but if found loads registry from file'''

    __send_holding_register : bool = False
    ''' send holding register over mqtt '''

    __send_input_register : bool = True
    ''' send input register over mqtt '''

    __holding_register_prefix : str = ""
    __input_register_prefix : str = ""

    __running : bool = False
    ''' controls main loop'''



    
    measurement : str
    config_file : str


    protocolSettings : protocol_settings

    modbus_delay : float = 0.85
    '''time inbetween requests'''

    modbus_version = ""
    reader : reader_base
    reader_settings : dict[str, str]
    

    def __init__(self, config_file : str):
        self.__log = logging.getLogger('invertermodbustomqqt_log')
        handler = logging.StreamHandler(sys.stdout)
        self.__log.setLevel(logging.DEBUG)
        formatter = logging.Formatter('[%(asctime)s]  {%(filename)s:%(lineno)d}  %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.__log.addHandler(handler)

        self.config_file = os.path.dirname(os.path.realpath(__file__)) + '/growatt2mqtt.cfg'
        newcfg = os.path.dirname(os.path.realpath(__file__)) + '/'+ config_file
        if os.path.isfile(newcfg):
            self.config_file = newcfg

        #logging.basicConfig()
        #pymodbus_log = logging.getLogger('pymodbus')
        #pymodbus_log.setLevel(logging.DEBUG)
        #pymodbus_log.addHandler(handler)

        return None

    def init_invertermodbustomqtt(self):
        """
        initialize -- needs to be cleaned up big time
        """
        self.__log.info("Initialize Inverter ModBus To MQTT Server")
        self.__settings = RawConfigParser()

        self.__settings.read(self.config_file)

        ##[TIME]
        self.__interval = self.__settings.getint('time', 'interval', fallback=1)
        self.__offline_interval = self.__settings.getint('time', 'offline_interval', fallback=60)
        self.__error_interval = self.__settings.getint('time', 'error_interval', fallback=60)
        
        self.__log_level = self.__settings.get('general','log_level', fallback='DEBUG')
        self.__max_precision = self.__settings.getint('general','max_precision', fallback=-1)

        if (self.__log_level != 'DEBUG'):
            self.__log.setLevel(logging.getLevelName(self.__log_level))


        self.__log.info("start connection mqtt ...")
        self.__mqtt_host = self.__settings.get(
            'mqtt', 'host', fallback='mqtt.eclipseprojects.io')
        
        self.__mqtt_port = self.__settings.get('mqtt', 'port', fallback=1883)
        self.__mqtt_topic = self.__settings.get('mqtt', 'topic', fallback='home/inverter')
        self.__mqtt_discovery_topic = self.__settings.get('mqtt', 'discovery_topic', fallback='homeassistant')
        self.__mqtt_discovery_enabled = strtobool(self.__settings.get('mqtt', 'discovery_enabled', fallback="true"))
        self.__mqtt_json = strtobool(self.__settings.get('mqtt', 'json', fallback="false"))
        self.__mqtt_reconnect_delay = self.__settings.getint('mqtt', 'reconnect_delay', fallback=7)
        if not isinstance( self.__mqtt_reconnect_delay , int) or self.__mqtt_reconnect_delay < 1: #minumum 1 second
            self.__mqtt_reconnect_delay = 1

        self.__mqtt_reconnect_attempts = self.__settings.getint('mqtt', 'reconnect_attempts', fallback=21)
        if not isinstance( self.__mqtt_reconnect_attempts , int) or self.__mqtt_reconnect_attempts < 0: #minimum 0
            self.__mqtt_reconnect_attempts = 0

        self.__holding_register_prefix = self.__settings.get("mqtt", "holding_register_prefix", fallback="")
        self.__input_register_prefix = self.__settings.get("mqtt", "input_register_prefix", fallback="")

        # inverter / device
        #this is kinda dumb, overcomplicates things, let's stick to 1 inverter at a time, can always run multiple instances of script
        #keep this loop for backwards compatability
        for section in self.__settings.sections():
            if not section.startswith('inverter') and not section.startswith('device'):
                continue

            self.name = self.__settings.get(section, 'name', fallback="NO NAME")
            self.unit = int(self.__settings.get(section, 'unit'))
            self.protocol_version = str(self.__settings.get(section, 'protocol_version'))

            self.__analyze_protocol = self.__settings.getboolean(section, 'analyze_protocol', fallback=False)
            self.__write = self.__settings.getboolean(section, 'write', fallback=False)
            self.__analyze_protocol_save_load = self.__settings.getboolean(section, 'analyze_protocol_save_load', fallback=False)

           
            self.measurement = self.__settings.get(section, 'measurement', fallback="")

            reader_section = 'serial'
            if self.__settings.has_section('reader'):
                reader_section = 'reader'
                
            self.reader_settings : dict[str, object] = {} 
            self.reader_settings["reader"] = self.__settings.get(reader_section, 'reader', fallback='')
            self.reader_settings["port"] = self.__settings.get(reader_section, 'port', fallback='/dev/ttyUSB0')
            self.reader_settings["baudrate"] = self.__settings.getint(reader_section, 'baudrate', fallback=9600)
            self.reader_settings["certfile"] = self.__settings.get(reader_section, 'certfile', fallback='')
            self.reader_settings["keyfile"] = self.__settings.get(reader_section, 'keyfile', fallback='')
            self.reader_settings["host"] = self.__settings.get(reader_section, 'host', fallback='')
            self.reader_settings["hostname"] = self.__settings.get(reader_section, 'hostname', fallback='')

            #load protocol settings
            self.protocolSettings = protocol_settings(self.protocol_version)

            #default for send_holding_register
            fallback = False
            if "send_holding_register" in self.protocolSettings.settings:
                fallback = self.protocolSettings.settings["send_holding_register"]

            self.__send_holding_register = self.__settings.getboolean(section, 'send_holding_register', fallback=fallback)

            #default for send_input_register
            fallback = True
            if "send_input_register" in self.protocolSettings.settings:
                fallback = self.protocolSettings.settings["send_input_register"]

            self.__send_input_register = self.__settings.getboolean(section, 'send_input_register', fallback=fallback)


        print("max_precision: " + str(self.__max_precision))



        #override reader if set
        if self.reader_settings["reader"]:
            self.protocolSettings.reader = self.reader_settings["reader"]
        #load reader
        # Import the module
        module = importlib.import_module('readers.'+self.protocolSettings.reader)


        # Get the class from the module
        cls = getattr(module, self.protocolSettings.reader)

        self.reader : reader_base = cls(self.reader_settings)
        self.reader.connect()

        self.__mqtt_error_topic = self.__settings.get(
            'mqtt', 'error_topic', fallback='home/inverter/error')
        self.__log.info("mqtt settings: \n")
        self.__log.info("mqtt host %s\n", self.__mqtt_host)
        self.__log.info("mqtt port %s\n", self.__mqtt_port)
        self.__log.info("mqtt_topic %s\n", self.__mqtt_topic)

        #compatability with newer lib
        
        if hasattr(mqtt, "CallbackAPIVersion"):
            self.__mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        else:
            self.__mqtt_client = mqtt.Client()

        self.__mqtt_client.on_connect = self.on_connect
        self.__mqtt_client.on_message = self.on_message
        self.__mqtt_client.on_disconnect = self.on_disconnect
        

        ## Set username and password
        username = self.__settings.get('mqtt', 'user')
        password = self.__settings.get('mqtt', 'pass')
        if username:
            self.__mqtt_client.username_pw_set(username=username, password=password)

        self.__mqtt_client.connect(str(self.__mqtt_host), int(self.__mqtt_port), 60)
        self.__mqtt_client.loop_start()

        self.__properties = Properties(PacketTypes.PUBLISH)
        self.__properties.MessageExpiryInterval = 30  # in seconds

        atexit.register(self.exit_handler)

    def exit_handler(self):
        '''on exit handler'''
        print("Exiting")
        self.__mqtt_client.publish( self.__mqtt_topic + "/availability","offline")
        return


    def mqtt_reconnect(self):
        self.__log.info("Disconnected from MQTT Broker!")
        if self.__mqtt_reconnecting != 0: #stop double calls
            return
        # Attempt to reconnect
        for attempt in range(0, self.__mqtt_reconnect_attempts):
            self.__mqtt_reconnecting = time.time()
            try:
                self.__log.warning("Attempting to reconnect("+str(attempt)+")...")
                if random.randint(0,1): #alternate between methods because built in reconnect might be unreliable. 
                    self.__mqtt_client.reconnect()
                else:
                    self.__mqtt_client.loop_stop()
                    self.__mqtt_client.connect(str(self.__mqtt_host), int(self.__mqtt_port), 60)
                    self.__mqtt_client.loop_start()

                #sleep to give a chance to reconnect. 
                time.sleep(self.__mqtt_reconnect_delay)    
                if self.__mqtt_connected:
                    self.__mqtt_reconnecting = 0
                    return
            except:
                self.__log.warning("Reconnection failed. Retrying in "+str(self.__mqtt_reconnect_delay)+" second(s)...")
                time.sleep(self.__mqtt_reconnect_delay)
        
        #failed to reonnect
        self.__log.critical("Failed to Reconnect, Too many attempts")
        self.__running = False
        self.__mqtt_reconnecting = 0
        quit() #exit, service should restart entire script

    def on_disconnect(self, client, userdata, rc):
       self.mqtt_reconnect()

    def on_connect(self, client, userdata, flags, rc):
        """ The callback for when the client receives a CONNACK response from the server. """
        self.__log.info("Connected with result code %s\n",str(rc))
        self.__mqtt_connected = True


    __write_topics : dict[str, registry_map_entry] = {}

    def on_message(self, client, userdata, msg):
        """ The callback for when a PUBLISH message is received from the server. """
        self.__log.info(msg.topic+" "+str(msg.payload.decode('utf-8')))

        #self.protocolSettings.validate_registry_entry
        if msg.topic in self.__write_topics:
            entry = self.__write_topics[msg.topic]
            self.write_variable(entry, value=str(msg.payload.decode('utf-8')))


    def run(self):
        """
        run method, starts ModBus connection and mqtt connection
        """

        self.__running = True

        if self.__analyze_protocol:
            self.analyze_protocol()
            quit()


        self.__device_serial_number = self.__settings.get('mqtt_device', 'serial_number', fallback='')

        if not self.__device_serial_number: #if empty, fetch serial
            self.__device_serial_number = self.read_serial_number()
                    
        print("using serial number: " + self.__device_serial_number)

        if self.__write:
            self.enable_write()

        if self.__mqtt_discovery_enabled:
            self.mqtt_discovery()

        error_sleep = 0
        while self.__running:
            if not self.__mqtt_client.is_connected(): ##mqtt not connected. 
                if self.__mqtt_reconnecting == 0 or time.time() - self.__mqtt_reconnecting > 15*60:
                    self.mqtt_reconnect() #on disconnect event might have failed. manually reconnect

                print('MQTT is not connected')
                time.sleep(self.__mqtt_reconnect_delay)
                continue
            
            self.__mqtt_connected = True
            

            online = False
            # If this inverter errored then we wait a bit before trying again
            if error_sleep > 0:
                error_sleep -= self.__interval
                continue

            try:
                info = {}

                if self.__send_input_register:
                    new_info = self.read_input_registry()
                    if self.__input_register_prefix:
                        new_info = {self.__input_register_prefix + key: value for key, value in new_info.items()}

                    info.update(new_info)

                if self.__send_holding_register:
                    print("read holding registers")
                    new_info = self.read_holding_registry()

                    if self.__holding_register_prefix:
                        new_info = {self.__holding_register_prefix + key: value for key, value in new_info.items()}

                    info.update(new_info)

                if info is None:
                    self.__log.info("Register is None; modbus busy?")
                    continue

                # Mark that at least one inverter is online so we should continue collecting data
                online = True
                now = time.time()
                points = [{
                    'time': int(now),
                    'measurement': self.measurement,
                    "fields": info
                }]
                self.__log.info(points)

                #have to send this every loop, because mqtt doesnt disconnect when HA restarts. HA bug. 
                self.__mqtt_client.publish(self.__mqtt_topic + "/availability","online", qos=0,retain=True)

                if(self.__mqtt_json):
                    # Serializing json
                    json_object = json.dumps(points[0], indent=4)
                    self.__mqtt_client.publish(self.__mqtt_topic, json_object, 0, properties=self.__properties)
                else:
                    for key, val in info.items():
                        self.__mqtt_client.publish(str(self.__mqtt_topic+'/'+key).lower(), str(val))

                #if it makes it here, mqtt should be connected. 
                self.__mqtt_reconnect_attempts = 0
                self.__mqtt_reconnecting = 0

            except Exception as err:
                traceback.print_exc()
                self.__log.error(self.name)
                self.__log.error(err)
                json_object = '{"name":' + str(self.name)+',error_code:'+str(err)+'}'
                self.__mqtt_client.publish(self.__mqtt_error_topic, json_object, 0, properties=self.__properties)
                error_sleep = self.__error_interval

            if online:
                time.sleep(self.__interval)
            else:
                # If all the inverters are not online because no power is being generated then we sleep for 1 min
                time.sleep(self.__offline_interval)


    def enable_write(self):
        """
        enable write to modbus; must pass tests.
        """
        print("Validating Protocol for Writing")
        self.__write = False
        score_percent = self.validate_protocol(Registry_Type.HOLDING)
        if(score_percent > 90):
            self.__write = True
            print("enable write - validation passed")
            
            self.__write_topics = {}
            #subscribe to write topics
            for entry in self.protocolSettings.holding_registry_map:
                if entry.write_mode == WriteMode.WRITE:
                    #__write_topics
                    topic : str = self.__mqtt_topic + "/write/" + entry.variable_name.lower().replace(' ', '_')
                    self.__write_topics[topic] = entry
                    self.__mqtt_client.subscribe(topic)
    
    def validate_protocol(self, registry_type : Registry_Type = Registry_Type.INPUT) -> float:
        """
        validate protocol
        """

        score : float = 0
        info = {}
        registry_map : list[registry_map_entry] = self.protocolSettings.get_registry_map(registry_type)
        info = self.read_registry(registry_type)

        for value in registry_map:
            if value.variable_name in info:
                evaluate = True

                if value.concatenate and value.register != value.concatenate_registers[0]: #only eval concated values once
                    evaluate = False
                  
                if evaluate:
                    score = score + self.protocolSettings.validate_registry_entry(value, info[value.variable_name])

        maxScore = len(registry_map)
        percent = score*100/maxScore
        print("validation score: " + str(score) + " of " + str(maxScore) + " : " + str(round(percent)) + "%")
        return percent


    

    def analyze_protocol(self, settings_dir : str = 'protocols'):
        print("=== PROTOCOL ANALYZER ===")
        protocol_names : list[str] = []
        protocols : dict[str,protocol_settings] = {}

        for file in glob.glob(settings_dir + "/*.json"):
            file = file.lower().replace(settings_dir, '').replace('/', '').replace('\\', '').replace('\\', '').replace('.json', '')
            print(file)
            protocol_names.append(file)

        max_input_register : int = 0
        max_holding_register : int = 0

        for name in protocol_names:
            protocols[name] = protocol_settings(name)

            if protocols[name].input_registry_size > max_input_register:
                max_input_register = protocols[name].input_registry_size

            if protocols[name].input_registry_size > max_holding_register:
                max_holding_register = protocols[name].holding_registry_size

        print("max input register: ", max_input_register)
        print("max holding register: ", max_holding_register)

        self.modbus_delay = self.modbus_delay #decrease delay because can probably get away with it due to lots of small reads
        print("read INPUT Registers: ")

        input_save_path = "input_registry.json"
        holding_save_path = "holding_registry.json"

        #load previous scan if enabled and exists
        if self.__analyze_protocol_save_load and os.path.exists(input_save_path) and os.path.exists(holding_save_path):
            with open(input_save_path, "r") as file:
                input_registry = json.load(file)

            with open(holding_save_path, "r") as file:
                holding_registry = json.load(file)

            # Convert keys to integers
            input_registry = {int(key): value for key, value in input_registry.items()}
            holding_registry = {int(key): value for key, value in holding_registry.items()}
        else:
            #perform registry scan
            ##batch_size = 1, read registers one by one; if out of bound. it just returns error
            input_registry = self.read_registers(min=0, max=max_input_register, batch_size=45, registry=Registry_Type.INPUT)
            holding_registry = self.read_registers(min=0, max=max_holding_register, batch_size=45, registry=Registry_Type.HOLDING)

            if self.__analyze_protocol_save_load: #save results if enabled
                with open(input_save_path, "w") as file:
                    json.dump(input_registry, file)

                with open(holding_save_path, "w") as file:
                    json.dump(holding_registry, file)

        #print results for debug
        print("=== START INPUT REGISTER ===")
        print([(key, value) for key, value in input_registry.items()])
        print("=== END INPUT REGISTER ===")
        print("=== START HOLDING REGISTER ===")
        print([(key, value) for key, value in holding_registry.items()])
        print("=== END HOLDING REGISTER ===")

        #very well possible the registers will be incomplete due to different hardware sizes
        #so dont assume they are set / complete
        #we'll see about the behaviour. if it glitches, this could be a way to determine protocol.
        

        input_register_score : dict[str, int] = {}
        holding_register_score : dict[str, int] = {}

        input_valid_count : dict[str, int] = {}
        holding_valid_count  : dict[str, int] = {}

        def evaluate_score(entry : registry_map_entry, val):
            score = 0
            if entry.data_type == Data_Type.ASCII:
                if val and not re.match('[^a-zA-Z0-9\_\-]', val): #validate ascii
                    mod = 1
                    if entry.concatenate:
                        mod = len(entry.concatenate_registers)

                    if entry.value_regex: #regex validation
                        if re.match(entry.value_regex, val):
                            mod = mod * 2 
                        else: 
                            mod = mod * -2 #regex validation failed, double damage!

                    score = score + (2 * mod) #double points for ascii
                pass
            else: #default type
                if isinstance(val, str):
                    #likely to be a code
                    score = score + 2
                elif val != 0:
                    if val >= entry.value_min and val <= entry.value_max:
                        score = score + 1

                        if entry.value_max != 65535: #double points for non-default range
                            score = score + 1

            return score


        
        for name, protocol in protocols.items():
            input_register_score[name] = 0
            holding_register_score[name] = 0
            #very rough percentage. tood calc max possible score. 
            input_valid_count[name] = 0
            holding_valid_count[name] = 0

            #process registry based on protocol
            input_info = self.process_registery(input_registry, protocol.input_registry_map)
            holding_info = self.process_registery(input_registry, protocol.holding_registry_map)
            

            for entry in protocol.input_registry_map:
                if entry.variable_name in input_info:
                    val = input_info[entry.variable_name]
                    score = evaluate_score(entry, val)
                    if score > 0:
                        input_valid_count[name] = input_valid_count[name] + 1

                    input_register_score[name] = input_register_score[name] + score


            for entry in protocol.holding_registry_map:
                if entry.variable_name in holding_info:
                    val = holding_info[entry.variable_name]
                    score = evaluate_score(entry, val)

                    if score > 0:
                        holding_valid_count[name] = holding_valid_count[name] + 1

                    holding_register_score[name] = holding_register_score[name] + score

        
        protocol_scores: dict[str, int] = {}
        #combine scores
        for name, protocol in protocols.items():
            protocol_scores[name] = input_register_score[name] + holding_register_score[name]

        #print scores
        for name in sorted(protocol_scores, key=protocol_scores.get, reverse=True):
            print("=== "+str(name)+" - "+str(protocol_scores[name])+" ===")
            print("input register score: " + str(input_register_score[name]) + "; valid registers: "+str(input_valid_count[name])+" of " + str(len(protocols[name].input_registry_map)))
            print("holding register score : " + str(holding_register_score[name]) + "; valid registers: "+str(holding_valid_count[name])+" of " + str(len(protocols[name].holding_registry_map)))
        
                    
                    
    def mqtt_discovery(self):
        print("Publishing HA Discovery Topics...")

        disc_payload = {}
        disc_payload['availability_topic'] = self.__mqtt_topic + "/availability"

        device = {}
        device['manufacturer'] = self.__settings.get('mqtt_device', 'manufacturer', fallback='HotNoob')
        device['model'] = self.__settings.get('mqtt_device', 'model', fallback='HotNoob Was Here 2024')
        device['identifiers'] = "hotnoob_" + self.__device_serial_number
        device['name'] = self.__settings.get('mqtt_device', 'name', fallback='Solar Inverter')

        registry_map : list[registry_map_entry] = []
        if self.__send_input_register and self.protocolSettings.input_registry_map:
            registry_map.extend(self.protocolSettings.input_registry_map)

        if self.__send_holding_register and self.protocolSettings.holding_registry_map:
            registry_map.extend(self.protocolSettings.holding_registry_map)

        length = len(registry_map)
        count = 0
        for item in registry_map:
            count = count + 1

            if item.concatenate and item.register != item.concatenate_registers[0]:
                continue #skip all except the first register so no duplicates
            
            if item.write_mode == WriteMode.READDISABLED: #disabled
                continue

            clean_name = item.variable_name.lower().replace(' ', '_')

            if self.__input_register_prefix and item.registry_type == Registry_Type.INPUT:
                clean_name = self.__input_register_prefix + clean_name

            if self.__holding_register_prefix and item.registry_type == Registry_Type.HOLDING:
                clean_name = self.__holding_register_prefix + clean_name


            print('Publishing Topic '+str(count)+' of ' + str(length) + ' "'+str(clean_name)+'"', end='\r', flush=True)

            #device['sw_version'] = bms_version
            disc_payload = {}
            disc_payload['availability_topic'] = self.__mqtt_topic + "/availability"
            disc_payload['device'] = device
            disc_payload['name'] = clean_name
            disc_payload['unique_id'] = "hotnoob_" + self.__device_serial_number + "_"+clean_name

            writePrefix = ""
            if self.__write and item.write_mode == WriteMode.WRITE:
                writePrefix = "" #home assistant doesnt like write prefix

            disc_payload['state_topic'] = self.__mqtt_topic +writePrefix+ "/"+clean_name
            
            if item.unit:
                disc_payload['unit_of_measurement'] = item.unit


            discovery_topic = self.__mqtt_discovery_topic+"/sensor/inverter-" + self.__device_serial_number  + writePrefix + "/" + disc_payload['name'].replace(' ', '_') + "/config"
            
            self.__mqtt_client.publish(discovery_topic,
                                       json.dumps(disc_payload),qos=1, retain=True)
            
            time.sleep(0.01) #slow down for better reliability
        
        self.__mqtt_client.publish(disc_payload['availability_topic'],"online",qos=0, retain=True)
        print()
        self.__log.info("Published HA "+str(count)+"x Discovery Topics")

    #region - was inverter class
    def read_serial_number(self) -> str:
        serial_number = str(self.read_variable("Serial Number", Registry_Type.HOLDING))
        print("read SN: " +serial_number)
        if serial_number:
            return serial_number
        
        sn2 = ""
        sn3 = ""
        fields = ['Serial No 1', 'Serial No 2', 'Serial No 3', 'Serial No 4', 'Serial No 5']
        for field in fields:
            self.__log.info("Reading " + field)
            registry_entry = self.protocolSettings.get_holding_registry_entry(field)
            if registry_entry is not None:
                self.__log.info("Reading " + field + "("+str(registry_entry.register)+")")
                data = self.reader.read_registers(registry_entry.register, registry_type=Registry_Type.HOLDING)
                if not hasattr(data, 'registers') or data.registers is None:
                    self.__log.critical("Failed to get serial number register ("+field+") ; exiting")
                    exit()
                    
                serial_number = serial_number  + str(data.registers[0])

                data_bytes = data.registers[0].to_bytes((data.registers[0].bit_length() + 7) // 8, byteorder='big')
                sn2 = sn2 + str(data_bytes.decode('utf-8')) 
                sn3 = str(data_bytes.decode('utf-8')) + sn3

            time.sleep(self.modbus_delay) #sleep inbetween requests so modbus can rest
        
        print(sn2)
        print(sn3)
        
        if not re.search("[^a-zA-Z0-9\_]", sn2) :
            serial_number = sn2

        return serial_number

    def print_info(self):
        """ prints basic information about the current ModBus inverter """
        self.__log.info('Inverter:')
        self.__log.info('\tName: %s\n', str(self.name))
        self.__log.info('\tUnit: %s\n', str(self.unit))
        self.__log.info('\tModbus Version: %s\n', str(self.modbus_version))

    def write_variable(self, entry : registry_map_entry, value : str, registry_type : Registry_Type = Registry_Type.HOLDING):
        """ writes a value to a ModBus register; todo: registry_type to handle other write functions"""

        #read current value
        current_registers = self.read_registers(start=entry.register, end=entry.register, registry_type=registry_type)
        results = self.process_registery(current_registers, self.protocolSettings.get_registry_map(registry_type))
        current_value = current_registers[entry.register]

      
        if not self.protocolSettings.validate_registry_entry(entry, current_value):
            raise ValueError("Invalid value in register. unsafe to write")
        
        if not self.protocolSettings.validate_registry_entry(entry, value):
            raise ValueError("Invalid new value. unsafe to write")
        
        #handle codes
        if entry.variable_name+"_codes" in self.protocolSettings.codes:
            codes = self.protocolSettings.codes[entry.variable_name+"_codes"]
            for key, val in codes.items():
                if val == value: #convert "string" to key value
                    value = key
                    break

        #results[entry.variable_name]
        ushortValue : int = None #ushort
        if entry.data_type == Data_Type.USHORT:
            ushortValue = int(value)
            if ushortValue < 0 or ushortValue > 65535:
                 raise ValueError("Invalid value")
        elif entry.data_type.value > 200 or entry.data_type == Data_Type.BYTE: #bit types
            bit_size = Data_Type.getSize(entry.data_type)

            new_val = int(value)
            if 0 > new_val or new_val > 2**bit_size:
                raise ValueError("Invalid value")

            bit_index = entry.register_bit
            bit_mask = ((1 << bit_size) - 1) << bit_index  # Create a mask for extracting X bits starting from bit_index
            clear_mask = ~(bit_mask)  # Mask for clearing the bits to be updated

            # Clear the bits to be updated in the current_value
            ushortValue = current_value & clear_mask

            # Set the bits according to the new_value at the specified bit position
            ushortValue |= (new_val << bit_index) & bit_mask

            bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
            check_value = (ushortValue >> bit_index) & bit_mask

            if check_value != new_val:
                raise ValueError("something went wrong bitwise")
        else:
            raise TypeError("Unsupported data type")
            
       

        
        if ushortValue == None:
            raise ValueError("Invalid value - None")

        self.reader.write_register(entry.register, ushortValue, registry_type=registry_type)


    def read_variable(self, variable_name : str, registry_type : Registry_Type, entry : registry_map_entry = None):
        ##clean for convinecne  
        if variable_name:
            variable_name = variable_name.strip().lower().replace(' ', '_')

        registry_map = self.protocolSettings.get_registry_map(registry_type)

        if entry == None:
            for e in registry_map:
                if e.variable_name == variable_name:
                    entry = e
                    break

        if entry:
            start : int = 0
            end : int = 0
            if not entry.concatenate:
                start = entry.register
                end = entry.register
            else:
                start = entry.register
                end = max(entry.concatenate_registers)
            
            registers = self.read_registers(start=start, end=end, registry_type=registry_type)
            results = self.process_registery(registers, registry_map)
            return results[entry.variable_name]
            

    def read_registers(self, ranges : list[tuple] = None, start : int = 0, end : int = None, batch_size : int = 45, registry_type : Registry_Type = Registry_Type.INPUT ) -> dict:
        

        if not ranges: #ranges is empty, use min max
            end = end + 1
            ranges = []
            start = start - batch_size
            while( start := start + batch_size ) < end:
                count = batch_size
                if start + batch_size > end:
                    count = end - start + 1
                ranges.append((start, count)) ##APPEND TUPLE

        registry : dict[int,] = {}
        retries = 7
        retry = 0
        total_retries = 0

        index = -1
        while (index := index + 1) < len(ranges) :
            range = ranges[index]

            print("get registers("+str(index)+"): " + str(range[0]) + " to " + str(range[0]+range[1]-1) + " ("+str(range[1])+")")
            time.sleep(self.modbus_delay) #sleep for 1ms to give bus a rest #manual recommends 1s between commands

            isError = False
            try:
                register = self.reader.read_registers(range[0], range[1], registry_type=registry_type, unit=self.unit)

            except ModbusIOException as e: 
                print("ModbusIOException : ", e.error_code)
                if e.error_code == 4: #if no response; probably time out. retry with increased delay
                    isError = True
                else:
                    raise

            if register.isError() or isError:
                self.__log.error(register.__str__)
                self.modbus_delay = self.modbus_delay + 0.050 #increase delay, error is likely due to modbus being busy

                if self.modbus_delay > 60: #max delay. 60 seconds between requests should be way over kill if it happens
                    self.modbus_delay = 60

                if retry > retries: #instead of none, attempt to continue to read. but with no retires. 
                    continue
                else:
                    #undo step in loop and retry read
                    retry = retry + 1
                    total_retries = total_retries + 1
                    print("Retry("+str(retry)+" - ("+str(total_retries)+")) range("+str(index)+")")
                    index = index - 1
                    continue
            

            retry -= 1
            if retry < 0:
                retry = 0

            #combine registers into "registry"
            i = -1
            while(i := i + 1 ) < range[1]:
                #print(str(i) + " => " + str(i+range[0]))
                registry[i+range[0]] = register.registers[i]

        return registry

    def process_registery(self, registry : dict, map : list[registry_map_entry]) -> dict[str,str]:
        '''process registry into appropriate datatypes and names'''
        
        concatenate_registry : dict = {}
        info = {}
        for item in map:

            if item.register not in registry:
                continue
            value = ''    

            if item.data_type == Data_Type.UINT: #read uint
                if item.register + 1 not in registry:
                    continue
                value = float((registry[item.register] << 16) + registry[item.register + 1])
            elif item.data_type == Data_Type.SHORT: #read signed short
                val = registry[item.register]

                # Convert the combined unsigned value to a signed integer if necessary
                if val & (1 << 15):  # Check if the sign bit (bit 31) is set
                    # Perform two's complement conversion to get the signed integer
                    value = val - (1 << 16)
                else:
                    value = val
                value = -value
            elif item.data_type == Data_Type.INT: #read int
                if item.register + 1 not in registry:
                    continue
                
                combined_value_unsigned = (registry[item.register] << 16) + registry[item.register + 1]

                # Convert the combined unsigned value to a signed integer if necessary
                if combined_value_unsigned & (1 << 31):  # Check if the sign bit (bit 31) is set
                    # Perform two's complement conversion to get the signed integer
                    value = combined_value_unsigned - (1 << 32)
                else:
                    value = combined_value_unsigned
                value = -value
                #value = struct.unpack('<h', bytes([min(max(registry[item.register], 0), 255), min(max(registry[item.register+1], 0), 255)]))[0]
                #value = int.from_bytes(bytes([registry[item.register], registry[item.register + 1]]), byteorder='little', signed=True)
            elif item.data_type == Data_Type._16BIT_FLAGS or item.data_type == Data_Type._8BIT_FLAGS:
                val = registry[item.register]
                #16 bit flags
                start_bit : int = 0
                if item.data_type == Data_Type._8BIT_FLAGS:
                    start_bit = 8
                
                if item.documented_name+'_codes' in self.protocolSettings.codes:
                    flags : list[str] = []
                    for i in range(start_bit, 16):  # Iterate over each bit position (0 to 15)
                        # Check if the i-th bit is set
                        if (val >> i) & 1:
                            flag_index = "b"+str(i)
                            if flag_index in self.protocolSettings.codes[item.documented_name+'_codes']:
                                flags.append(self.protocolSettings.codes[item.documented_name+'_codes'][flag_index])
                            
                    value = ",".join(flags)
                else:
                    flags : list[str] = []
                    for i in range(start_bit, 16):  # Iterate over each bit position (0 to 15)
                        # Check if the i-th bit is set
                        if (val >> i) & 1:
                            flags.append("1")
                        else:
                            flags.append("0")
                    value = ''.join(flags)
            elif item.data_type.value > 200 or item.data_type == Data_Type.BYTE: #bit types
                    bit_size = Data_Type.getSize(item.data_type)
                    bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
                    bit_index = item.register_bit
                    value = (registry[item.register] >> bit_index) & bit_mask
            elif item.data_type == Data_Type.ASCII:
                value = registry[item.register].to_bytes((16 + 7) // 8, byteorder='big') #convert to ushort to bytes
                try:
                    value = value.decode("utf-8") #convert bytes to ascii
                except UnicodeDecodeError as e:
                    print("UnicodeDecodeError:", e)

            else: #default, Data_Type.USHORT
                value = float(registry[item.register])

            if item.unit_mod != float(1):
                value = value * item.unit_mod

            if  isinstance(value, float) and self.max_precision > -1:
                value = round(value, self.max_precision)

            if (item.data_type != Data_Type._16BIT_FLAGS and
                item.documented_name+'_codes' in self.protocolSettings.codes):
                try:
                    cleanval = str(int(value))
            
                    if cleanval in self.protocolSettings.codes[item.documented_name+'_codes']:
                        value = self.protocolSettings.codes[item.documented_name+'_codes'][cleanval]
                except:
                    #do nothing; try is for intval
                    value = value
            
            #if item.unit:
            #    value = str(value) + item.unit
            if item.concatenate:
                concatenate_registry[item.register] = value

                all_exist = True
                for key in item.concatenate_registers:
                    if key not in concatenate_registry:
                        all_exist = False
                        break
                if all_exist:
                #if all(key in concatenate_registry for key in item.concatenate_registers):
                    concatenated_value = ""
                    for key in item.concatenate_registers:
                        concatenated_value = concatenated_value + str(concatenate_registry[key])
                        del concatenate_registry[key]

                    info[item.variable_name] = concatenated_value
            else:
                info[item.variable_name] = value

        return info
    
    def read_registry(self, registry_type : Registry_Type = Registry_Type.INPUT) -> dict[str,str]:
        map = self.protocolSettings.get_registry_map(registry_type)
        if not map:
            return {}
        
        registry = self.read_registers(self.protocolSettings.get_registry_ranges(registry_type), registry_type=registry_type)
        info = self.process_registery(registry, map)
        return info


    def read_input_registry(self) -> dict[str,str]:
        ''' reads input registers and returns as clean dict object inverters '''
        if not self.protocolSettings.input_registry_map: #empty map. no data to read
            return {}
        
        registry = self.read_registers(self.protocolSettings.input_registry_ranges, registry_type=Registry_Type.INPUT)
        info = self.process_registery(registry, self.protocolSettings.input_registry_map)
        return info
    
    def read_holding_registry(self) -> dict[str,str]:
        ''' reads holding registers and returns as clean dict object inverters '''
        if not self.protocolSettings.holding_registry_map: #empty map. no data to read
            return {}

        registry = self.read_registers(self.protocolSettings.holding_registry_ranges, registry_type=Registry_Type.HOLDING)
        info = self.process_registery(registry, self.protocolSettings.holding_registry_map)
        return info
    #endregion - was inveter class


def strtobool (val):
    """Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1'
    """
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return 1
    
    return 0

def main():
    """
    main method
    """
    print(__logo)

    inverter2mqtt = InverterModBusToMQTT(args.config)
    inverter2mqtt.init_invertermodbustomqtt()
    inverter2mqtt.run()


if __name__ == "__main__":
    # Create ArgumentParser object
    parser = argparse.ArgumentParser(description='Description of your script')

    # Add arguments
    parser.add_argument('--config', '-c', type=str, help='Specify Config File', default='config.cfg')
    # Parse arguments
    args = parser.parse_args()

    main()
