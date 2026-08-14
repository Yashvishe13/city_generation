"""Create /Game/Maps/CityLevel and place the OSM city generator in it.

Run headless from the repo root:
    tools/ue_run.sh UnrealProject/Scripts/bootstrap_city_level.py

Idempotent: re-running replaces the level contents rather than stacking actors.
"""
import unreal

LEVEL_PATH = "/Game/Maps/CityLevel"
CITY_DATA_PATH = "Data/city.json"  # relative to <project>/Content


def _level_subsystem():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def make_level():
    ls = _level_subsystem()
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL_PATH):
        unreal.log(f"opening existing level {LEVEL_PATH}")
        ls.load_level(LEVEL_PATH)
    else:
        unreal.log(f"creating level {LEVEL_PATH}")
        ls.new_level(LEVEL_PATH)


def clear_actors():
    """Remove previously spawned generator/lighting so re-runs stay clean."""
    acts = _actor_subsystem()
    for actor in acts.get_all_level_actors():
        if actor.get_actor_label().startswith("CityGen_"):
            acts.destroy_actor(actor)


def spawn(cls, label, location=unreal.Vector(0, 0, 0), rotation=unreal.Rotator(0, 0, 0)):
    actor = _actor_subsystem().spawn_actor_from_class(cls, location, rotation)
    actor.set_actor_label(f"CityGen_{label}")
    return actor


def add_lighting():
    sun = spawn(unreal.DirectionalLight, "Sun", unreal.Vector(0, 0, 50000),
                unreal.Rotator(0, -50, 30))
    sun.light_component.set_intensity(6.0)

    spawn(unreal.SkyAtmosphere, "SkyAtmosphere")
    sky = spawn(unreal.SkyLight, "SkyLight", unreal.Vector(0, 0, 30000))
    sky.light_component.set_editor_property("real_time_capture", True)
    return sun


def add_generator():
    gen = spawn(unreal.OSMCityBuilder, "Generator")
    gen.set_editor_property("city_data_path", CITY_DATA_PATH)
    gen.set_editor_property("build_on_construction", True)
    gen.rebuild_city()
    unreal.log(f"generator summary: {gen.get_editor_property('last_build_summary')}")
    return gen


def main():
    make_level()
    clear_actors()
    add_lighting()
    add_generator()
    _level_subsystem().save_current_level()
    unreal.log("bootstrap_city_level: done")


main()
