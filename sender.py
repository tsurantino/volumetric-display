import argparse
import time
import math
import json
from typing import List, Dict
from artnet import ArtNetController, Raster, RGB, Scene, load_scene

# Configuration
ARTNET_IP = "192.168.1.11"  # Replace with your controller's IP
ARTNET_PORT = 6454  # Default ArtNet UDP port

# Universe and DMX settings
UNIVERSE = 0  # Universe ID
CHANNELS = 512  # Max DMX channels

class DisplayConfig:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Parse geometry
        width, height, length = map(int, config['geometry'].split('x'))
        self.width = width
        self.height = height
        self.length = length
        
        # Parse z mapping
        self.z_mapping = []
        for mapping in config['z_mapping']:
            self.z_mapping.append({
                'ip': mapping['ip'],
                'z_indices': mapping['z_idx']
            })

def create_default_scene():
    """Creates a built-in default scene with the original wave pattern"""

    class WaveScene(Scene):

        def render(self, raster, time):
            for y in range(raster.height):
                for x in range(raster.width):
                    for z in range(raster.length):
                        # Calculate pixel index
                        idx = y * raster.width + x + z * raster.width * raster.height

                        # Calculate color
                        red = int(127 * math.sin(0.5 * math.sin(time * 5) * x +
                                                 z * 0.2 + time * 10) + 128)
                        green = int(127 * math.sin(0.5 * math.cos(time * 4) *
                                                   y + z * 0.2 + time * 10) +
                                    128)
                        blue = int(127 * math.sin(0.5 * math.sin(time * 3) *
                                                  (x + y + z) + time * 10) +
                                   128)

                        # Set pixel color
                        raster.data[idx] = RGB(red, green, blue)

    return WaveScene()


def main():
    parser = argparse.ArgumentParser(
        description="ArtNet DMX Transmission with Sync")
    parser.add_argument("--config",
                        type=str,
                        required=True,
                        help="Path to display configuration JSON file")
    parser.add_argument("--layer-span",
                        type=int,
                        default=1,
                        help="Layer span (1 for 1:1 mapping)")
    parser.add_argument("--brightness",
                        type=float,
                        default=0.05,
                        help="Brightness factor (0.0 to 1.0)")
    parser.add_argument("--scene",
                        type=str,
                        help="Path to a scene plugin file")
    args = parser.parse_args()

    # Load display configuration
    display_config = DisplayConfig(args.config)
    
    # Create raster with full geometry
    raster = Raster(width=display_config.width, 
                   height=display_config.height, 
                   length=display_config.length)
    raster.brightness = args.brightness

    # Create controllers for each IP
    controllers = {}
    for mapping in display_config.z_mapping:
        ip = mapping['ip']
        if ip not in controllers:
            controllers[ip] = ArtNetController(ip, ARTNET_PORT)

    # Load scene
    try:
        scene = load_scene(args.scene) if args.scene else create_default_scene()
    except (ImportError, ValueError) as e:
        print(f"Error loading scene: {e}")
        return

    start_time = time.time()
    print("🚀 Starting ArtNet DMX Transmission with Sync...")
    print(f"Using {len(controllers)} controllers for {display_config.length} z-slices")

    try:
        while True:
            current_time = time.time() - start_time

            # Update the raster using the scene
            scene.render(raster, current_time)

            # Send the updated raster
            for ip in controllers:
                controller = controllers[ip]
                mapping = display_config.z_mapping[ip]
                controller.send_dmx(UNIVERSE, raster, z_indices=mapping['z_indices'])
            time.sleep(0.01)  # Send updates at 100Hz

    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")


if __name__ == "__main__":
    main()
