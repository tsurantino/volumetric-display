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


def create_artnet_dmx_packet(universe, data):
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
    packet.extend(struct.pack('!H',
                              len(data)))  # Length of DMX data (big endian)

    # DMX Data
    packet.extend(data)  # Append DMX data

    return packet


def create_artnet_sync_packet():
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
    brightness: float
    data: list[RGB]

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.brightness = 1.0
        self.data = [RGB(0, 0, 0) for _ in range((width * height))]

def saturate_u8(value):
    """
    Saturate a value to the range [0, 255].
    """
    return int(max(0, min(value, 255)))

def send_artnet_packet(ip,
                       port,
                       base_universe,
                       raster,
                       channels_per_universe=510):
    """
    Send the ArtNet DMX packet via UDP.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Send DMX Data Packet
        universe_offset = 0
        data = bytearray()
        for rgb in raster.data:
            data.extend(struct.pack('B', saturate_u8(rgb.red * raster.brightness)))
            data.extend(struct.pack('B', saturate_u8(rgb.green * raster.brightness)))
            data.extend(struct.pack('B', saturate_u8(rgb.blue * raster.brightness)))

        while len(data) > 0:
            dmx_packet = create_artnet_dmx_packet(
                base_universe + universe_offset, data[:channels_per_universe])
            sock.sendto(dmx_packet, (ip, port))
            data = data[channels_per_universe:]
            universe_offset += 1

        # Send Sync Packet
        sync_packet = create_artnet_sync_packet()
        sock.sendto(sync_packet, (ip, port))


def main():
    raster = Raster(width=20, height=20)
    raster.brightness = 0.05

    t = 0

    print("🚀 Starting ArtNet DMX Transmission with Sync...")
    try:
        while True:
            send_artnet_packet(ARTNET_IP, ARTNET_PORT, UNIVERSE, raster)
            time.sleep(0.01)  # Send updates at 100Hz

            # Draw a plane wave pattern
            t += 0.01 * 0.2
            for y in range(raster.height):
                for x in range(raster.width):
                    # Calculate pixel index
                    idx = y * raster.width + x

                    # Calculate color
                    red = int(127 * math.sin(0.5 * math.sin(t * 5) * x + t * 10) + 128)
                    green = int(127 * math.sin(0.5 * math.cos(t * 4) * y + t * 10) + 128)
                    blue = int(127 * math.sin(0.5 * math.sin(t * 3) * (x + y) + t * 10) + 128)

                    # Set pixel color
                    raster.data[idx] = RGB(red, green, blue)

    except KeyboardInterrupt:
        print("\n🛑 Transmission stopped by user.")


if __name__ == "__main__":
    main()
