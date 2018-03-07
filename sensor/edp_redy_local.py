# """
# Creates sensors for EDP Re:dy power readings
# """
import asyncio
import json
import logging
import decimal
import requests
from datetime import timedelta

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.const import ATTR_FRIENDLY_NAME, CONF_HOST
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity, async_generate_entity_id
from homeassistant.helpers.event import (async_track_state_change,
                                         async_track_point_in_time)
from homeassistant.helpers.restore_state import async_get_last_state
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers import template as template_helper
from homeassistant.util import dt as dt_util

from html.parser import HTMLParser

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'edp_redy_local'
ATTR_LAST_COMMUNICATION = 'last_communication'
ATTR_ONLINE = 'online'
ATTR_ENTITY_PICTURE = 'entity_picture'
ATTR_VOLTAGE = 'Voltagem'
ATTR_ICON = 'icon'
CONF_UPDATE_INTERVAL = 'update_interval'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_UPDATE_INTERVAL, default=30): cv.positive_int,
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    class RedyHTMLParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self._json = ''

        def handle_data(self, data):
            if data.find('REDYMETER') != -1:
                self._json = data

        def json(self):
            return self._json

    sensors = {}
    new_sensors_list = []

    def load_sensor(sensor_id, name, power, last_communication, is_online, voltage, contracted_power):
        if sensor_id in sensors:
            sensors[sensor_id].update_data(power, last_communication, is_online, voltage, contracted_power)
            return

        # create new sensor
        sensor = EdpRedyLocalSensor(sensor_id, name, power, last_communication, is_online, None, None) 
        sensors[sensor_id] = sensor
        new_sensors_list.append(sensor)

    def get_json_section(json, section_tag):
        if section_tag in json:
            if len(json[section_tag]) > 0:
                return json[section_tag][0]
        return None

    def read_nodes(json_nodes):
        for node in json_nodes:
#            if "NAME" not in node:
#              _LOGGER.error("sensor NO NAME wtf!!")
#            else: 
#              _LOGGER.error("sensor %s", node["NAME"])
            if "EMETER:POWER_APLUS" not in node:
                continue

            node_id = node["ID"]
            node_name = node["NAME"]
            node_power = node["EMETER:POWER_APLUS"]
            if "ONLINE" not in node:
              node_is_online = None
            else: 
              node_is_online = node["ONLINE"]
            load_sensor(node_id, node_name, node_power, None, None, None, None)

    def parse_data(json):
        redymeter_section = get_json_section(json, "REDYMETER")
        if redymeter_section:
            read_nodes(redymeter_section["NODES"])

        for znodes in json["ZBENDPOINT"]:
           if znodes:
              read_nodes(znodes["NODES"])

        edpbox_section = get_json_section(json, "EDPBOX")
        if edpbox_section:
            edpbox_id = edpbox_section["SMARTMETER_ID"]
            edpbox_power = edpbox_section["EMETER:POWER_APLUS"]
            edpbox_last_comm = edpbox_section["LAST_COMMUNICATION"]
            edpbox_is_online = edpbox_section["ONLINE"]
            edpbox_voltage = edpbox_section["EMETER:VOLTAGE_L1"]
            edpbox_contracted_power = edpbox_section["CONTRACTED_POWER"]
            load_sensor(edpbox_id, "Smart Meter", edpbox_power, edpbox_last_comm,edpbox_is_online,edpbox_voltage,edpbox_contracted_power)

    def update(time):
        """Fetch data from the redy box and update sensors."""
        host = config[CONF_HOST]

        try:

            # get the data from the box
            data_html = requests.get('http://{}:1234/api/devices'.format(host))

            html_parser = RedyHTMLParser()
            html_parser.feed(
                data_html.content.decode(data_html.apparent_encoding))
            html_parser.close()
            html_json = html_parser.json()
            j = json.loads(html_json)

            new_sensors_list.clear()
            parse_data(j)
            if len(new_sensors_list) > 0:
                async_add_devices(new_sensors_list)

        except requests.exceptions.RequestException as error:
            _LOGGER.error("Failed to get data from redy box: %s", error)
        except Exception as ex:
            _LOGGER.error("WTF? %s    >    %s", type(ex).__name__, ex)

        # schedule next update
        async_track_point_in_time(hass, update, time + timedelta(
            seconds=config[CONF_UPDATE_INTERVAL]))

    update(dt_util.utcnow())


class EdpRedyLocalSensor(Entity):
    """Representation of a sensor."""

    def __init__(self, node_id, name, power, last_communication, is_online, voltage, contracted_power):
        """Set up sensor and add update callback to get data from websocket."""
        self._id = node_id
        self._name = 'Power {0}'.format(name)
        if power is not None:
         self._power = round(float(power)*1000, 0)        
        else: 
         self._power = power
        self._last_comm = last_communication
        self._is_online = is_online
        if voltage is not None:
         self._voltage = round(float(voltage),0)
        else: 
         self._voltage = voltage
        if contracted_power is not None:
         self._contracted_power = round(float(contracted_power)/(1000), 2)
        else: 
         self._contracted_power = contracted_power
        _LOGGER.error("init %s", self._name)

    def update_data(self, power, last_communication, is_online, voltage, contracted_power):
        """Update the sensor's state."""
        if power is not None:
         self._power = round(float(power)*1000, 0)        
        else: 
         self._power = power
        self._last_comm = last_communication
        self._is_online = is_online
        if voltage is not None:
         self._voltage = round(float(voltage),0)
        else: 
         self._voltage = voltage
        if contracted_power is not None:
         self._contracted_power = float(contracted_power)/(1000)
        else: 
         self._contracted_power = contracted_power
        self.async_schedule_update_ha_state()
#        _LOGGER.error("updated %s", self._name)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._power

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique identifier for this sensor."""
        return self._id

    @property
    def device_class(self):
        """Return the class of the sensor."""
#        if self._is_online:
#           return "plug"
        return "power"

#    @property
#    def icon(self):
#        """Return the icon to use in the frontend."""
#        return self._sensor.sensor_icon

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this sensor."""
        return 'W'

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def device_state_attributes(self):
        """Return the state attributes of the sensor."""
        if self._last_comm:
             if self._is_online and self._is_online == 'TRUE':
                attr = {
                    ATTR_LAST_COMMUNICATION: self._last_comm,
                    ATTR_ONLINE: self._is_online,
                    ATTR_ICON: 'mdi:cloud-outline',
                    ATTR_VOLTAGE: self._voltage
                }
             elif self._is_online and self._is_online == 'FALSE':
                attr = {
                    ATTR_LAST_COMMUNICATION: self._last_comm,
                    ATTR_ONLINE: self._is_online,
                    ATTR_ICON: 'mdi:cloud-off-outline',
                    ATTR_VOLTAGE: self._voltage
                }
             else: 
                attr = {
                    ATTR_LAST_COMMUNICATION: self._last_comm,
                }
             return attr
        return None
