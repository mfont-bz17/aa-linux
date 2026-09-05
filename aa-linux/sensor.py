"""Pluggable sensor data consumer — HU sensor messages forwarded to a backend.

AAContext parses incoming HU sensor messages and forwards them to a
``SensorBackend``. Subclass the base and override the per-sensor template
handlers you care about (one method per SensorType); the default publishes to
the D-Bus sensor service (``DbusSensorBackend``).
"""

from __future__ import annotations

import asyncio
import threading
import time

from .util import log

NIGHT_DATA = 10

SENSOR_TYPE_NAMES = {
    1: "LOCATION",
    2: "COMPASS",
    3: "CAR_SPEED",
    4: "RPM",
    5: "ODOMETER",
    6: "FUEL_LEVEL",
    7: "PARKING_BRAKE",
    8: "GEAR",
    9: "DIAGNOSTICS",
    10: "NIGHT_DATA",
    11: "ENVIRONMENT",
    12: "HVAC",
    13: "DRIVING_STATUS",
    14: "DEAD_RECONING",
    15: "PASSENGER",
    16: "DOOR",
    17: "LIGHT",
    18: "TIRE",
    19: "ACCEL",
    20: "GYRO",
    21: "GPS",
    22: "TOLL_CARD",
    23: "VEHICLE_ENERGY_MODEL",
    24: "TRAILER",
    25: "RAW_VEHICLE_ENERGY_MODEL",
    26: "RAW_EV_TRIP_SETTINGS",
}

# SensorType field number -> per-sensor template handler
_SENSOR_HANDLERS = {
    1: "on_location",
    2: "on_compass",
    3: "on_speed",
    4: "on_rpm",
    5: "on_odometer",
    6: "on_fuel_level",
    7: "on_parking_brake",
    8: "on_gear",
    9: "on_diagnostics",
    10: "on_night_mode",
    11: "on_environment",
    12: "on_hvac",
    13: "on_driving_status",
    14: "on_steering_wheel",
    15: "on_passenger",
    16: "on_door",
    17: "on_light",
    18: "on_tire_pressure",
    19: "on_accel",
    20: "on_gyro",
    21: "on_gps_satellite",
    22: "on_toll_card",
    23: "on_vehicle_energy_model",
    24: "on_trailer",
    25: "on_raw_vehicle_energy_model",
    26: "on_raw_ev_trip_settings",
}


class SensorBackend:
    """Base class for consuming HU sensor data — one handler per sensor type.

    Override the handlers you need; every handler is called with
    ``(channel, data)`` where ``data`` is the parsed per-sensor message
    (e.g. ``oaa.sensor.SpeedData_pb2.Speed``). ``on_unknown`` receives any
    sensor type not covered by the template.
    """

    def on_event(self, channel: int, event) -> None:
        """Called for each SensorEventIndication; dispatches per present field."""
        for field, values in event.ListFields():
            handler = _SENSOR_HANDLERS.get(field.number)
            for item in values:
                if handler is not None:
                    getattr(self, handler)(channel, item)
                else:
                    self.on_unknown(channel, field.number, item)

    # ------------------------------------------------------------------
    # Per-sensor template (all 26 SensorType fields)
    # ------------------------------------------------------------------

    def on_location(self, channel: int, data) -> None:            # GPSLocation
        pass

    def on_compass(self, channel: int, data) -> None:             # Compass
        pass

    def on_speed(self, channel: int, data) -> None:               # Speed
        pass

    def on_rpm(self, channel: int, data) -> None:                 # RPM
        pass

    def on_odometer(self, channel: int, data) -> None:            # Odometer
        pass

    def on_fuel_level(self, channel: int, data) -> None:          # FuelLevel
        pass

    def on_parking_brake(self, channel: int, data) -> None:       # ParkingBrake
        pass

    def on_gear(self, channel: int, data) -> None:                # Gear
        pass

    def on_diagnostics(self, channel: int, data) -> None:         # Diagnostics
        pass

    def on_night_mode(self, channel: int, data) -> None:          # NightMode
        pass

    def on_environment(self, channel: int, data) -> None:         # Environment
        pass

    def on_hvac(self, channel: int, data) -> None:                # HVAC
        pass

    def on_driving_status(self, channel: int, data) -> None:      # DrivingStatus
        pass

    def on_steering_wheel(self, channel: int, data) -> None:      # SteeringWheel
        pass

    def on_passenger(self, channel: int, data) -> None:           # Passenger
        pass

    def on_door(self, channel: int, data) -> None:                # Door
        pass

    def on_light(self, channel: int, data) -> None:               # Light
        pass

    def on_tire_pressure(self, channel: int, data) -> None:       # TirePressure
        pass

    def on_accel(self, channel: int, data) -> None:               # Accel
        pass

    def on_gyro(self, channel: int, data) -> None:                # Gyro
        pass

    def on_gps_satellite(self, channel: int, data) -> None:       # GpsSatelliteData
        pass

    def on_toll_card(self, channel: int, data) -> None:           # TollCardData
        pass

    def on_vehicle_energy_model(self, channel: int, data) -> None:  # VehicleEnergyModelData
        pass

    def on_trailer(self, channel: int, data) -> None:             # TrailerData
        pass

    def on_raw_vehicle_energy_model(self, channel: int, data) -> None:  # RawVehicleEnergyModel
        pass

    def on_raw_ev_trip_settings(self, channel: int, data) -> None:  # RawEvTripSettings
        pass

    def on_unknown(self, channel: int, sensor_type: int, data) -> None:
        pass

    # ------------------------------------------------------------------
    # Channel-level messages
    # ------------------------------------------------------------------

    def on_start_response(self, channel: int, status: int) -> None:
        """Called when the HU answers a sensor subscription request."""

    def on_error(self, channel: int, sensor_type: int, status: int) -> None:
        """Called when the HU reports a sensor error."""


def _msg_to_dict(msg) -> dict:
    """Recursively convert a protobuf message to JSON-friendly primitives.

    Scalars/enums stay as-is, bytes become hex, nested messages become dicts
    and repeated fields become lists.
    """
    out = {}
    for fd, value in msg.ListFields():
        if fd.type == fd.TYPE_MESSAGE:
            if fd.is_repeated:
                out[fd.name] = [_msg_to_dict(v) for v in value]
            else:
                out[fd.name] = _msg_to_dict(value)
        elif fd.type == fd.TYPE_BYTES:
            out[fd.name] = value.hex()
        elif fd.is_repeated:
            out[fd.name] = list(value)
        else:
            out[fd.name] = value
    return out


# ---------------------------------------------------------------------------
# D-Bus backend — mirrors the latest reading of every sensor to a service on
# the session bus (org.aalinux.sensors, /org/aalinux/sensors) as per-sensor
# a{sv} properties, matching what fake_sensors.py publishes. Consumed by the
# standalone sensor_display.py dashboard and sensor_web.py.
# ---------------------------------------------------------------------------

_DBUS_NAME = "org.aalinux.sensors"
_DBUS_PATH = "/org/aalinux/sensors"
_DBUS_IFACE = "org.aalinux.sensors"

# sensor name (lowercased SENSOR_TYPE_NAMES) -> D-Bus property name
_DBUS_PROPERTIES = {
    "car_speed": "carspeed",
    "gear": "gear",
    "parking_brake": "parkingbrake",
    "night_data": "nightdata",
    "driving_status": "drivingstatus",
    "location": "location",
    "gps": "gps",
    "accel": "accel",
    "gyro": "gyro",
}

try:
    from dbus_fast import Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import PropertyAccess, ServiceInterface, dbus_property

    _DBUS_AVAILABLE = True
except ImportError:
    _DBUS_AVAILABLE = False


def _dbus_variant(v):
    """Map a JSON-like value onto the dbus-fast type system."""
    if isinstance(v, bool):
        return Variant("b", v)
    if isinstance(v, int):
        return Variant("i", v)
    if isinstance(v, float):
        return Variant("d", v)
    if isinstance(v, str):
        return Variant("s", v)
    if isinstance(v, dict):
        return Variant("a{sv}", {k: _dbus_variant(x) for k, x in v.items()})
    if isinstance(v, list):
        return Variant("aa{sv}", [{k: _dbus_variant(x) for k, x in item.items()} for item in v])
    return Variant("s", str(v))


if _DBUS_AVAILABLE:

    class _SensorService(ServiceInterface):
        """Exposes the latest reading of every sensor as a read-only a{sv} property."""

        def __init__(self, iface: str = _DBUS_IFACE):
            super().__init__(iface)
            self._values: dict = {}
            self._lock = threading.Lock()

        def set_values(self, values: dict) -> None:
            with self._lock:
                self._values = dict(values)

        def _prop(self, name: str) -> dict:
            with self._lock:
                data = self._values.get(name)
            if not data:
                return {}
            return {k: _dbus_variant(v) for k, v in data.items()}

        @dbus_property(access=PropertyAccess.READ)
        def carspeed(self) -> "a{sv}":
            return self._prop("carspeed")

        @dbus_property(access=PropertyAccess.READ)
        def gear(self) -> "a{sv}":
            return self._prop("gear")

        @dbus_property(access=PropertyAccess.READ)
        def parkingbrake(self) -> "a{sv}":
            return self._prop("parkingbrake")

        @dbus_property(access=PropertyAccess.READ)
        def nightdata(self) -> "a{sv}":
            return self._prop("nightdata")

        @dbus_property(access=PropertyAccess.READ)
        def drivingstatus(self) -> "a{sv}":
            return self._prop("drivingstatus")

        @dbus_property(access=PropertyAccess.READ)
        def location(self) -> "a{sv}":
            return self._prop("location")

        @dbus_property(access=PropertyAccess.READ)
        def gps(self) -> "a{sv}":
            return self._prop("gps")

        @dbus_property(access=PropertyAccess.READ)
        def accel(self) -> "a{sv}":
            return self._prop("accel")

        @dbus_property(access=PropertyAccess.READ)
        def gyro(self) -> "a{sv}":
            return self._prop("gyro")

    class DbusSensorBackend(SensorBackend):
        """Publishes the latest reading of every sensor to a D-Bus service on
        the session bus (org.aalinux.sensors, /org/aalinux/sensors) as per-sensor
        a{sv} properties, for the standalone sensor_display.py dashboard. Runs
        its own asyncio loop in a background thread; reconnects automatically if
        the bus drops."""

        def __init__(self, bus_name: str = _DBUS_NAME, path: str = _DBUS_PATH,
                     iface: str = _DBUS_IFACE):
            self._svc = _SensorService(iface)
            self._bus_name = bus_name
            self._path = path
            self._values: dict = {}
            threading.Thread(target=self._run, daemon=True).start()

        def _run(self) -> None:
            asyncio.run(self._bus_loop())

        async def _bus_loop(self) -> None:
            warned = False
            while True:
                try:
                    bus = await MessageBus().connect()
                except Exception as e:
                    if not warned:
                        log(f"Sensor D-Bus: connect failed ({e}); will retry")
                        warned = True
                    await asyncio.sleep(5.0)
                    continue
                warned = False
                try:
                    bus.export(self._path, self._svc)
                    await bus.request_name(self._bus_name)
                    log(f"Sensor D-Bus service connected: {self._bus_name} {self._path}")
                    await bus.wait_for_disconnect()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log(f"Sensor D-Bus: {e}; reconnecting")
                finally:
                    try:
                        bus.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(2.0)

        def on_event(self, channel: int, event) -> None:
            now = time.time()
            for field, values in event.ListFields():
                name = SENSOR_TYPE_NAMES.get(field.number, field.name).lower()
                prop = _DBUS_PROPERTIES.get(name)
                if prop is None:
                    continue
                for item in values:
                    self._values[prop] = {
                        "type": field.number,
                        "ts": now,
                        **_msg_to_dict(item),
                    }
            self._svc.set_values(self._values)
