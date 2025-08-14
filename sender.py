import argparse
import json
import math
import time
from typing import Tuple

from artnet import RGB, ArtNetController, Raster, Scene, load_scene


class DisplayConfig:
    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            config = json.load(f)

        # Parse defaults
        self.default_ip = config["defaults"]["ip"]
        self.default_port = config["defaults"]["port"]

        # Parse cube geometry
        width, height, length = map(int, config["cube_geometry"].split("x"))
        self.width = width
        self.height = height
        self.length = length

        # Parse cubes
        self.cubes = []
        for i, cube_config in enumerate(config["cubes"]):
            self.cubes.append(
                {
                    "position": cube_config["position"],
                    "ip": self.default_ip,
                    "port": self.default_port + i,
                }
            )

        # Parse orientation
        self.orientation = config.get("orientation", ["X", "Y", "Z"])
        self._validate_orientation()
        self._compute_transform()

    def _validate_orientation(self):
        """Validate that orientation contains valid coordinate mappings."""
        valid_coords = {"X", "Y", "Z", "-X", "-Y", "-Z"}
        if len(self.orientation) != 3:
            raise ValueError("Orientation must specify exactly 3 coordinates")
        if not all(coord in valid_coords for coord in self.orientation):
            raise ValueError(f"Invalid coordinate in orientation. Must be one of: {valid_coords}")
        # Extract just the axis letters and check for uniqueness
        axes = [coord[-1] for coord in self.orientation]
        if len(set(axes)) != 3:
            raise ValueError("Each coordinate axis must appear exactly once in orientation")

    def _compute_transform(self):
        """Compute the transformation matrix for coordinate mapping."""
        self.transform = []
        for coord in self.orientation:
            axis = coord[-1]  # Get the axis (X, Y, or Z)
            sign = -1 if coord.startswith("-") else 1
            if axis == "X":
                self.transform.append((0, sign))
            elif axis == "Y":
                self.transform.append((1, sign))
            else:  # Z
                self.transform.append((2, sign))

    def transform_coordinates(self, x: int, y: int, z: int) -> Tuple[int, int, int]:
        """Transform coordinates according to the orientation configuration."""
        coords = [x, y, z]
        result = [0, 0, 0]
        for i, (axis, sign) in enumerate(self.transform):
            result[i] = coords[axis] * sign
        return tuple(result)


def create_default_scene():
    """Creates a built-in default scene with the original wave pattern"""

    class WaveScene(Scene):
        def __init__(self, config=None):
            pass  # No config needed for this simple scene

        def render(self, raster, time):
            for y in range(raster.height):
                for x in range(raster.width):
                    for z in range(raster.length):
                        # Calculate color
                        red = int(
                            127 * math.sin(0.5 * math.sin(time * 5) * x + z * 0.2 + time * 10) + 128
                        )
                        green = int(127 * math.cos((time * 4) * y + z * 0.2 + time * 10) + 128)
                        blue = int(
                            127 * math.sin(0.5 * math.sin(time * 3) * (x + y + z) + time * 10) + 128
                        )

                        # Set pixel color using set_pix
                        raster.set_pix(x, y, z, RGB(red, green, blue))

    return WaveScene()


def main():
    parser = argparse.ArgumentParser(description="ArtNet DMX Transmission with Sync")
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to display configuration JSON file",
    )
    parser.add_argument("--layer-span", type=int, default=1, help="Layer span (1 for 1:1 mapping)")
    parser.add_argument(
        "--brightness", type=float, default=0.05, help="Brightness factor (0.0 to 1.0)"
    )
    parser.add_argument("--scene", type=str, help="Path to a scene plugin file")
    args = parser.parse_args()

    # 1. Load display configuration from JSON
    display_config = DisplayConfig(args.config)
    if not display_config.cubes:
        raise ValueError("Configuration must contain at least one cube.")

    # 2. Calculate the total bounding box to create one large "world" raster
    all_x = [c["position"][0] for c in display_config.cubes]
    all_y = [c["position"][1] for c in display_config.cubes]
    all_z = [c["position"][2] for c in display_config.cubes]

    min_coord = (min(all_x), min(all_y), min(all_z))

    max_coord_x = max(c["position"][0] + display_config.width for c in display_config.cubes)
    max_coord_y = max(c["position"][1] + display_config.height for c in display_config.cubes)
    max_coord_z = max(c["position"][2] + display_config.length for c in display_config.cubes)

    world_width = max_coord_x - min_coord[0]
    world_height = max_coord_y - min_coord[1]
    world_length = max_coord_z - min_coord[2]

    # This is the single, large canvas that all scenes will draw on
    world_raster = Raster(world_width, world_height, world_length)
    world_raster.brightness = args.brightness

    # 3. Set up handlers for each physical display
    physical_displays = []
    for cube_config in display_config.cubes:
        physical_displays.append(
            {
                "config": cube_config,
                "controller": ArtNetController(cube_config["ip"], cube_config["port"]),
                "raster": Raster(
                    display_config.width, display_config.height, display_config.length
                ),
            }
        )

    # 4. Load the scene plugin
    try:
        # Pass the world dimensions to the scene so it knows the size of its canvas
        scene_config = {
            "width": world_width,
            "height": world_height,
            "length": world_length,
        }
        scene = (
            load_scene(args.scene, config=scene_config) if args.scene else create_default_scene()
        )
    except (ImportError, ValueError) as e:
        print(f"Error loading scene: {e}")
        raise e

    # 5. Start the main render loop
    start_time = time.monotonic()
    print("🚀 Starting ArtNet Transmission (Single Raster Mode)...")
    print(f"World Raster Dimensions: {world_width}x{world_height}x{world_length}")
    print(f"Managing {len(physical_displays)} physical cubes.")

    try:
        while True:
            current_time = time.monotonic() - start_time

            # A. SCENE RENDER: The active scene draws on the single large world_raster.
            scene.render(world_raster, current_time)

            # B. SLICE & SEND: Slice the world_raster and send data to each physical display.
            for display in physical_displays:
                # Top-left-front corner of this cube within the world_raster
                start_x = display["config"]["position"][0] - min_coord[0]
                start_y = display["config"]["position"][1] - min_coord[1]
                start_z = display["config"]["position"][2] - min_coord[2]

                cube_raster = display["raster"]

                # Copy the relevant "slice" from the world_raster to this cube's own raster
                for z in range(display_config.length):
                    for y in range(display_config.height):
                        for x in range(display_config.width):
                            # Source coordinate in the large world raster
                            world_x, world_y, world_z = start_x + x, start_y + y, start_z + z

                            # Correct 3D to 1D index calculation: (z * area) + (y * width) + x
                            source_idx = (
                                (world_z * world_height * world_width)
                                + (world_y * world_width)
                                + world_x
                            )
                            dest_idx = (
                                (z * display_config.height * display_config.width)
                                + (y * display_config.width)
                                + x
                            )

                            if 0 <= source_idx < len(world_raster.data):
                                cube_raster.data[dest_idx] = world_raster.data[source_idx]

                # Send the prepared data for this cube
                display["controller"].send_dmx(
                    base_universe=0,
                    raster=cube_raster,
                    channels_per_universe=510,
                    universes_per_layer=6,
                    channel_span=1,
                    z_indices=list(range(display_config.length)),
                )

            time.sleep(1 / 30.0)  # Send updates at 30Hz

    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")


if __name__ == "__main__":
    main()
