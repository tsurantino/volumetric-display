from artnet import Scene, RGB, Raster
import random
import math
from dataclasses import dataclass
from typing import List

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
    lifetime: float
    color: RGB

    def update(self, dt: float, bounds: tuple[float, float, float]):
        # Update position
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        # Bounce off walls
        width, height, length = bounds
        if self.x - self.radius < 0:
            self.x = self.radius
            self.vx = abs(self.vx)
        elif self.x + self.radius > width - 1:
            self.x = width - 1 - self.radius
            self.vx = -abs(self.vx)

        if self.y - self.radius < 0:
            self.y = self.radius
            self.vy = abs(self.vy)
        elif self.y + self.radius > height - 1:
            self.y = height - 1 - self.radius
            self.vy = -abs(self.vy)

        if self.z - self.radius < 0:
            self.z = self.radius
            self.vz = abs(self.vz)
        elif self.z + self.radius > length - 1:
            self.z = length - 1 - self.radius
            self.vz = -abs(self.vz)

    def is_expired(self, current_time: float) -> bool:
        return current_time - self.birth_time > self.lifetime

    def get_current_radius(self, current_time: float) -> float:
        age = current_time - self.birth_time
        if age > self.lifetime - 1.0:  # Start shrinking in the last second
            return self.radius * (1.0 - (age - (self.lifetime - 1.0)))
        return self.radius


class BouncingSphereScene(Scene):
    def __init__(self):
        self.spheres: List[Sphere] = []
        self.next_spawn = 0.0
        self.spawn_interval = 2.0  # New sphere every 2 seconds

    def spawn_sphere(self, time: float, bounds: tuple[float, float, float]) -> Sphere:
        width, height, length = bounds
        radius = random.uniform(1.5, 3.0)
        
        # Random position (keeping sphere inside bounds)
        x = random.uniform(radius, width - radius)
        y = random.uniform(radius, height - radius)
        z = random.uniform(radius, length - radius)
        
        # Random velocity
        speed = 5.0
        angle = random.uniform(0, 2 * math.pi)
        elevation = random.uniform(-math.pi/4, math.pi/4)
        
        vx = speed * math.cos(elevation) * math.cos(angle)
        vy = speed * math.cos(elevation) * math.sin(angle)
        vz = speed * math.sin(elevation)
        
        # Random color
        color = RGB(
            random.randint(100, 255),
            random.randint(100, 255),
            random.randint(100, 255)
        )
        
        return Sphere(
            x=x, y=y, z=z,
            vx=vx, vy=vy, vz=vz,
            radius=radius,
            birth_time=time,
            lifetime=random.uniform(5.0, 10.0),
            color=color
        )

    def render(self, raster: Raster, time: float):
        # Clear the raster
        for i in range(len(raster.data)):
            raster.data[i] = RGB(0, 0, 0)

        # Spawn new spheres
        if time >= self.next_spawn:
            self.spheres.append(self.spawn_sphere(
                time, (raster.width, raster.height, raster.length)))
            self.next_spawn = time + self.spawn_interval

        # Update and render spheres
        bounds = (raster.width, raster.height, raster.length)
        new_spheres = []

        for sphere in self.spheres:
            if not sphere.is_expired(time):
                sphere.update(0.1, bounds)  # Update physics
                
                # Get current radius (for shrinking effect)
                current_radius = sphere.get_current_radius(time)
                
                # Render sphere
                for x in range(max(0, int(sphere.x - current_radius)), 
                             min(raster.width, int(sphere.x + current_radius + 1))):
                    for y in range(max(0, int(sphere.y - current_radius)),
                                 min(raster.height, int(sphere.y + current_radius + 1))):
                        for z in range(max(0, int(sphere.z - current_radius)),
                                     min(raster.length, int(sphere.z + current_radius + 1))):
                            # Calculate distance from sphere center
                            dx = x - sphere.x
                            dy = y - sphere.y
                            dz = z - sphere.z
                            distance = math.sqrt(dx*dx + dy*dy + dz*dz)
                            
                            if distance <= current_radius:
                                # Calculate intensity based on distance from center
                                intensity = 1.0 - (distance / current_radius)
                                idx = y * raster.width + x + z * raster.width * raster.height
                                
                                # Blend with existing color
                                existing = raster.data[idx]
                                raster.data[idx] = RGB(
                                    max(existing.red, int(sphere.color.red * intensity)),
                                    max(existing.green, int(sphere.color.green * intensity)),
                                    max(existing.blue, int(sphere.color.blue * intensity))
                                )
                
                new_spheres.append(sphere)

        self.spheres = new_spheres

