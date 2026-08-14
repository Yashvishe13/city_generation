"""Area + tuning config for the OSM -> PCG pipeline."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

# Overpass mirrors, tried in order.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# Metres per storey when only building:levels is tagged.
METRES_PER_LEVEL = 3.2
# Height used when a building has no height/levels tag at all.
DEFAULT_HEIGHT_M = 12.0

# Fallback heights (metres) by building tag value, used when untagged.
HEIGHT_BY_BUILDING_TYPE = {
    "house": 7.0,
    "detached": 7.0,
    "bungalow": 4.5,
    "garage": 3.0,
    "garages": 3.0,
    "shed": 3.0,
    "hut": 3.0,
    "roof": 3.5,
    "carport": 3.0,
    "kiosk": 3.5,
    "retail": 8.0,
    "commercial": 20.0,
    "office": 30.0,
    "industrial": 10.0,
    "warehouse": 10.0,
    "apartments": 18.0,
    "residential": 12.0,
    "hotel": 30.0,
    "church": 15.0,
    "cathedral": 30.0,
    "school": 10.0,
    "university": 18.0,
    "hospital": 22.0,
    "civic": 15.0,
    "public": 15.0,
    "train_station": 12.0,
    "parking": 10.0,
}

# Road half-widths (metres) per highway class -> drives the road ribbon mesh.
ROAD_WIDTH_M = {
    "motorway": 16.0,
    "motorway_link": 8.0,
    "trunk": 14.0,
    "trunk_link": 7.0,
    "primary": 12.0,
    "primary_link": 6.0,
    "secondary": 10.0,
    "secondary_link": 6.0,
    "tertiary": 9.0,
    "tertiary_link": 5.0,
    "residential": 8.0,
    "unclassified": 7.0,
    "living_street": 6.0,
    "service": 5.0,
    "pedestrian": 5.0,
    "footway": 2.0,
    "path": 2.0,
    "cycleway": 2.5,
    "steps": 2.0,
    "track": 3.0,
}

# Highway classes we import. Footways/paths are off by default (noise).
ROAD_CLASSES = [
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "residential", "unclassified",
    "living_street", "service", "pedestrian",
]


@dataclass
class AreaConfig:
    """A named bounding box to reconstruct.

    Bounds are WGS84 degrees. Origin defaults to the bbox centre and becomes
    UE world (0,0). UE axis convention: +X = North, +Y = East, +Z = Up, cm.
    """

    name: str
    south: float
    west: float
    north: float
    east: float
    note: str = ""
    road_classes: list[str] = field(default_factory=lambda: list(ROAD_CLASSES))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.south, self.west, self.north, self.east)

    @property
    def origin(self) -> tuple[float, float]:
        """(lat, lon) of the local origin -> UE (0,0)."""
        return ((self.south + self.north) / 2.0, (self.west + self.east) / 2.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["origin_lat"], d["origin_lon"] = self.origin
        return d


# Preset areas. Keep them small: a few blocks to a district.
AREAS: dict[str, AreaConfig] = {
    # ~1.0 x 0.8 km. Dense, excellent height tagging, unmistakable skyline.
    "midtown": AreaConfig(
        name="midtown",
        south=40.7480, west=-73.9895, north=40.7560, east=-73.9790,
        note="Midtown Manhattan, NYC - Empire State Building / Bryant Park block grid",
    ),
    # Smaller smoke-test area (~450 x 350 m) for fast iteration.
    "midtown_small": AreaConfig(
        name="midtown_small",
        south=40.7500, west=-73.9860, north=40.7532, east=-73.9810,
        note="Small Midtown slice for quick pipeline iteration",
    ),
    "loop": AreaConfig(
        name="loop",
        south=41.8760, west=-87.6360, north=41.8850, east=-87.6230,
        note="Chicago Loop - tight grid, tall towers",
    ),
}

DEFAULT_AREA = "midtown"
