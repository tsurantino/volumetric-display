from abc import ABC, abstractmethod
import dataclasses
import importlib.util
import os.path
import socket
import struct
import time
import sys

@dataclasses.dataclass
class RGB:
    red: int
    green: int
    blue: int

    @staticmethod
    def from_hsv(hsv):
        h, s, v = hsv.hue / 255.0 * 6, hsv.saturation / 255.0, hsv.value / 255.0
        c = v * s
        x = c * (1 - abs((h % 2) - 1))
        m = v - c
        if 0 <= h < 1: r, g, b = c, x, 0
        elif 1 <= h < 2: r, g, b = x, c, 0
        elif 2 <= h < 3: r, g, b = 0, c, x
        elif 3 <= h < 4: r, g, b = 0, x, c
        elif 4 <= h < 5: r, g, b = x, 0, c
        else: r, g, b = c, 0, x
        return RGB(int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))

@dataclasses.dataclass
class HSV:
    hue: int
    saturation: int
    value: int

@dataclasses.dataclass
class Raster:
    width: int
    height: int
    length: int
    brightness: float = 1.0
    data: list[RGB] = dataclasses.field(init=False)

    def __post_init__(self):
        self.data = [RGB(0, 0, 0) for _ in range(self.width * self.height * self.length)]

    def set_pix(self, x, y, z, color):
        if 0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length:
            idx = z * self.width * self.height + y * self.width + x
            self.data[idx] = color

    def get_pix(self, x, y, z):
        if 0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length:
            idx = z * self.width * self.height + y * self.width + x
            return self.data[idx]
        return RGB(0, 0, 0)

    def clear(self):
        self.data = [RGB(0, 0, 0) for _ in range(self.width * self.height * self.length)]

def saturate_u8(value):
    return int(max(0, min(value, 255)))

class Scene(ABC):
    @abstractmethod
    def render(self, raster: Raster, time: float) -> None:
        pass


def load_scene(path: str, config=None) -> Scene:
    """
    Load a scene plugin from a Python file

    Args:
        path: Path to the Python file containing the scene
        config: Optional configuration to pass to the scene constructor

    Returns:
        An instance of the scene class

    Raises:
        ImportError: If the scene cannot be loaded
        ValueError: If the scene doesn't contain exactly one Scene subclass
    """
    # Get absolute path
    path = os.path.abspath(path)
    scene_dir = os.path.dirname(path)

    # Store original sys.path and add scene directory
    original_sys_path = list(sys.path)
    if scene_dir not in sys.path:
        sys.path.insert(0, scene_dir)

    try:
        # Load module
        spec = importlib.util.spec_from_file_location("scene_module", path)
        if not spec or not spec.loader:
            raise ImportError(f"Could not load scene from {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find Scene subclass
        scene_classes = [
            cls for cls in module.__dict__.values()
            if isinstance(cls, type) and issubclass(cls, Scene) and cls != Scene
        ]

        if not scene_classes:
            raise ValueError(f"No Scene subclass found in {path}")
        if len(scene_classes) > 1:
            raise ValueError(f"Multiple Scene subclasses found in {path}")

        # Create and return instance
        return scene_classes[0](config=config)

    finally:
        # Restore original sys.path
        sys.path = original_sys_path


class ArtNetController:

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def __del__(self):
        self.sock.close()

    def create_dmx_packet(self, universe, data):
        """
        Manually construct an ArtNet DMX packet.
        """
        packet = bytearray()

        # ArtNet Header
        packet.extend(b'Art-Net\x00')  # Protocol header
        packet.extend(struct.pack('<H', 0x5000))  # OpCode for DMX (0x5000)
        packet.extend(struct.pack('!H',
                                  14))  # Protocol version (0x000E, big-endian)
        packet.extend(struct.pack('B', 0))  # Sequence (0 = disabled)
        packet.extend(struct.pack('B', 0))  # Physical port (0 = ignored)
        packet.extend(struct.pack('<H', universe))  # Universe (little endian)
        packet.extend(struct.pack(
            '!H', len(data)))  # Length of DMX data (big endian)

        # DMX Data
        packet.extend(data)  # Append DMX data

        return packet

    def create_sync_packet(self):
        """
        Manually construct an ArtNet Sync packet.
        """
        packet = bytearray()

        # ArtNet Header
        packet.extend(b'Art-Net\x00')  # Protocol header
        packet.extend(struct.pack('<H', 0x5200))  # OpCode for Sync (0x5200)
        packet.extend(struct.pack('!H',
                                  14))  # Protocol version (0x000E, big-endian)
        packet.extend(struct.pack('B', 0))  # Sequence (ignored)
        packet.extend(struct.pack('B', 0))  # Physical port (ignored)

        return packet

    def send_dmx(self,
                 base_universe,
                 raster,
                 channels_per_universe=510,
                 universes_per_layer=3,
                 channel_span=1,
                 z_indices=None):
        """
        Send the ArtNet DMX packet via UDP.
        """
        # Send DMX Data Packet
        data = bytearray()
        if z_indices is None:
            z_indices = range(0, raster.length, channel_span)

        for out_z, z in enumerate(z_indices):
            universe = (out_z //
                        channel_span) * universes_per_layer + base_universe
            layer = raster.data[z * raster.width * raster.height:(z + 1) *
                                raster.width * raster.height]

            for rgb in layer:
                data.extend(
                    struct.pack('B', saturate_u8(rgb.red * raster.brightness)))
                data.extend(
                    struct.pack('B',
                                saturate_u8(rgb.green * raster.brightness)))
                data.extend(
                    struct.pack('B',
                                saturate_u8(rgb.blue * raster.brightness)))

            while len(data) > 0:
                dmx_packet = self.create_dmx_packet(
                    universe, data[:channels_per_universe])
                self.sock.sendto(dmx_packet, (self.ip, self.port))
                data = data[channels_per_universe:]
                universe += 1

        # Send Sync Packet
        sync_packet = self.create_sync_packet()
        self.sock.sendto(sync_packet, (self.ip, self.port))
        