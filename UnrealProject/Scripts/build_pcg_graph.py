"""Author the PCG assets: /Game/PCG/PCG_City and /Game/Blueprints/BP_CityGenerator.

Graph shape:

    OSM City Source ──Buildings──► Spawn Dynamic Mesh (buildings)
                    ──Roads─────► Spawn Dynamic Mesh (roads)
                    ──Ground────► Spawn Dynamic Mesh (ground)
                    ──RoadSplines► (left unconnected: available for spline meshes)

BP_CityGenerator is an Actor with a PCGComponent whose graph is PCG_City.

Run:  tools/ue_run.sh UnrealProject/Scripts/build_pcg_graph.py
Re-running rebuilds both assets from scratch, so the graph never accumulates nodes.
"""
import unreal

GRAPH_PACKAGE = "/Game/PCG"
GRAPH_NAME = "PCG_City"
GRAPH_PATH = f"{GRAPH_PACKAGE}/{GRAPH_NAME}"

BP_PACKAGE = "/Game/Blueprints"
BP_NAME = "BP_CityGenerator"
BP_PATH = f"{BP_PACKAGE}/{BP_NAME}"

CITY_DATA_PATH = "Data/city.json"  # relative to <project>/Content

IN_PIN = "In"  # PCGPinConstants::DefaultInputLabel
MESH_PINS = ("Buildings", "Roads", "Ground")

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()


def recreate_asset(package, name, factory):
    path = f"{package}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    asset = asset_tools.create_asset(name, package, None, factory)
    if asset is None:
        raise RuntimeError(f"could not create {path}")
    return asset


def build_graph():
    graph = recreate_asset(GRAPH_PACKAGE, GRAPH_NAME, unreal.PCGGraphFactory())

    src_node, src_settings = graph.add_node_of_type(unreal.PCGOSMCitySettings)
    src_settings.set_editor_property("city_data_path", CITY_DATA_PATH)

    for index, pin in enumerate(MESH_PINS):
        spawn_node, _ = graph.add_node_of_type(unreal.PCGSpawnDynamicMeshSettings)
        graph.add_edge(src_node, pin, spawn_node, IN_PIN)
        # Lay the graph out so it is readable when a reviewer opens it.
        spawn_node.set_node_position(600, index * 220)

    src_node.set_node_position(0, 220)

    unreal.EditorAssetLibrary.save_loaded_asset(graph)
    unreal.log(f"built PCG graph {GRAPH_PATH}")
    return graph


def build_blueprint(graph):
    """BP_CityGenerator: ACityGeneratorActor subclass with CityGraph = PCG_City.

    The C++ parent already owns the PCGComponent and triggers generation from its
    construction script, so the Blueprint only has to carry the graph reference.
    """
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.CityGeneratorActor)
    bp = recreate_asset(BP_PACKAGE, BP_NAME, factory)

    defaults = unreal.get_default_object(bp.generated_class())
    defaults.set_editor_property("city_graph", graph)
    defaults.set_editor_property("generate_on_construction", True)

    unreal.EditorAssetLibrary.save_loaded_asset(bp)
    unreal.log(f"built {BP_PATH} (ACityGeneratorActor) bound to {GRAPH_PATH}")
    return bp


def main():
    graph = build_graph()
    try:
        build_blueprint(graph)
    except Exception as exc:  # noqa: BLE001 - report and let the level script fall back
        unreal.log_warning(f"BP_CityGenerator authoring failed ({exc}); "
                           "the level script will place a plain actor + PCGComponent")
    unreal.log("build_pcg_graph: done")


main()
