import argparse
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


class DisplayConfig:
    """Configuration for the volumetric display."""

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

        self.orientation = config.get("orientation", "xyz")

        # Validate dimensions
        if not all(d > 0 for d in [self.width, self.height, self.length]):
            raise ValueError("Display dimensions must be positive integers")


def create_controllers_from_config(config_path: str) -> dict:
    """Create ArtNet controllers based on the configuration file."""
    with open(config_path, "r") as f:
        config = json.load(f)

    controllers = {}
    controller_mappings = []

    # Extract controller mappings from config (using z_mapping field)
    mappings = config.get("z_mapping", [])
    for mapping in mappings:
        ip = mapping["ip"]
        port = mapping["port"]
        if ip not in controllers:
            controllers[ip] = ArtNetController(ip, port)
        controller_mappings.append((controllers[ip], mapping))

    return controllers, controller_mappings


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
    parser.add_argument(
        "--layer-span", type=int, default=1, help="Number of layers to skip between universes"
    )
    parser.add_argument(
        "--web-monitor-port", type=int, default=WEB_MONITOR_PORT, help="Web monitor port"
    )

    args = parser.parse_args()

    # Load display configuration from JSON
    display_config = DisplayConfig(args.config)
    if not display_config.cubes:
        raise ValueError("Configuration must contain at least one cube.")

    # Start control port manager for web monitoring if available
    control_port_manager = None
    if CONTROL_PORT_AVAILABLE:
        try:
            control_port_manager = create_control_port_from_config(
                args.config, args.web_monitor_port
            )
            print(
                f"🌐 Control port manager started with web monitoring on port {args.web_monitor_port}"
            )
        except Exception as e:
            print(f"Warning: Failed to start control port manager: {e}")
            print("Continuing without web monitoring...")

    # Create raster with full geometry (including expanding across multiple cubes)
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

    # Create the structured properties object
    display_props = DisplayProperties(
        width=world_width,
        height=world_height,
        length=world_length,
    )

    # Set up handlers for each physical display
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

    # Load and run the scene
    try:
        # Pass the world dimensions to the scene so it knows the size of its canvas
        scene = (
            load_scene(
                args.scene, properties=display_props, control_port_manager=control_port_manager
            )
            if args.scene
            else create_default_scene()
        )

        print("🚀 Starting ArtNet Transmission (Single Raster Mode)...")
        print(f"🎬 Playing scene: {args.scene}")
        print(f"🧊 Managing {len(physical_displays)} physical cubes.")
        print(f"📐 World raster dimensions: {world_width}x{world_height}x{world_length}")
        print(f"💡 Brightness: {args.brightness}")
        print(f"🔗 Layer span: {args.layer_span}")

        # Show game controller information if available
        if (
            hasattr(scene, "input_handler")
            and scene.input_handler
            and scene.input_handler.initialized
        ):
            game_controllers = len(scene.input_handler.controllers)
            print(f"🎮 Connected {game_controllers} game controllers for player input")

        # Create controllers from config
        controllers, controller_mappings = create_controllers_from_config(args.config)
        print(f"🎛️  Found {len(controllers)} ArtNet controllers for LED output")

        # Main rendering and transmission loop
        print("🔁 Starting main loop...")
        start_time = time.time()

        while True:
            current_time = time.time() - start_time

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
                    universes_per_layer=3,
                    channel_span=1,
                    z_indices=list(range(display_config.length)),
                )

            time.sleep(1 / 30.0)  # Send updates at 30Hz

    except (ImportError, ValueError) as e:
        print(f"Error loading scene: {e}")
        raise e
    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")
    except Exception as e:
        print(f"\n❌ Error in main loop: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Clean up scene and controller input handler first
        if "scene" in locals() and hasattr(scene, "input_handler") and scene.input_handler:
            try:
                print("🛑 Stopping controller input handler...")
                scene.input_handler.stop()
                print("✅ Controller input handler stopped")
            except Exception as e:
                print(f"Warning: Error stopping controller input handler: {e}")

        # Clean up control port manager only when the entire program is exiting
        if control_port_manager:
            try:
                control_port_manager.shutdown()
                print("🌐 Control port manager stopped")
            except Exception as e:
                print(f"Error stopping control port manager: {e}")


if __name__ == "__main__":
    main()
