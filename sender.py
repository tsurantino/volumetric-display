import argparse
import dataclasses
import json
import math
import time

from artnet import RGB, ArtNetController, DisplayProperties, Raster, Scene, load_scene

# Try to use Rust-based control port for web monitoring
try:
    from control_port_rust import create_control_port_from_config

    CONTROL_PORT_AVAILABLE = True
    print("Using Rust-based control port with web monitoring")
except ImportError:
    CONTROL_PORT_AVAILABLE = False
    print("Control port not available - web monitoring disabled")

# Config (ARTNET IP & PORT are handled via sim_config updates and specified there)
WEB_MONITOR_PORT = 8080  # Port for web monitoring interface
UNIVERSE = 0  # Universe ID
CHANNELS = 512  # Max DMX channels


class ArtNetManager:
    """Manages ArtNet controllers and data mappings based on a config file."""

    def __init__(self, config: dict):
        if "cubes" not in config or not config["cubes"]:
            raise ValueError("Configuration must contain at least one cube.")

        self.config = config
        self.cubes = config["cubes"]

        # Parse cube geometry
        self.width, self.height, self.length = map(int, config["cube_geometry"].split("x"))

        # These will be populated by _initialize_mappings
        self.controllers_cache = {}
        self.send_jobs = []

        self._initialize_mappings()

    def _initialize_mappings(self):
        """Parses the config to create ArtNet controllers and send jobs."""
        print("🎛️  Initializing ArtNet mappings...")

        # Create a unique raster buffer for each physical cube
        cube_rasters = {
            tuple(cube_config["position"]): Raster(self.width, self.height, self.length)
            for cube_config in self.cubes
        }

        for cube_config in self.cubes:
            position_tuple = tuple(cube_config["position"])

            for mapping in cube_config.get("artnet_mappings", []):
                ip = mapping["ip"]
                port = int(mapping["port"])
                controller_key = (ip, port)

                # Create a controller for the IP/Port if it doesn't exist
                if controller_key not in self.controllers_cache:
                    self.controllers_cache[controller_key] = ArtNetController(ip, port)

                # A "send job" is a dictionary with everything needed to send one packet
                self.send_jobs.append(
                    {
                        "controller": self.controllers_cache[controller_key],
                        "cube_raster": cube_rasters[position_tuple],
                        "cube_position": cube_config["position"],
                        "z_indices": mapping["z_idx"],
                        "universe": mapping.get("universe", 0),
                    }
                )

        print(
            f"✅ Found {len(self.cubes)} cubes and created {len(self.send_jobs)} send jobs "
            f"across {len(self.controllers_cache)} unique controllers."
        )


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
    parser = argparse.ArgumentParser(description="Send ArtNet DMX data to volumetric display")
    parser.add_argument("--config", required=True, help="Path to display configuration JSON")
    parser.add_argument("--scene", required=True, help="Path to scene Python file")
    parser.add_argument(
        "--brightness", type=float, default=1.0, help="Brightness multiplier (0.0-1.0)"
    )
    parser.add_argument("--web-monitor-port", type=int, default=8080, help="Web monitor port")
    args = parser.parse_args()

    # --- Configuration Loading and Setup ---
    with open(args.config, "r") as f:
        config = json.load(f)

    artnet_manager = ArtNetManager(config)

    # --- Start Control Port ---
    control_port_manager = None
    if CONTROL_PORT_AVAILABLE:
        try:
            control_port_manager = create_control_port_from_config(
                args.config, args.web_monitor_port
            )
            print(f"🌐 Control port manager started on port {args.web_monitor_port}")
        except Exception as e:
            print(f"Warning: Failed to start control port manager: {e}")

    # --- World Raster Setup (Single Canvas for Scene) ---
    all_x = [c["position"][0] for c in artnet_manager.cubes]
    all_y = [c["position"][1] for c in artnet_manager.cubes]
    all_z = [c["position"][2] for c in artnet_manager.cubes]
    min_coord = (min(all_x), min(all_y), min(all_z))

    max_coord_x = max(c["position"][0] + artnet_manager.width for c in artnet_manager.cubes)
    max_coord_y = max(c["position"][1] + artnet_manager.height for c in artnet_manager.cubes)
    max_coord_z = max(c["position"][2] + artnet_manager.length for c in artnet_manager.cubes)

    world_width = max_coord_x - min_coord[0]
    world_height = max_coord_y - min_coord[1]
    world_length = max_coord_z - min_coord[2]

    world_raster = Raster(world_width, world_height, world_length)
    world_raster.brightness = args.brightness
    display_props = DisplayProperties(width=world_width, height=world_height, length=world_length)

    # --- Scene Loading ---
    try:
        scene = (
            load_scene(
                args.scene, properties=display_props, control_port_manager=control_port_manager
            )
            if args.scene
            else create_default_scene()
        )

        print("\n🚀 Starting ArtNet Transmission...")
        print(f"🎬 Playing scene: {args.scene}")
        print(f"📐 World raster dimensions: {world_width}x{world_height}x{world_length}")
        print(f"💡 Brightness: {args.brightness}")

        if (
            hasattr(scene, "input_handler")
            and scene.input_handler
            and scene.input_handler.initialized
        ):
            print(f"🎮 Connected {len(scene.input_handler.controllers)} game controllers")

        # --- Main Rendering and Transmission Loop ---
        print("🔁 Starting main loop...")
        start_time = time.monotonic()
        while True:
            current_time = time.monotonic() - start_time

            # A. SCENE RENDER: The active scene draws on the single large world_raster.
            scene.render(world_raster, current_time)

            # B. SLICE: Copy data from the world raster to each cube's individual raster.
            processed_cubes = set()
            for job in artnet_manager.send_jobs:
                cube_pos_tuple = tuple(job["cube_position"])

                # This check ensures we only slice a cube's data once per frame,
                # even if it has multiple ArtNet mappings.
                if (
                    not hasattr(job["cube_raster"], "frame_sliced")
                    or job["cube_raster"].frame_sliced != current_time
                ):
                    start_x = job["cube_position"][0] - min_coord[0]
                    start_y = job["cube_position"][1] - min_coord[1]
                    start_z = job["cube_position"][2] - min_coord[2]

                    # Get a reference to the destination raster for clarity
                    cube_raster = job["cube_raster"]

                    world_slice = world_raster.data[
                        start_z : start_z + cube_raster.length,
                        start_y : start_y + cube_raster.height,
                        start_x : start_x + cube_raster.width,
                    ]
                    cube_raster.data[:] = world_slice

                    processed_cubes.add(cube_pos_tuple)

            # C. SEND: Iterate through all jobs and send the specified Z-layers.
            for job in artnet_manager.send_jobs:
                # Get the original raster with its NumPy data
                cube_raster = job["cube_raster"]
                temp_raster = dataclasses.replace(cube_raster)

                # Convert the NumPy array into the Python list of RGB objects
                # that the Rust library expects.
                numpy_data = cube_raster.data.reshape(-1, 3)  # Flatten to (num_pixels, 3)
                temp_raster.data = [RGB(int(r), int(g), int(b)) for r, g, b in numpy_data]

                universes_per_layer = 3
                base_universe_offset = min(job["z_indices"]) * universes_per_layer

                job["controller"].send_dmx(
                    base_universe=base_universe_offset,
                    raster=temp_raster,
                    z_indices=job["z_indices"],
                    # --- These params can be customized if needed ---
                    channels_per_universe=510,
                    universes_per_layer=universes_per_layer,
                    channel_span=1,
                )

            time.sleep(1 / 30.0)  # Target 30Hz

    except (ImportError, ValueError) as e:
        print(f"Error loading scene: {e}")
        raise
    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")
    except Exception as e:
        import traceback

        print(f"\n❌ Error in main loop: {e}")
        traceback.print_exc()
    finally:
        # Cleanup
        if "scene" in locals() and hasattr(scene, "input_handler") and scene.input_handler:
            scene.input_handler.stop()
            print("🛑 Controller input handler stopped.")
        if control_port_manager:
            control_port_manager.shutdown()
            print("🌐 Control port manager stopped.")


if __name__ == "__main__":
    main()
