"""osm2pcg - OpenStreetMap -> Unreal Engine PCG translation pipeline.

Stages: fetch (Overpass) -> parse (tags/heights) -> project (tmerc, cm)
-> export (JSON + CSV DataTables consumed by the PCG graph).
"""

__version__ = "0.1.0"
