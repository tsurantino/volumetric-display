import argparse
import socket
import struct
import time
import dataclasses
import math

# Configuration
ARTNET_IP = "192.168.1.11"  # Replace with your controller's IP
ARTNET_PORT = 6454  # Default ArtNet UDP port

# Universe and DMX settings
UNIVERSE = 0  # Universe ID
CHANNELS = 512  # Max DMX channels


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
                 universes_per_layer=6):
        """
        Send the ArtNet DMX packet via UDP.
        """
        # Send DMX Data Packet
        data = bytearray()
        for z in range(raster.length):
            universe = z * universes_per_layer + base_universe
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


@dataclasses.dataclass
class RGB:
    """
    Simple RGB color data class.
    """
    red: int
    green: int
    blue: int


@dataclasses.dataclass
class Raster:
    """
    Simple raster data class.
    """
    width: int
    height: int
    length: int
    brightness: float
    data: list[RGB]

    def __init__(self, width, height, length):
        self.width = width
        self.height = height
        self.length = length
        self.brightness = 1.0
        self.data = [RGB(0, 0, 0) for _ in range((width * height * length))]


def saturate_u8(value):
    """
    Saturate a value to the range [0, 255].
    """
    return int(max(0, min(value, 255)))


def main():
    parser = argparse.ArgumentParser(
        description="ArtNet DMX Transmission with Sync")
    parser.add_argument("--ip",
                        type=str,
                        default=ARTNET_IP,
                        help="ArtNet controller IP address")
    parser.add_argument("--port",
                        type=int,
                        default=ARTNET_PORT,
                        help="ArtNet controller port")
    parser.add_argument("--geometry",
                        type=str,
                        default="20x20x20",
                        help="Raster geometry (e.g., 20x20x20)")
    parser.add_argument("--brightness",
                        type=float,
                        default=0.05,
                        help="Brightness factor (0.0 to 1.0)")
    args = parser.parse_args()

    width, height, length = map(int, args.geometry.split("x"))

    raster = Raster(width=width, height=height, length=length)
    raster.brightness = args.brightness
    controller = ArtNetController(args.ip, args.port)

    t = 0

    print("🚀 Starting ArtNet DMX Transmission with Sync...")
    try:
        while True:
            controller.send_dmx(UNIVERSE, raster)
            time.sleep(0.01)  # Send updates at 100Hz

            # Draw a plane wave pattern
            t += 0.01 * 0.2
            for y in range(raster.height):
                for x in range(raster.width):
                    for z in range(raster.length):
                        # Calculate pixel index
                        idx = y * raster.width + x + z * raster.width * raster.height

                        # Calculate color
                        red = int(127 * math.sin(0.5 * math.sin(t * 5) * x +
                                                 z * 0.2 + t * 10) + 128)
                        green = int(127 * math.sin(0.5 * math.cos(t * 4) * y +
                                                   z * 0.2 + t * 10) + 128)
                        blue = int(127 * math.sin(0.5 * math.sin(t * 3) *
                                                  (x + y + z) + t * 10) + 128)

                        # Set pixel color
                        raster.data[idx] = RGB(red, green, blue)

    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")


if __name__ == "__main__":
    main()
