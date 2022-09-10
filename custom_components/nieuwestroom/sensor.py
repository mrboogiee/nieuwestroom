"""The nieuwestroom current electricity and gas price information service."""
# A lot has been stolen from https://github.com/bajansen/home-assistant-frank_energie/
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from collections.abc import Callable

import aiohttp
import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorEntity,
    SensorEntityDescription,
)

from homeassistant.const import (
    CONF_DISPLAY_OPTIONS,
    CURRENCY_EURO,
    ENERGY_KILO_WATT_HOUR,
    VOLUME_CUBIC_METERS,
    # VOLUME_CUBIC_METERS,
)

from homeassistant.core import HassJob, HomeAssistant
from homeassistant.helpers import event
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt, utcnow

ATTRIBUTION = "Data provided by easyenergy.com"
DOMAIN = "nieuwestroom"
ELEC_DATA_URL = "https://mijn.easyenergy.com/nl/api/tariff/getapxtariffs?startTimestamp="
GAS_DATA_URL = "https://mijn.easyenergy.com/nl/api/tariff/getlebatariffs?startTimestamp=" #2022-09-08T22%3A00%3A00.000Z&endTimestamp=2022-09-09T22%3A00%3A00.000Z&grouping=&includeVat=false"
ICON = "mdi:currency-eur"


@dataclass
class NieuwestroomEntityDescription(SensorEntityDescription):
    """Describes Nieuwestroom sensor entity."""

    value_fn: Callable[[dict], StateType] = None


SENSOR_TYPES: tuple[NieuwestroomEntityDescription, ...] = (
    NieuwestroomEntityDescription(
        key="elec_market",
        name="Current electricity market price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{ENERGY_KILO_WATT_HOUR}",
        value_fn=lambda data: data["elec"][0],
    ),
    NieuwestroomEntityDescription(
        key="elec_min",
        name="Lowest energy price for 24h",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{ENERGY_KILO_WATT_HOUR}",
        value_fn=lambda data: min(data["today_elec"]),
    ),
    NieuwestroomEntityDescription(
        key="elec_max",
        name="Highest energy price for 24h",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{ENERGY_KILO_WATT_HOUR}",
        value_fn=lambda data: max(data["today_elec"]),
    ),
    NieuwestroomEntityDescription(
        key="elec_avg",
        name="Average electricity price for 24h",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{ENERGY_KILO_WATT_HOUR}",
        value_fn=lambda data: round(
            sum(data["today_elec"]) / len(data["today_elec"]), 5
        ),
    ),
    NieuwestroomEntityDescription(
        key="gas_market",
        name="Current gas market price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{VOLUME_CUBIC_METERS}",
        value_fn=lambda data: data['gas'][0],
    ),
    NieuwestroomEntityDescription(
        key="gas_min",
        name="Lowest gas price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{VOLUME_CUBIC_METERS}",
        value_fn=lambda data: min(data['today_gas']),
    ),
    NieuwestroomEntityDescription(
        key="gas_max",
        name="Highest gas price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{VOLUME_CUBIC_METERS}",
        value_fn=lambda data: max(data['today_gas']),
    ),
)

_LOGGER = logging.getLogger(__name__)

OPTION_KEYS = [desc.key for desc in SENSOR_TYPES]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_DISPLAY_OPTIONS, default=[]): vol.All(
            cv.ensure_list, [vol.In(OPTION_KEYS)]
        ),
    }
)


async def async_setup_platform(
    hass: HomeAssistant, config, async_add_entities, discovery_info=None
) -> None:
    """Set up the Nieuwestroom sensors."""
    _LOGGER.debug("Setting up Nieuwestroom component")

    websession = async_get_clientsession(hass)

    coordinator = NieuwestroomCoordinator(hass, websession)

    entities = [
        NieuwestroomSensor(coordinator, description)
        for description in SENSOR_TYPES
        if description.key in config[CONF_DISPLAY_OPTIONS]
    ]

    await coordinator.async_config_entry_first_refresh()

    async_add_entities(entities, True)


class NieuwestroomSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Nieuwestroom sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON

    def __init__(
        self,
        coordinator: NieuwestroomCoordinator,
        description: NieuwestroomEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description: NieuwestroomEntityDescription = description
        self._attr_unique_id = f"nieuwestroom.{description.key}"

        self._update_job = HassJob(self.async_schedule_update_ha_state(force_refresh=False))
        self._unsub_update = None

        super().__init__(coordinator)

    async def async_update(self) -> None:
        """Get the latest data and updates the states."""
        try:
            self._attr_native_value = self.entity_description.value_fn(
                self.coordinator.processed_data()
            )
        except (TypeError, IndexError):
            # No data available
            self._attr_native_value = None

        # Cancel the currently scheduled event if there is any
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

        # Schedule the next update at exactly the next whole hour sharp
        self._unsub_update = event.async_track_point_in_utc_time(
            self.hass,
            self._update_job,
            # utcnow().replace(minute=0, second=0) + timedelta(hours=1),
            utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1),
        )
class NieuwestroomCoordinator(DataUpdateCoordinator):
    """Get the latest data and update the states."""

    def __init__(self, hass: HomeAssistant, websession) -> None:
        """Initialize the data object."""
        self.hass = hass
        self.websession = websession

        logger = logging.getLogger(__name__)
        super().__init__(
            hass,
            logger,
            name="Nieuwestroom coordinator",
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> dict:
        """Get the latest data from Nieuwestroom"""
        self.logger.debug("Fetching Nieuwestroom data")

        # We request data for today up until the day after tomorrow.
        # This is to ensure we always request all available data.
        today = datetime.utcnow()
        tomorrow = today + timedelta(days=1)
        # day_after_tomorrow = today + timedelta(seconds=300)

        # Fetch data for today and tomorrow separately,
        # because the gas prices response only contains data for the first day of the query
        elec_data_today = await self._run_electricity_query(today, tomorrow)
        gas_data_today = await self._run_gas_query(today, tomorrow)
        # data_tomorrow = await self._run_electricity_query(tomorrow, day_after_tomorrow)
        return {
            "marketPricesElectricity": elec_data_today,
            # + data_tomorrow["TariffUsage"],
            "marketPricesGas": gas_data_today
            # + data_tomorrow["marketPricesGas"],
        }

    async def _run_electricity_query(self, start_date, end_date):
        try:
            full_url = (
                ELEC_DATA_URL
                + str(start_date.year)
                + "-"
                + str("{:02d}".format(start_date.month))
                + "-"
                + str("{:02d}".format(start_date.day))
                + "T"
                + str("{:02d}".format(start_date.hour))
                + "%3A00%3A00.000Z&endTimestamp="
                + str(end_date.year)
                + "-"
                + str("{:02d}".format(end_date.month))
                + "-"
                + str("{:02d}".format(end_date.day))
                + "T"
                + str("{:02d}".format(end_date.hour))
                + "%3A00%3A00.000Z&grouping=&includeVat=false"
            )
            resp = await self.websession.get(full_url)
            data = await resp.json()
            return data

        except (asyncio.TimeoutError, aiohttp.ClientError, KeyError) as error:
            raise UpdateFailed(
                f"Fetching energy data failed: {error}") from error

    async def _run_gas_query(self, start_date, end_date):
        try:
            full_url = (
                GAS_DATA_URL
                + str(start_date.year)
                + "-"
                + str("{:02d}".format(start_date.month))
                + "-"
                + str("{:02d}".format(start_date.day))
                + "T"
                + str("{:02d}".format(start_date.hour))
                + "%3A00%3A00.000Z&endTimestamp="
                + str(end_date.year)
                + "-"
                + str("{:02d}".format(end_date.month))
                + "-"
                + str("{:02d}".format(end_date.day))
                + "T"
                + str("{:02d}".format(end_date.hour))
                + "%3A00%3A00.000Z&grouping=&includeVat=false"
            )
            resp = await self.websession.get(full_url)
            data = await resp.json()
            return data

        except (asyncio.TimeoutError, aiohttp.ClientError, KeyError) as error:
            raise UpdateFailed(
                f"Fetching gas data failed: {error}") from error

    def processed_data(self):
        """supposed to process the data into usable data"""
        return {
            "elec": self.get_current_hourprices(self.data["marketPricesElectricity"]),
            'gas': self.get_current_gas_hourprices(self.data['marketPricesGas']),
            "today_elec": self.get_elec_hourprices(self.data["marketPricesElectricity"]),
            'today_gas': self.get_gas_hourprices(self.data['marketPricesGas']),
        }

    def get_current_hourprices(self, hourprices) -> tuple:
        """get the current hourly pricing"""
        for hour in hourprices:
            if dt.parse_datetime(hour["Timestamp"]) == dt.utcnow().replace(
                minute=0, second=0, microsecond=0
            ):
                return (hour["TariffUsage"],)

    def get_elec_hourprices(self, hourprices) -> list:
        """create a list of hourly rates"""
        today_prices = []
        for hour in hourprices:
            today_prices.append(hour["TariffUsage"])
        return today_prices
    
    def get_current_gas_hourprices(self, hourprices) -> tuple:
        """get the current hourly pricing"""
        for hour in hourprices:
            if dt.parse_datetime(hour["Timestamp"]) == dt.utcnow().replace(
                minute=0, second=0, microsecond=0
            ):
                return (hour["TariffUsage"],)

    def get_gas_hourprices(self, hourprices) -> list:
        """create a list of hourly rates"""
        today_prices = []
        for hour in hourprices:
            today_prices.append(hour["TariffUsage"])
        return today_prices
