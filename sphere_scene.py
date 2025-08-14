import math
import random
from dataclasses import dataclass
from typing import List

from artnet import HSV, RGB, Raster, Scene


@dataclass
class Sphere:
    x: float  # position
    y: float
    z: float
    vx: float  # velocity
    vy: float
    vz: float
    radius: float
    birth_time: float
    mass: float
    lifetime: float
    color: RGB

    # Physics constants
    GRAVITY = 20.0  # Gravity acceleration
    ELASTICITY = 0.95  # Bounce elasticity (1.0 = perfect bounce)
    AIR_DAMPING = 0.999  # Air resistance (velocity multiplier per update)
    GROUND_FRICTION = 0.95  # Additional friction when touching ground
    MINIMUM_SPEED = 0.01  # Speed below which we stop movement
    FADE_IN_OUT_TIME = 0.2  # Time to fade in and out

    def update(self, dt: float, bounds: tuple[float, float, float]):
        # Apply gravity
        self.vy -= self.GRAVITY * dt

        # Apply air resistance
        self.vx *= self.AIR_DAMPING
        self.vy *= self.AIR_DAMPING
        self.vz *= self.AIR_DAMPING

        # Apply additional ground friction when touching bottom
        if self.y - self.radius <= 0:
            self.vx *= self.GROUND_FRICTION
            self.vz *= self.GROUND_FRICTION

        # Stop very slow movement
        speed = math.sqrt(self.vx * self.vx + self.vy * self.vy + self.vz * self.vz)
        if speed < self.MINIMUM_SPEED:
            self.vx = 0
            self.vy = 0
            self.vz = 0

        # Update position
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        # Bounce off walls with energy loss
        width, height, length = bounds
        if self.x - self.radius < 0:
            self.x = self.radius
            self.vx = abs(self.vx) * self.ELASTICITY
        elif self.x + self.radius > width - 1:
            self.x = width - 1 - self.radius
            self.vx = -abs(self.vx) * self.ELASTICITY

        if self.y - self.radius < 0:
            self.y = self.radius
            self.vy = abs(self.vy) * self.ELASTICITY
        elif self.y + self.radius > height - 1:
            self.y = height - 1 - self.radius
            self.vy = -abs(self.vy) * self.ELASTICITY

        if self.z - self.radius < 0:
            self.z = self.radius
            self.vz = abs(self.vz) * self.ELASTICITY
        elif self.z + self.radius > length - 1:
            self.z = length - 1 - self.radius
            self.vz = -abs(self.vz) * self.ELASTICITY

    def collide_with(self, other: "Sphere"):
        """Handle elastic collision with another sphere"""
        # Calculate distance between sphere centers
        dx = other.x - self.x
        dy = other.y - self.y
        dz = other.z - self.z
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

        # Check if spheres are overlapping
        if distance < self.radius + other.radius:
            # Normal vector of the collision
            nx = dx / distance
            ny = dy / distance
            nz = dz / distance

            # Relative velocity
            rvx = other.vx - self.vx
            rvy = other.vy - self.vy
            rvz = other.vz - self.vz

            # Relative velocity along normal
            normal_vel = rvx * nx + rvy * ny + rvz * nz

            # Only collide if spheres are moving toward each other
            if normal_vel < 0:
                # Calculate the impulse scalar
                impulse = -(1 + self.ELASTICITY) * normal_vel / (1 / self.mass + 1 / other.mass)

                # Update velocities using conservation of momentum
                self.vx -= (impulse / self.mass) * nx
                self.vy -= (impulse / self.mass) * ny
                self.vz -= (impulse / self.mass) * nz
                other.vx += (impulse / other.mass) * nx
                other.vy += (impulse / other.mass) * ny
                other.vz += (impulse / other.mass) * nz

                # Separate spheres to prevent sticking
                overlap = (self.radius + other.radius - distance) / 2
                self.x -= nx * overlap
                self.y -= ny * overlap
                self.z -= nz * overlap
                other.x += nx * overlap
                other.y += ny * overlap
                other.z += nz * overlap

    def is_expired(self, current_time: float) -> bool:
        return current_time - self.birth_time > self.lifetime

    def get_current_radius(self, current_time: float) -> float:
        age = current_time - self.birth_time
        if age < self.FADE_IN_OUT_TIME:
            # Growing at the beginning
            return self.radius * age / self.FADE_IN_OUT_TIME
        elif age > self.lifetime - self.FADE_IN_OUT_TIME:
            # Shrinking at the end
            return self.radius * (self.lifetime - age) / self.FADE_IN_OUT_TIME
        return self.radius


class BouncingSphereScene(Scene):

    RENDER_FADE_MARGIN = 0.2  # Fade out near the edge

    def __init__(self, config: dict):
        """
        Initializes the scene using a configuration dictionary.

        Args:
            config (dict): A dictionary containing scene settings, including
                           the total width, height, and length of the
                           volumetric display space.
        """
        self.spheres: List[Sphere] = []
        self.next_spawn = 0.0
        self.spawn_interval = 2.0  # New sphere every 2 seconds

        # Read the total dimensions of the scene from the config
        self.width = config.get("width", 32)
        self.height = config.get("height", 32)
        self.length = config.get("length", 32)
        self.bounds = (self.width, self.height, self.length)

    def spawn_sphere(self, time: float) -> Sphere:
        """Spawns a new sphere within the scene's total bounds."""
        width, height, length = self.bounds
        radius = random.uniform(1.5, 3.0)

        # Random position (keeping sphere inside bounds)
        x = random.uniform(radius, width - radius)
        y = random.uniform(height / 2, height - radius)  # Start in upper half
        z = random.uniform(radius, length - radius)

        # Random initial velocity
        speed = random.uniform(8.0, 32.0)
        angle = random.uniform(0, 2 * math.pi)
        vx = speed * math.cos(angle)
        vy = random.uniform(8, 32.0)
        vz = speed * math.sin(angle)

        # Random color and mass
        color = RGB.from_hsv(HSV(random.randint(0, 255), 255, 255))
        mass = radius**3

        return Sphere(
            x=x,
            y=y,
            z=z,
            vx=vx,
            vy=vy,
            vz=vz,
            radius=radius,
            birth_time=time,
            lifetime=random.uniform(5.0, 30.0),
            color=color,
            mass=mass,
        )

    def render(self, raster: Raster, time: float):
        """
        Updates physics and renders spheres onto a single large raster.

        Args:
            raster (Raster): The single "world" raster to draw on.
            time (float): The current animation time.
        """
        # --- Setup ---
        dt = 0.01  # Smaller timestep for stable physics
        black = RGB(0, 0, 0)
        for i in range(len(raster.data)):
            raster.data[i] = black

        # --- Spawning ---
        if time >= self.next_spawn:
            self.spheres.append(self.spawn_sphere(time))
            self.next_spawn = time + self.spawn_interval

        # --- Physics Update ---
        # 1. Update positions and handle wall collisions
        for sphere in self.spheres:
            sphere.update(dt, self.bounds)

        # 2. Handle inter-sphere collisions
        for i, sphere1 in enumerate(self.spheres):
            for sphere2 in self.spheres[i + 1 :]:
                sphere1.collide_with(sphere2)

        # 3. Remove dead spheres
        self.spheres = [s for s in self.spheres if not s.is_expired(time)]

        # --- Rendering ---
        for sphere in self.spheres:
            current_radius = sphere.get_current_radius(time)
            if current_radius <= 0:
                continue

            # Bounding box for the sphere
            min_x = int(sphere.x - current_radius)
            max_x = int(sphere.x + current_radius + 1)
            min_y = int(sphere.y - current_radius)
            max_y = int(sphere.y + current_radius + 1)
            min_z = int(sphere.z - current_radius)
            max_z = int(sphere.z + current_radius + 1)

            # Iterate over the bounding box, clamped to the raster's dimensions
            for z in range(max(0, min_z), min(raster.length, max_z)):
                for y in range(max(0, min_y), min(raster.height, max_y)):
                    for x in range(max(0, min_x), min(raster.width, max_x)):
                        # Check if this voxel is inside the sphere's radius
                        distance_sq = (
                            (x - sphere.x) ** 2 + (y - sphere.y) ** 2 + (z - sphere.z) ** 2
                        )
                        if distance_sq > current_radius**2:
                            continue

                        # Simplified logic: just calculate index and draw
                        idx = z * raster.height * raster.width + y * raster.width + x

                        # Calculate light intensity for a soft-edge effect
                        distance = math.sqrt(distance_sq)
                        intensity_margin = current_radius * self.RENDER_FADE_MARGIN
                        if distance < current_radius - intensity_margin:
                            intensity = 1.0
                        else:
                            intensity = (
                                1.0
                                - (distance - (current_radius - intensity_margin))
                                / intensity_margin
                            )

                        # Blend with existing color using the max rule
                        existing = raster.data[idx]
                        raster.data[idx] = RGB(
                            max(existing.red, int(sphere.color.red * intensity)),
                            max(existing.green, int(sphere.color.green * intensity)),
                            max(existing.blue, int(sphere.color.blue * intensity)),
                        )
