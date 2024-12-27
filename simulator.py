import argparse
import socket
import struct
import numpy as np
import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
import threading


class VolumetricDisplay:

    def __init__(self,
                 width,
                 height,
                 length,
                 ip_address,
                 port,
                 universes_per_layer):
        self.width = width
        self.height = height
        self.length = length
        self.ip_address = ip_address

        # Track rotation key states
        self.rotation_keys = {
            pygame.K_LEFT: False,
            pygame.K_RIGHT: False,
            pygame.K_UP: False,
            pygame.K_DOWN: False
        }

        # Initialize 3D array to store RGB values
        self.pixels = np.zeros((width, height, length, 3), dtype=np.uint8)

        # Calculate number of universes needed per layer
        pixels_per_layer = width * height
        self.universes_per_layer = universes_per_layer
        if self.universes_per_layer > 10:
            raise ValueError("Layer size too large for ArtNet limitations")

        # ArtNet setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip_address, port))

        # Visualization setup
        pygame.init()
        pygame.display.set_mode((800, 600), DOUBLEBUF | OPENGL)

        # Setup perspective and lighting
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

        # Initialize rotation state
        self.rotation_matrix = np.identity(4, dtype=np.float32)

        # Start ArtNet listener thread
        self.running = True
        self.needs_update = False
        self.thread = threading.Thread(target=self._listen_artnet)
        self.thread.start()

    def _listen_artnet(self):
        while self.running:
            data, addr = self.sock.recvfrom(1024)

            # Check if it's an ArtNet packet
            if data[0:8] != b'Art-Net\0':
                continue

            opcode = struct.unpack('<H', data[8:10])[0]

            # Handle DMX data
            if opcode == 0x5000:  # OpDmx
                universe = struct.unpack('<H', data[14:16])[0]
                length = struct.unpack('>H', data[16:18])[0]
                dmx_data = data[18:18 + length]

                # Calculate which layer and section this universe belongs to
                layer = universe // self.universes_per_layer
                universe_in_layer = universe % self.universes_per_layer

                if layer >= self.length:
                    continue

                # Update pixel values
                start_pixel = universe_in_layer * 170
                for i in range(0, len(dmx_data), 3):  # Skip last 2 channels
                    pixel_index = start_pixel + (i // 3)
                    if pixel_index >= self.width * self.height:
                        break

                    x = pixel_index % self.width
                    y = pixel_index // self.width

                    self.pixels[x, y, layer] = [
                        dmx_data[i], dmx_data[i + 1], dmx_data[i + 2]
                    ]

            # Handle sync packet
            elif opcode == 0x5200:  # OpSync
                self.needs_update = True

    def render(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # Load identity matrix and apply our stored rotation
        glLoadIdentity()
        gluPerspective(45, (800 / 600), 0.1, 100.0)
        glTranslatef(0, 0, -max(self.width, self.height, self.length) * 2.5)
        glMultMatrixf(self.rotation_matrix)
        glTranslatef(-self.width / 2, -self.height / 2, -self.length / 2)

        # Draw coordinate axes for reference
        glBegin(GL_LINES)
        # X axis in red
        glColor3f(1, 0, 0)
        glVertex3f(0, 0, 0)
        glVertex3f(self.width, 0, 0)
        # Y axis in green
        glColor3f(0, 1, 0)
        glVertex3f(0, 0, 0)
        glVertex3f(0, self.height, 0)
        # Z axis in blue
        glColor3f(0, 0, 1)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 0, self.length)
        glEnd()

        # Draw each pixel as a colored cube
        for x in range(self.width):
            for y in range(self.height):
                for z in range(self.length):
                    color = self.pixels[x, y, z]
                    if any(color):  # Only draw if the color isn't black
                        self.draw_cube(x, y, z, color)

        pygame.display.flip()

    def draw_cube(self, x, y, z, color):
        """Helper method to draw a colored cube at given coordinates"""
        # Set emission to make colors more vibrant
        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION,
                     (color[0] / 255.0 * 1.0, color[1] / 255.0 * 1.0,
                      color[2] / 255.0 * 1.0, 1.0))
        #glColor3ub(color[0], color[1], color[2])
        glColor3ub(255, 255, 255)

        size = 0.2
        vertices = [
            # Front face
            [x - size, y - size, z + size],
            [x + size, y - size, z + size],
            [x + size, y + size, z + size],
            [x - size, y + size, z + size],
            # Back face
            [x - size, y - size, z - size],
            [x + size, y - size, z - size],
            [x + size, y + size, z - size],
            [x - size, y + size, z - size],
        ]

        faces = [
            [0, 1, 2, 3],  # Front
            [5, 4, 7, 6],  # Back
            [4, 0, 3, 7],  # Left
            [1, 5, 6, 2],  # Right
            [4, 5, 1, 0],  # Bottom
            [3, 2, 6, 7],  # Top
        ]

        glBegin(GL_QUADS)
        for face in faces:
            for vertex in face:
                glVertex3fv(vertices[vertex])
        glEnd()

    def rotate(self, angle, x, y, z):
        """Apply a rotation to our stored rotation matrix"""
        # Convert angle to radians
        angle = np.radians(angle)

        # Create rotation matrix
        c = np.cos(angle)
        s = np.sin(angle)
        rotation = np.identity(4, dtype=np.float32)

        if x:  # Rotate around X axis
            rotation = np.array(
                [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]],
                dtype=np.float32)
        elif y:  # Rotate around Y axis
            rotation = np.array(
                [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]],
                dtype=np.float32)
        elif z:  # Rotate around Z axis
            rotation = np.array(
                [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                dtype=np.float32)

        # Apply rotation to stored matrix
        self.rotation_matrix = np.matmul(self.rotation_matrix, rotation)

        # Renormalize the rotation matrix to prevent accumulation of numerical errors
        # Extract 3x3 rotation part
        rotation_3x3 = self.rotation_matrix[:3, :3]
        # Use SVD to orthogonalize
        u, _, vh = np.linalg.svd(rotation_3x3)
        rotation_3x3 = np.matmul(u, vh)
        # Put back into 4x4 matrix
        self.rotation_matrix[:3, :3] = rotation_3x3

    def run(self):
        """Main display loop"""
        clock = pygame.time.Clock()

        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key in self.rotation_keys:
                        self.rotation_keys[event.key] = True
                elif event.type == pygame.KEYUP:
                    if event.key in self.rotation_keys:
                        self.rotation_keys[event.key] = False

            # Handle continuous rotation
            if self.rotation_keys[pygame.K_LEFT]:
                self.rotate(5, 0, 1, 0)
            if self.rotation_keys[pygame.K_RIGHT]:
                self.rotate(-5, 0, 1, 0)
            if self.rotation_keys[pygame.K_UP]:
                self.rotate(5, 1, 0, 0)
            if self.rotation_keys[pygame.K_DOWN]:
                self.rotate(-5, 1, 0, 0)

            # Always render every frame
            self.render()
            clock.tick(60)

    def cleanup(self):
        """Cleanup resources"""
        self.running = False
        self.thread.join()
        self.sock.close()
        pygame.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--geometry',
                        type=str,
                        default="16x16x16",
                        help="Width, height, and length of the display")
    parser.add_argument('--ip',
                        type=str,
                        default="127.0.0.1",
                        help="IP address to listen for ArtNet packets")
    parser.add_argument('--port',
                        type=int,
                        default=6454,
                        help="Port to listen for ArtNet packets")
    parser.add_argument('--universes-per-layer',
                        type=int,
                        default=6,
                        help="Number of universes per layer")
    args = parser.parse_args()

    width, height, length = map(int, args.geometry.split('x'))

    # Example usage
    display = VolumetricDisplay(width, height, length, args.ip, args.port,
                                args.universes_per_layer)
    try:
        display.run()
    finally:
        display.cleanup()
