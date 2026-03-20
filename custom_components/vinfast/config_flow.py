import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_GEMINI_API_KEY, CONF_REGION, CONF_LANGUAGE

_LOGGER = logging.getLogger(__name__)

CONF_GEMINI_MODEL = "gemini_model"

GEMINI_MODELS = {
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
}

REGIONS = {"VN": "Việt Nam (VN)", "US": "United States (US)", "EU": "Europe (EU)"}
LANGUAGES = {"vi": "Tiếng Việt (VI)", "en": "English (EN)"}

def safe_int(val, default):
    try: return int(float(val))
    except (ValueError, TypeError): return default

def safe_float(val, default):
    try: return float(val)
    except (ValueError, TypeError): return default

class VinFastConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_EMAIL], data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_REGION, default="VN"): vol.In(REGIONS),
            vol.Required(CONF_LANGUAGE, default="vi"): vol.In(LANGUAGES),
            vol.Optional(CONF_GEMINI_API_KEY, default=""): str,
            vol.Optional(CONF_GEMINI_MODEL, default="gemini-2.5-flash"): vol.In(GEMINI_MODELS),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return VinFastOptionsFlowHandler(config_entry)

class VinFastOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        data = self._config_entry.data
        
        current_region = opts.get(CONF_REGION, data.get(CONF_REGION, "VN"))
        current_lang = opts.get(CONF_LANGUAGE, data.get(CONF_LANGUAGE, "vi"))
        current_gemini_key = opts.get(CONF_GEMINI_API_KEY, data.get(CONF_GEMINI_API_KEY, ""))
        current_gemini_model = opts.get(CONF_GEMINI_MODEL, data.get(CONF_GEMINI_MODEL, "gemini-2.5-flash"))

        options_schema = vol.Schema({
            vol.Required(CONF_REGION, default=current_region): vol.In(REGIONS),
            vol.Required(CONF_LANGUAGE, default=current_lang): vol.In(LANGUAGES),
            vol.Optional(CONF_GEMINI_API_KEY, default=current_gemini_key): str,
            vol.Optional(CONF_GEMINI_MODEL, default=current_gemini_model): vol.In(GEMINI_MODELS),
            vol.Required("cost_per_kwh", default=safe_int(opts.get("cost_per_kwh"), 4000)): vol.Coerce(int),
            vol.Required("gas_price", default=safe_int(opts.get("gas_price"), 20000)): vol.Coerce(int),
        })
        
        return self.async_show_form(step_id="init", data_schema=options_schema)