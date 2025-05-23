
import logging
from classes.protocol_settings import Registry_Type,protocol_settings,registry_map_entry

from typing import Callable
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .transport_base import transport_base
    from configparser import SectionProxy

class transport_base:
    type : str = ''
    protocolSettings : 'protocol_settings'
    protocol_version : str = ''
    transport_name : str = ''
    device_name : str = ''
    device_serial_number : str = ''
    device_manufacturer : str = 'hotnoob'
    device_model : str = 'hotnoob'
    device_identifier : str = 'hotnoob'
    bridge : str = ''
    write_enabled : bool = False
    max_precision : int = 2

    read_interval : float = 0
    last_read_time : float = 0

    connected : bool = False

    on_message : Callable[['transport_base', registry_map_entry, str], None] = None
    ''' callback, on message recieved '''

    _log : logging.Logger = None

    def __init__(self, settings : 'SectionProxy', protocolSettings : 'protocol_settings' = None) -> None:
        
        self.transport_name = settings.name #section name

        #apply log level to logger
        self._log_level = getattr(logging, settings.get('log_level', fallback='INFO'), logging.INFO)
        short_name : str = __name__[__name__.rfind('.'): ] if '.' in __name__ else None
        self._log : logging.Logger = logging.getLogger(short_name + f"[{self.transport_name}]")

        self._log.setLevel(self._log_level)
        
        self.type = self.__class__.__name__ 

        self.protocolSettings = protocolSettings
        if not self.protocolSettings: #if not, attempt to load. lazy i know
            self.protocol_version = settings.get('protocol_version')
            if self.protocol_version:
                self.protocolSettings = protocol_settings(self.protocol_version)

        if self.protocolSettings:
            self.protocol_version = self.protocolSettings.protocol

            #todo, reimplement default settings from protocolsettings

        if settings:
            self.device_serial_number = settings.get(["device_serial_number", "serial_number"], self.device_serial_number)
            self.device_manufacturer = settings.get(["device_manufacturer", "manufacturer"], self.device_manufacturer)
            self.device_name = settings.get(['device_name', 'name'], fallback=self.device_manufacturer+"_"+self.device_serial_number)
            self.bridge = settings.get("bridge", self.bridge)
            self.read_interval = settings.getfloat("read_interval", self.read_interval)
            self.max_precision = settings.getint(["max_precision", "precision"], self.max_precision)
            if "write_enabled" in settings:
                self.write_enabled = settings.getboolean(["write_enabled", "enable_write"], self.write_enabled)
            else:
                self.write_enabled = settings.getboolean("write", self.write_enabled)
                
        self.update_identifier()


    def update_identifier(self):
        self.device_identifier = self.device_serial_number.strip().lower()

    def init_bridge(self, from_transport : 'transport_base'):
        pass

    @classmethod
    def _get_top_class_name(cls, cls_obj):
        if not cls_obj.__bases__:
            return cls_obj.__name__
        else:
            return cls._get_top_class_name(cls_obj.__bases__[0])

    def connect(self):
        pass

    def write_data(self, data : dict[str, registry_map_entry], from_transport : 'transport_base'):
        ''' general purpose write function for between transports'''
        pass

    #lets convert this to dict[str, registry_map_entry]
    def read_data(self) -> dict[str,str]:
        ''' general purpose read function for between transports; 
        return type may be changed to dict[str, registrsy_map_entry]. still thinking about this'''
        pass



    def enable_write(self):
        ''' required for sensitive / manually defined protocols '''
        pass

    #region - modbus
    #might limit to modbus_base only. not sure; might also apply to future protocols
    def read_registers(self, start, count=1, registry_type : Registry_Type = Registry_Type.INPUT, **kwargs):
        pass

    def write_register(self, register : int, value : int, **kwargs):
        pass

    def analyse_protocol(self):
        pass

    def validate_protocol(self, protocolSettings : 'protocol_settings') -> float:
        ''' validates protocol'''
        pass
    #endregion