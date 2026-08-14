"""Create /Game/Maps/CityLevel and populate it: lighting + the PCG city generator.

Run headless from the repo root:
    tools/ue_run.sh UnrealProject/Scripts/bootstrap_city_level.py

Idempotent: every actor it spawns is labelled `CityGen_*` and destroyed on re-run,
so the level never accumulates duplicates.

The PCG component is set to GenerateOnLoad: PCG generation is asynchronous and cannot
be flushed inside a commandlet, so the geometry appears when the level is opened (or
via Generate in the details panel). `AOSMCityBuilder` is the synchronous alternative
and can be placed with WITH_PREVIEW_BUILDER for a quick non-PCG check.
"""
import unreal

LEVEL_PATH = "/Game/Maps/CityLevel"
BP_PATH = "/Game/Blueprints/BP_CityGenerator"
GRAPH_PATH = "/Game/PCG/PCG_City"
CITY_DATA_PATH = "Data/city.json"  # relative to <project>/Content

# Also place the direct (non-PCG) builder. Off by default so the two paths do not
# generate overlapping copies of the same city.
WITH_PREVIEW_BUILDER = False


def _levels():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def make_level():
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL_PATH):
        unreal.log(f"opening existing level {LEVEL_PATH}")
        _levels().load_level(LEVEL_PATH)
    else:
        unreal.log(f"creating level {LEVEL_PATH}")
        _levels().new_level(LEVEL_PATH)


def clear_actors():
    for actor in _actors().get_all_level_actors():
        if actor.get_actor_label().startswith("CityGen_"):
            _actors().destroy_actor(actor)


def spawn(cls, label, location=unreal.Vector(0, 0, 0), rotation=unreal.Rotator(0, 0, 0)):
    actor = _actors().spawn_actor_from_class(cls, location, rotation)
    actor.set_actor_label(f"CityGen_{label}")
    return actor


def add_lighting():
    """Fully dynamic lighting - nothing to bake, no 'lighting needs rebuild' banner."""
    sun = spawn(unreal.DirectionalLight, "Sun", unreal.Vector(0, 0, 50000),
                unreal.Rotator(0, -50, 30))
    sun.light_component.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    sun.light_component.set_intensity(6.0)

    sky = spawn(unreal.SkyLight, "SkyLight", unreal.Vector(0, 0, 30000))
    sky.light_component.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    sky.light_component.set_editor_property("real_time_capture", True)

    spawn(unreal.SkyAtmosphere, "SkyAtmosphere")


def add_pcg_generator():
    """BP_CityGenerator (Actor + PCGComponent bound to PCG_City)."""
    bp_class = unreal.EditorAssetLibrary.load_blueprint_class(BP_PATH)
    actor = spawn(bp_class, "Generator")

    pcg = actor.get_component_by_class(unreal.PCGComponent)
    if pcg is None:
        raise RuntimeError("BP_CityGenerator has no PCGComponent")
    # ACityGeneratorActor's construction script generates on load, so opening the
    # level rebuilds the city. PCG generation is async and cannot complete inside a
    # commandlet, hence no attempt to verify counts here.
    actor.generate_city()
    unreal.log(f"placed {BP_PATH} with graph {GRAPH_PATH}; generation scheduled")
    return actor


def add_preview_builder():
    builder = spawn(unreal.OSMCityBuilder, "PreviewBuilder")
    builder.set_editor_property("city_data_path", CITY_DATA_PATH)
    builder.rebuild_city()
    unreal.log(f"preview builder: {builder.get_editor_property('last_build_summary')}")
    return builder


def main():
    make_level()
    clear_actors()
    add_lighting()
    add_pcg_generator()
    if WITH_PREVIEW_BUILDER:
        add_preview_builder()
    _levels().save_current_level()
    unreal.log("bootstrap_city_level: done")


main()
