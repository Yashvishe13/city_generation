"""Top-down screenshot of the generated city, for the report's side-by-side.

Run through the GUI editor, not a commandlet: PCG generation is asynchronous and a
`-run=pythonscript` commandlet exits before it finishes, and `-NullRHI` has nothing to
capture anyway. So this is invoked with -ExecCmds on a normal editor launch, after the
map has loaded and BP_CityGenerator's construction script has scheduled generation.

    tools/ue_shot.sh [area]

Writes <project>/Saved/Screenshots/overhead_ue.png.
"""
import unreal

SHOT_PX = 2048
# Frame the REQUESTED area, not the scene bounds: the scene currently overruns its bbox,
# and a shot framed on the overrun buries the area under empty ground slab.
FRAME_HALF_M = 330.0
# The editor viewport renders at ~90 deg FOV, and setting camera info does not change it,
# so visible half-width on the ground is approximately the camera height. Measured, not
# assumed: at Z = 1200 m the frame covered ~2.4 km.
CAMERA_Z_CM = FRAME_HALF_M * 100.0


def _scene_centre_and_extent():
    """Centre and half-extent of everything the generator spawned, in cm."""
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    box_min = [1e12, 1e12]
    box_max = [-1e12, -1e12]
    found = False
    for actor in actors:
        name = actor.get_name()
        if "CityGenerator" not in name and "OSMCity" not in name:
            continue
        origin, extent = actor.get_actor_bounds(only_colliding_components=False)
        if extent.x <= 1.0 and extent.y <= 1.0:
            continue
        found = True
        box_min[0] = min(box_min[0], origin.x - extent.x)
        box_min[1] = min(box_min[1], origin.y - extent.y)
        box_max[0] = max(box_max[0], origin.x + extent.x)
        box_max[1] = max(box_max[1], origin.y + extent.y)
    if not found:
        unreal.log_warning("[overhead] no generator bounds found; falling back to origin")
        return (0.0, 0.0), 40000.0
    centre = ((box_min[0] + box_max[0]) / 2.0, (box_min[1] + box_max[1]) / 2.0)
    half = max(box_max[0] - box_min[0], box_max[1] - box_min[1]) / 2.0
    return centre, half


def main():
    centre, half = _scene_centre_and_extent()
    unreal.log(f"[overhead] centre={centre} scene_half_cm={half:.0f} "
               f"framing {FRAME_HALF_M:.0f} m half-width")

    # Straight down: pitch -90. Yaw 0 keeps +X (North) pointing up the frame, so the
    # image reads the same way as a north-up map - the whole point of the axis choice.
    location = unreal.Vector(centre[0], centre[1], CAMERA_Z_CM)
    rotation = unreal.Rotator(0.0, -90.0, 0.0)
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(location, rotation)

    unreal.AutomationLibrary.take_high_res_screenshot(
        SHOT_PX, SHOT_PX, "overhead_ue.png")
    unreal.log("[overhead] screenshot requested -> Saved/Screenshots/overhead_ue.png")


main()
