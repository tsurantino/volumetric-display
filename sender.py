import argparse
import time
import math
import json
from typing import List, Dict, Tuple
from artnet import ArtNetController, Raster, RGB, Scene, load_scene, saturate_u8
import struct

# Constants
ARTNET_IP = "127.0.0.1"
ARTNET_PORT = 6454
UNIVERSE = 0
CHANNELS = 512

class DisplayConfig:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            config = json.load(f)

        self.cube_width, self.cube_height, self.cube_length = map(int, config['cube_geometry'].split('x'))
        self.orientation = config.get('orientation', ['X', 'Y', 'Z'])
        
        PIXELS_PER_UNIVERSE = 170
        pixels_per_layer = self.cube_width * self.cube_height
        universes_per_layer = (pixels_per_layer + PIXELS_PER_UNIVERSE - 1) // PIXELS_PER_UNIVERSE
        universes_per_cube = self.cube_length * universes_per_layer
        
        defaults = config.get("defaults", {})
        default_ip = defaults.get("ip", ARTNET_IP)
        default_port = defaults.get("port", ARTNET_PORT)
        
        # Process cube definitions, auto-generating the z_mapping if needed
        self.cubes = []
        for i, cube_def in enumerate(config["cubes"]):
            processed_cube = dict(cube_def)
            if "z_mapping" not in processed_cube:
                processed_cube["z_mapping"] = [
                    {
                        "ip": default_ip,
                        "port": default_port,
                        "base_universe": i * universes_per_cube,
                        "universes_per_layer": universes_per_layer,
                        "z_indices": list(range(self.cube_length))
                    }
                ]
            self.cubes.append(processed_cube)

        # --- End of new logic ---
        
        max_x = max(c['position'][0] for c in self.cubes)
        max_y = max(c['position'][1] for c in self.cubes)
        max_z = max(c['position'][2] for c in self.cubes)

        self.grid_width = max_x + 1
        self.grid_height = max_y + 1
        self.grid_length = max_z + 1

        self.total_width = self.grid_width * self.cube_width
        self.total_height = self.grid_height * self.cube_height
        self.total_length = self.grid_length * self.cube_length

class ArtNetRenderer:
    """Manages the entire rendering and sending pipeline."""
    def __init__(self, config_path: str, brightness: float = 1.0):
        self.config = DisplayConfig(config_path)
        
        self.main_raster = Raster(
            width=self.config.total_width,
            height=self.config.total_height,
            length=self.config.total_length
        )
        self.main_raster.brightness = brightness

        self.controllers = {}
        for cube in self.config.cubes:
            for mapping in cube['z_mapping']:
                ip = mapping['ip']
                port = mapping.get('port', ARTNET_PORT)
                if (ip, port) not in self.controllers:
                    self.controllers[(ip, port)] = ArtNetController(ip, port)
    
    def render_scene(self, scene: Scene, time: float):
        """Renders a scene to the main raster and sends the data."""
        scene.render(self.main_raster, time)

        packets_to_send = {addr: [] for addr in self.controllers.keys()}
        sync_packets = {}

        for cube_config in self.config.cubes:
            for mapping in cube_config['z_mapping']:
                addr = (mapping['ip'], mapping.get('port', ARTNET_PORT))
                controller = self.controllers[addr]
                
                # Directly compute DMX from the main_raster slice, no sub_raster needed
                packets, sync_packet = self.compute_dmx(controller, self.main_raster, cube_config['position'], mapping)
                
                packets_to_send[addr].extend(packets)
                sync_packets[addr] = sync_packet

        for addr, packets in packets_to_send.items():
            controller = self.controllers[addr]
            for pkt in packets:
                controller.sock.sendto(pkt, addr)
            if addr in sync_packets:
                controller.sock.sendto(sync_packets[addr], addr)

    def compute_dmx(self, controller: ArtNetController, main_raster: Raster, position: list[int], mapping: dict) -> Tuple[List[bytes], bytes]:
        """Computes and returns ArtNet packets by reading directly from a slice of the main raster."""
        packets: List[bytes] = []
        
        base_universe = mapping['base_universe']
        universes_per_layer = mapping['universes_per_layer']
        z_indices = mapping['z_indices']
        channels_per_universe = 510

        start_x_main = position[0] * self.config.cube_width
        start_y_main = position[1] * self.config.cube_height
        start_z_main = position[2] * self.config.cube_length

        for i, z_slice_local in enumerate(z_indices):
            start_universe_for_layer = base_universe + (i * universes_per_layer)
            
            layer_data = bytearray()
            
            # Iterate through the slice of the main raster for this layer
            z_main = start_z_main + z_slice_local
            for y_local in range(self.config.cube_height):
                y_main = start_y_main + y_local
                for x_local in range(self.config.cube_width):
                    x_main = start_x_main + x_local
                    
                    # This is faster than get_pix for this tight loop
                    idx = z_main * main_raster.width * main_raster.height + y_main * main_raster.width + x_main
                    rgb = main_raster.data[idx]

                    layer_data.extend(struct.pack('B', saturate_u8(rgb.red * main_raster.brightness)))
                    layer_data.extend(struct.pack('B', saturate_u8(rgb.green * main_raster.brightness)))
                    layer_data.extend(struct.pack('B', saturate_u8(rgb.blue * main_raster.brightness)))

            universe_offset = 0
            while len(layer_data) > 0:
                current_universe = start_universe_for_layer + universe_offset
                packet_data = layer_data[:channels_per_universe]
                dmx_packet = controller.create_dmx_packet(current_universe, packet_data)
                packets.append(dmx_packet)
                layer_data = layer_data[channels_per_universe:]
                universe_offset += 1

        sync_packet = controller.create_sync_packet()
        return packets, sync_packet

def create_default_scene():
    """Creates a built-in default scene with a wave pattern"""
    class WaveScene(Scene):
        def render(self, raster, time):
            for y in range(raster.height):
                for x in range(raster.width):
                    for z in range(raster.length):
                        red = int(127 * math.sin(0.5 * math.sin(time * 5) * x + z * 0.2 + time * 10) + 128)
                        green = int(127 * math.sin(0.5 * math.cos(time * 4) * y + z * 0.2 + time * 10) + 128)
                        blue = int(127 * math.sin(0.5 * math.sin(time * 3) * (x + y + z) + time * 10) + 128)
                        raster.set_pix(x, y, z, RGB(red, green, blue))
    return WaveScene()

def main():
    parser = argparse.ArgumentParser(description="ArtNet DMX Transmission with Sync")
    parser.add_argument("--config", type=str, required=True, help="Path to display configuration JSON file")
    parser.add_argument("--brightness", type=float, default=1.0, help="Brightness factor (0.0 to 1.0)")
    parser.add_argument("--scene", type=str, help="Path to a scene plugin file")
    args = parser.parse_args()

    renderer = ArtNetRenderer(args.config, args.brightness)

    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
        scene = load_scene(args.scene, config=config) if args.scene else create_default_scene()
    except (ImportError, ValueError) as e:
        print(f"Error loading scene: {e}")
        raise e

    start_time = time.monotonic()
    print("🚀 Starting ArtNet DMX Transmission with Sync...")

    try:
        while True:
            current_time = time.monotonic() - start_time
            renderer.render_scene(scene, current_time)
            time.sleep(1 / 60.0)
    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")

if __name__ == "__main__":
    main()