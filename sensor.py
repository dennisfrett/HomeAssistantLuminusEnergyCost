import logging
import os
import re
from locale import atof
from PyPDF2 import PdfReader
import voluptuous as vol
import time
import urllib.request

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, CONF_UNIT_OF_MEASUREMENT, CONF_VALUE_TEMPLATE
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

ELEC_PDF_URL = "https://www.luminus.be/-/media/general/pricelists/nl/ecf0c_nl_comfyflex_elec.pdf"
GAS_PDF_URL = "https://www.luminus.be/-/media/general/pricelists/nl/gcf0c_nl_comfyflex_gas.pdf"

# Laagcalorisch gas
GAS_KWH_M3_FACTOR = 10.26

CONF_TYPE = "type"

ATTR_VALUE = "value"

ICON = "mdi:file-pdf"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_TYPE): cv.string,
        vol.Optional(CONF_VALUE_TEMPLATE): cv.template,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    type = config.get(CONF_TYPE)
    value_template = config.get(CONF_VALUE_TEMPLATE)

    if not type == "elek_dag" and not type == "elek_nacht" and not type == "gas":
        _LOGGER.error("Invalid type '%s'. Valid types are 'elek_dag', 'elek_nacht' and 'gas'", type)

    if value_template is not None:
        value_template.hass = hass

    async_add_entities([LuminusEnergyCost(
        type,
        value_template,
    )], True)

class LuminusEnergyCost(Entity):
    def __init__(self,
        type,
        value_template,
        pdf_path = None # For testing
    ):

        self.__type = type
        self.__pdf_path = pdf_path

        _LOGGER.info("Initializing Luminus Energy Cost for '%s'", self.__type)

        if type == "elek_dag":
            self._name = "Luminus Kost Electriciteit (dag)"
            self._unit_of_measurement = "€/kWh"
        elif type == "elek_nacht":
            self._name = "Luminus Kost Electriciteit (nacht)"
            self._unit_of_measurement = "€/kWh"
        elif type == "gas":
            self._name = "Luminus Kost Gas"
            self._unit_of_measurement = "€/m³"
        else:
            _LOGGER.error("Invalid type '%s'. Valid types are 'elek_dag', 'elek_nacht' and 'gas'", type)


        self._val_tpl = value_template
        self.__last_updated = None
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return ICON

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def get_elek_kost_geleverde_energie(self, pdf):
        # Example match string (excl. day, day, night, excl. night)
        # Geleverde energie (c€/kWh) 27,05 31,52 22,72 22,72
        cost_regex = "Geleverde energie\\s+\\(c€\\/kWh\\)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+"
        match_index = 2 if self.__type == "elek_dag" else 3

        try:
            page = pdf.getPage(0)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",",".")

        matches = re.search(cost_regex, text)

        return atof(matches[match_index])

    def get_elek_kost_wkk_groene_stroom(self, pdf):
        # Example match string (Vlaanderen groene stroom, Vlaanderen WKK, Wallonie)
        # Kosten groene
        # stroom (c€/kWh)4
        # Kosten WKK (c€/kWh)4VL
        # 2,22
        # 0,33WAL
        # 3,00

        cost_regex = "Kosten groene.*\\nstroom.*\\n.*VL.*\n([\\d.]+)\\n([\\d.]+)WAL\\n([\\d.]+)"

        try:
            page = pdf.getPage(0)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",",".")

        matches = re.search(cost_regex, text)

        vl_groene_stroom = matches[1]
        vl_wkk = matches[2]

        return atof(vl_groene_stroom) + atof(vl_wkk)

    def get_elek_netkosten(self, pdf):
        # Example match string (excl. day, day, night, excl. night, transport costs, ...)
        # Fluvius (Iverlek) 9,63 9,63 7,06 5,33 1,16 12,22 68,68
        cost_regex = "Fluvius \\(Iverlek\\)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)"
        match_index = 2 if self.__type == "elek_dag" else 3

        try:
            page = pdf.getPage(1)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",", ".")

        matches = re.search(cost_regex, text)

        netkost = atof(matches[match_index])
        transportkost = atof(matches[5])

        return netkost + transportkost

    def get_elek_taksen(self, pdf):
        # Example match string (Laagspanning niet-residentieel, Laagspanning residentieel, Bijzondere accijns Vlaanderen, Bijdrage op de energie Vlaanderen, ...)
        # Bijzondere accijns  (**) (c€/kWh)
        # Bijdrage op de energie  (c€/kWh)
        # Aansluitingsvergoeding  (*)(***)  (c€/kWh)8,4900
        # 0,4500
        # 1,4416
        # 0,2042
        # --
        # -
        # 1,4416
        # 0,2042
        # 0,0750
        cost_regex = "Aansluitingsvergoeding.*\\)([\\d.]+)\\n([\\d.]+)\\n([\\d.]+)\\n([\\d.]+)"
        match_index = 2 if self.__type == "elek_dag" else 3

        try:
            page = pdf.getPage(1)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",",".")

        matches = re.search(cost_regex, text)

        bijzondere_accijns_vl = atof(matches[3])
        bijdrage_energie_vl = atof(matches[4])

        return bijzondere_accijns_vl + bijdrage_energie_vl

    def get_gas_kost_energie(self, pdf):
        # Example match string 
        # Energie (c€/kWh) 12.31
        cost_regex = "Energie\\s+\\(c€\\/kWh\\)\\s+([\\d.]+)"

        try:
            page = pdf.getPage(0)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",",".")

        matches = re.search(cost_regex, text)

        return atof(matches[1])

    def get_gas_netkosten(self, pdf):
        # Currently this hardcodes to "gemiddeld verbruik"

        # Example match string (klein verbruik kost/kWh, kv vast, gemiddeld verbruik kost/kWh, gev vast, groot verbruik kost/kWh, grv vast, transportkosten, ...)
        # Fluvius (Iverlek) 1.72 11.91 0.77 59.37 0.52 445.03 0.1410 12.22
        cost_regex = "Fluvius \\(Iverlek\\)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)"

        try:
            page = pdf.getPage(1)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",", ".")

        matches = re.search(cost_regex, text)

        netkost_gemiddeld = atof(matches[3])
        transportkost = atof(matches[7])

        return netkost_gemiddeld + transportkost

    def get_gas_taksen(self, pdf):

        # Example match string: (Bijdrage op energie VL, bijz, accijns VL, bijdrage energie WAL, ...)
        # Taksen en heffingen :VL WAL
        # Bijdrage op de energie  (c€/kWh)
        # Bijzondere accijns   (c€/kWh)
        # Aansluitingsvergoeding  (*)(**) (c€/kWh)0.1058
        # 0.0572
        # -0.1058
        # 0.0572
        # 0.0075

        cost_regex = "Aansluitingsvergoeding.*kWh\\)([\\d.]+)\\n([\\d.]+)"

        try:
            page = pdf.getPage(1)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText().replace(",",".")

        matches = re.search(cost_regex, text)

        bijdrage_energie_vl = atof(matches[1])
        bijzondere_accijns_vl = atof(matches[2])

        return  bijdrage_energie_vl + bijzondere_accijns_vl

    def get_elek_month(self, pdf):

        # Example match string:
        # Luminus ComfyFlex Gas(september 2022 )
        month_regex = "Luminus ComfyFlex Elektriciteit\\(([a-zA-Z]+)\\s\\d\\d\\d\\d\\s+\\)"

        try:
            page = pdf.getPage(0)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText()
        
        matches = re.search(month_regex, text)

        return matches[1]

    def get_gas_month(self, pdf):

        # Example match string:
        # Luminus ComfyFlex Gas(september 2022 )
        month_regex = "Luminus ComfyFlex Gas\\(([a-zA-Z]+)\\s\\d\\d\\d\\d\\s+\\)"

        try:
            page = pdf.getPage(0)
        except IndexError:
            _LOGGER.error("Index error in pdf")

        text = page.extractText()
        
        matches = re.search(month_regex, text)

        return matches[1]

    def should_refresh_state(self, cur_time):
        # Filter out invalid values
        if self._state is None:
            return True

        if self._state == "0":
            return True

        # Only update if we haven't updated for a day or never
        if self.__last_updated is None:
            return True

        if cur_time - self.__last_updated > 86400:
            return True

        return False

    def get_refreshed_state_elek(self, cur_time):

        # Only download PDF if we didn't pass in a path.
        if self.__pdf_path is None:
            # Download PDF to temp file
            pdf_file, headers = urllib.request.urlretrieve(ELEC_PDF_URL)
        else:
            pdf_file = self.__pdf_path

        total_cost_str = None

        with open(pdf_file, 'rb') as file_data:
            pdf = PdfReader(file_data)

            month = self.get_elek_month(pdf)
            _LOGGER.info("Got electricity PDF for month %s", month)

            # Extract costs from PDF
            geleverde_energie = self.get_elek_kost_geleverde_energie(pdf)
            wkk_groene_stroom = self.get_elek_kost_wkk_groene_stroom(pdf)
            netkosten = self.get_elek_netkosten(pdf)
            taksen = self.get_elek_taksen(pdf)

            # Total cost in cent/kWh
            total = geleverde_energie + wkk_groene_stroom + netkosten + taksen

            # Convert cent -> eur
            total = total / 100

            total = round(total, 3)

            total_cost_str = str(total)

            self.__last_updated = cur_time

        if self.__pdf_path is None:
            # Remove temp file
            os.remove(pdf_file)

        return total_cost_str

    def get_refreshed_state_gas(self, cur_time):

        # Only download PDF if we didn't pass in a path.
        if self.__pdf_path is None:
            # Download PDF to temp file
            pdf_file, headers = urllib.request.urlretrieve(GAS_PDF_URL)
        else:
            pdf_file = self.__pdf_path

        total_cost_str = None

        with open(pdf_file, 'rb') as file_data:
            pdf = PdfReader(file_data)

            month = self.get_gas_month(pdf)
            _LOGGER.info("Got gas PDF for month %s", month)

            # Extract costs from PDF
            energie = self.get_gas_kost_energie(pdf)
            netkosten = self.get_gas_netkosten(pdf)
            taksen = self.get_gas_taksen(pdf)

            # Total cost in cent/kWh
            total = energie + netkosten + taksen

            # Convert cent -> eur
            total = total / 100

            # Convert kWh price -> m3 price
            total = total * GAS_KWH_M3_FACTOR

            total = round(total, 3)

            total_cost_str = str(total)

            self.__last_updated = cur_time

        if self.__pdf_path is None:
            # Remove temp file
            os.remove(pdf_file)

        return total_cost_str

    def get_refreshed_state(self, cur_time):
        _LOGGER.info("Refreshing Luminus energy cost state for '%s', downloading PDF", self.__type)

        if self.__type == "gas":
            return self.get_refreshed_state_gas(cur_time)
        else:
            return self.get_refreshed_state_elek(cur_time)

    def update(self):
        cur_time = time.time()

        state = self._state

        if self.should_refresh_state(cur_time):
            state = self.get_refreshed_state(cur_time)
        else:
            _LOGGER.debug("Not refreshing Luminus energy cost state for '%s', returning previous state", self.__type)


        if self._val_tpl is not None:
            variables = {
                ATTR_VALUE: state
            }
            state = self._val_tpl.render(variables, parse_result=False)

        if len(state) > 255:
            _LOGGER.warning("State exceeds 255 characters, truncating: %s", state)
            state = state[:255]

        self._state = state
