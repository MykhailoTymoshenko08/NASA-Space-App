"""Plain-language names of model features and the groups used to explain the model (SHAP) to a farmer."""

CROP_NAMES = {  # slug -> (en, uk)
    "corn": ("Corn", "Кукурудза"), "soybean": ("Soybean", "Соя"), "winter_wheat": ("Winter wheat", "Озима пшениця"),
    "sorghum": ("Sorghum", "Сорго"), "alfalfa": ("Alfalfa", "Люцерна"), "oats": ("Oats", "Овес"),
    "barley": ("Barley", "Ячмінь"), "cereal_rye": ("Cereal rye (cover)", "Жито (покривне)"),
    "other": ("other / fallow / unknown", "інше / пар / невідомо"),
}

BASE_DESC = {  # feature -> (en, uk)
    "prev_crop_1": ("last year's crop", "що росло на полі торік"),
    "prev_crop_2": ("crop two years ago", "що росло на полі позаторік"),
    "lat": ("latitude", "широта поля"), "lon": ("longitude", "довгота поля"), "state_fips": ("state", "штат"),
    "clay_pct": ("clay in the soil", "вміст глини в ґрунті"), "sand_pct": ("sand in the soil", "вміст піску в ґрунті"),
    "om_pct": ("soil organic matter", "органічна речовина в ґрунті"),
    "soc_pct": ("soil organic carbon", "органічний вуглець у ґрунті"), "ph_h2o": ("soil pH", "кислотність ґрунту (pH)"),
    "ec_ds_m": ("soil salinity", "засоленість ґрунту"), "awc_cm_cm": ("soil water holding capacity", "здатність ґрунту тримати воду"),
    "kw_factor": ("soil erodibility", "схильність ґрунту до ерозії"), "hydgrp": ("soil hydrologic group", "гідрологічна група ґрунту"),
    "drainage_class": ("soil drainage", "дренаж ґрунту"), "texture_class": ("soil texture", "текстура ґрунту"),
    "slope_pct": ("field slope", "ухил поля"), "twi": ("terrain wetness index", "індекс вологості рельєфу"),
    "gdd_grow": ("growing-season heat sum", "сума активних температур за сезон"),
    "tmean_grow": ("mean growing-season temperature", "середня температура вегетації"),
    "tmax_summer": ("summer maximum temperature", "літня максимальна температура"),
    "heat_days_32": ("days above 32 C", "днів спеки понад 32°C"), "heat_days_35": ("days above 35 C", "днів сильної спеки понад 35°C"),
    "precip_grow": ("growing-season rainfall", "опади за вегетацію"), "precip_spring": ("spring rainfall", "весняні опади"),
    "precip_summer": ("summer rainfall", "літні опади"), "et0_grow": ("growing-season evaporation", "випаровування за вегетацію"),
    "water_balance_grow": ("water balance (rain minus evaporation)", "водний баланс (опади мінус випаровування)"),
    "max_dry_spell": ("longest dry spell", "найдовша посуха"), "extreme_rain_days_spring": ("days of heavy spring rain", "днів сильних весняних дощів"),
    "extreme_rain_days_year": ("days of heavy rain per year", "днів сильних дощів за рік"),
    "last_spring_frost_doy": ("day of last spring frost", "день останнього весняного заморозку"),
    "first_fall_frost_doy": ("day of first fall frost", "день першого осіннього заморозку"),
    "frost_free_days": ("frost-free days", "безморозних днів"), "srad_grow": ("solar radiation", "сонячна радіація за сезон"),
    "rh_summer": ("summer air humidity", "літня вологість повітря"),
}

# SHAP contributions of several features are added up inside a group, so the farmer sees 5-7 reasons, not 50
GROUP_LABEL = {  # group -> (en, uk)
    "prev1": ("Last year's crop", "Попередник (що росло торік)"),
    "prev2": ("Crop two years ago", "Що росло позаторік"),
    "region": ("Region (where the field is)", "Регіон (де розташоване поле)"),
    "climate": ("Typical climate of the place", "Типовий клімат місця"),
    "weather_last": ("Last season's weather", "Погода торішнього сезону"),
    "soil": ("Soil", "Ґрунт"),
    "terrain": ("Terrain (slope)", "Рельєф (ухил)"),
}


def feature_group(name: str) -> str:
    if name == "prev_crop_1":
        return "prev1"
    if name == "prev_crop_2":
        return "prev2"
    if name in ("lat", "lon", "state_fips"):
        return "region"
    if name.startswith("norm_"):
        return "climate"
    if name.startswith("lag1_"):
        return "weather_last"
    if name in ("slope_pct", "twi"):
        return "terrain"
    return "soil"


def feature_plain(name: str, lang: str) -> str:
    i = 1 if lang == "uk" else 0
    base = name[5:] if name.startswith(("norm_", "lag1_")) else name
    text = BASE_DESC.get(base, (base, base))[i]
    return text


def crop_name(slug: str, lang: str) -> str:
    return CROP_NAMES.get(slug, (slug, slug))[1 if lang == "uk" else 0]
