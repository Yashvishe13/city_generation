"""Top-down screenshot of the generated city, for the report's side-by-side.

Run through the GUI editor, not a commandlet: PCG generation is asynchronous and a
`-run=pythonscript` commandlet exits before it finishes, and `-NullRHI` has nothing to
capture anyway. So this is invoked with -ExecCmds on a normal editor launch, after the
map has loaded and BP_CityGenerator's construction script has scheduled generation.

    tools/ue_shot.sh [area]

Writes <project>/Saved/Screenshots/overhead_ue.png.
"""
import unreal

SHOT_PX = 4096
# Shoot high and crop, rather than framing tight. A perspective viewport seen from 330 m
# over a 600 m area leans every tower outward from the centre, which cannot be laid beside
# a north-up map. From 1200 m the same area subtends a quarter of the frame and reads
# nearly orthographic; tools/crop_overhead.py then cuts out exactly the requested bbox.
#
# The editor viewport renders at ~90 deg FOV and set_level_viewport_camera_info does not
# change it, so visible half-width on the ground equals the camera height. Measured, not
# assumed: at Z = 1200 m the frame covered ~2.4 km.
CAMERA_Z_CM = 120000.0


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
               f"camera {CAMERA_Z_CM / 100:.0f} m up, frame ~{2 * CAMERA_Z_CM / 100:.0f} m "
               f"wide at {SHOT_PX} px")

    # Straight down: pitch -90. Yaw 0 keeps +X (North) pointing up the frame, so the
    # image reads the same way as a north-up map - the whole point of the axis choice.
    location = unreal.Vector(centre[0], centre[1], CAMERA_Z_CM)
    rotation = unreal.Rotator(0.0, -90.0, 0.0)
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(location, rotation)

    unreal.AutomationLibrary.take_high_res_screenshot(
        SHOT_PX, SHOT_PX, "overhead_ue.png")
    unreal.log("[overhead] screenshot requested -> Saved/Screenshots/overhead_ue.png")


main()
