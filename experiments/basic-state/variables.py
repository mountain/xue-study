"""ERA5 field registry for the next experiment; the published wind500 v1 is frozen.

Names are logical/CDS-style names, NOT necessarily array keys in an ARCO store.
The complete collection list includes state, diagnostic and forcing channels.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class Field:
    code: str
    cds_variable: str
    units: str
    level_hpa: int | None = None
    role: str = "state"
    domain: str = "global"
    arco_variable: str | None = None

    @property
    def name(self) -> str:
        suffix = f"_{self.level_hpa}hPa" if self.level_hpa is not None else ""
        return self.cds_variable + suffix

    @property
    def arco_name(self) -> str:
        return self.arco_variable or self.cds_variable

    @property
    def is_radiation(self) -> bool:
        return self.code in {"tisr", "ssr", "str"}

    def record(self) -> dict:
        return {**asdict(self), "name": self.name, "arco_name": self.arco_name,
                "training_units": "W m-2" if self.is_radiation else self.units}


# One table generates both parallel lists, so names and codes cannot drift.
# u/v must enter a vector harmonic representation together, on each level.
FIELDS = (
    Field("t850", "temperature", "K", 850, domain="above_ground"),
    Field("t2m", "2m_temperature", "K"),
    Field("sst", "sea_surface_temperature", "K", domain="ocean"),
    Field("sp", "surface_pressure", "Pa"),
    Field("msl", "mean_sea_level_pressure", "Pa"),
    Field("z500", "geopotential", "m2 s-2", 500, domain="above_ground"),
    Field("q850", "specific_humidity", "kg kg-1", 850, domain="above_ground"),
    Field("q700", "specific_humidity", "kg kg-1", 700, domain="above_ground"),
    Field("u850", "u_component_of_wind", "m s-1", 850, domain="above_ground"),
    Field("v850", "v_component_of_wind", "m s-1", 850, domain="above_ground"),
    Field("u500", "u_component_of_wind", "m s-1", 500, domain="above_ground"),
    Field("v500", "v_component_of_wind", "m s-1", 500, domain="above_ground"),
    Field("u250", "u_component_of_wind", "m s-1", 250, domain="above_ground"),
    Field("v250", "v_component_of_wind", "m s-1", 250, domain="above_ground"),
    Field("w500", "vertical_velocity", "Pa s-1", 500, domain="above_ground"),
    Field("w700", "vertical_velocity", "Pa s-1", 700, domain="above_ground"),
    Field("ssr", "surface_net_solar_radiation", "J m-2"),
    Field("str", "surface_net_thermal_radiation", "J m-2"),
    Field("sd", "snow_depth", "m water equivalent", domain="land"),
    Field("tisr", "toa_incident_solar_radiation", "J m-2", role="forcing"),
    Field("z1000", "geopotential", "m2 s-2", 1000, "diagnostic", "above_ground"),
    Field("r850", "relative_humidity", "%", 850, "diagnostic", "above_ground"),
    Field("r700", "relative_humidity", "%", 700, "diagnostic", "above_ground"),
)
STATIC_FIELDS = (
    Field("lsm", "land_sea_mask", "1", role="static"),
    Field("zs", "geopotential", "m2 s-2", role="static",
          arco_variable="geopotential_at_surface"),
)
BY_CODE = {f.code: f for f in (*FIELDS, *STATIC_FIELDS)}
variables = [f.name for f in FIELDS]
codes = [f.code for f in FIELDS]
state_codes = [f.code for f in FIELDS if f.role == "state"]
forcing_codes = [f.code for f in FIELDS if f.role == "forcing"]
diagnostic_codes = [f.code for f in FIELDS if f.role == "diagnostic"]

# User's spelling remains an accepted logical name; actual CDS uses 2m_temperature.
ALIASES = {
    "2_metre_temperature": "t2m",
    "total_incoming_shortwave_radiation": "tisr",
}


def resolve(name_or_code: str) -> Field:
    code = ALIASES.get(name_or_code, name_or_code)
    if code in BY_CODE:
        return BY_CODE[code]
    for field in BY_CODE.values():
        if field.name == name_or_code:
            return field
    raise KeyError(name_or_code)


def radiation_to_flux(values, *, product: str):
    """J/m² -> W/m² for these explicitly identified ERA5 products only.

    Cadence is NOT accumulation duration. No default for arbitrary/6-hour data.
    Preserve the ECMWF downward-positive sign, including negative net longwave.
    """
    seconds = {"era5_hourly_reanalysis": 3600,
               "era5_monthly_averaged_reanalysis": 86400}
    if product not in seconds:
        raise ValueError("Unverified radiation accumulation period: " + product)
    return values / seconds[product]


def domain_mask(field: Field, *, surface_pressure=None, land_sea_mask=None):
    """Array/scalar applicability mask on an already aligned grid and time.

    It must be intersected with finite-data flags. A monthly mean sp mask is
    only a monthly screening, not proof that every hourly sample is above ground.
    The 0.5 coastline threshold defines this first experiment's analysis domain;
    sd is intentionally restricted to land, omitting snow on sea ice.
    """
    if field.domain == "above_ground":
        if surface_pressure is None:
            raise ValueError(f"{field.code} requires surface pressure in Pa")
        return surface_pressure >= 100 * field.level_hpa
    if field.domain in {"ocean", "land"}:
        if land_sea_mask is None:
            raise ValueError(f"{field.code} requires a land-sea mask")
        return (land_sea_mask < 0.5 if field.domain == "ocean"
                else land_sea_mask >= 0.5)
    return True


def cds_monthly_requests(year: int, months: list[int]) -> list[dict]:
    """Unsubmitted one-year request plan, grouped to avoid unwanted level pairs."""
    if not 1940 <= year <= 9999 or not months or any(m < 1 or m > 12 for m in months):
        raise ValueError("Invalid year/month selection")
    common = {"product_type": ["monthly_averaged_reanalysis"],
              "year": [str(year)], "month": [f"{m:02d}" for m in sorted(set(months))],
              "time": ["00:00"], "data_format": "netcdf", "download_format": "unarchived"}
    # The full-month product is selected; 00:00 is its request label, not a
    # restriction to observations taken at midnight.
    singles = sorted({f.cds_variable for f in FIELDS if f.level_hpa is None})
    result = [{"dataset": "reanalysis-era5-single-levels-monthly-means",
               "request": {**common, "variable": singles}}]
    groups: dict[str, list[int]] = {}
    for f in FIELDS:
        if f.level_hpa is not None:
            groups.setdefault(f.cds_variable, []).append(f.level_hpa)
    for name, levels in sorted(groups.items()):
        result.append({"dataset": "reanalysis-era5-pressure-levels-monthly-means",
                       "request": {**common, "variable": [name],
                                   "pressure_level": [str(x) for x in sorted(set(levels))]}})
    return result


if __name__ == "__main__":
    print(json.dumps({"version": "basic-state-v1", "status": "configuration_only",
                      "fields": [f.record() for f in FIELDS],
                      "static_fields": [f.record() for f in STATIC_FIELDS]}, indent=2))
