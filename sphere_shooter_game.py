from base_game import BaseGame, PlayerID, TeamID, Difficulty, RGB
from game_util import Button
import random
import math
import time
from dataclasses import dataclass
from typing import List, Dict, Tuple

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
    team: TeamID  # Track which team shot this sphere

    # Physics constants
    GRAVITY = 20.0  # Gravity acceleration
    ELASTICITY = 0.95  # Bounce elasticity (1.0 = perfect bounce)
    AIR_DAMPING = 0.999  # Air resistance (velocity multiplier per update)
    GROUND_FRICTION = 0.95  # Additional friction when touching ground
    MINIMUM_SPEED = 0.01  # Speed below which we stop movement

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

    def collide_with(self, other: 'Sphere'):
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

@dataclass
class Cannon:
    x: float  # Position on the face
    y: float
    face: str  # Which face of the cube ('x', '-x', 'y', '-y')
    team: TeamID
    color: RGB
    select_hold_start: float = None  # When SELECT was pressed
    radius: float = 1.0

class SphereShooterGame(BaseGame):
    def __init__(self, width=20, height=20, length=20, frameRate=30, config=None, input_handler=None):
        self.team_colors = {
            TeamID.BLUE: RGB(0, 0, 255),    # Blue team
            TeamID.ORANGE: RGB(255, 165, 0)  # Orange team
        }
        super().__init__(width, height, length, frameRate, config, input_handler)
        self.spheres: List[Sphere] = []
        self.cannons: Dict[PlayerID, Cannon] = {}
        self.reset_game()

    def reset_game(self):
        """Reset the game state."""
        self.spheres = []
        self.cannons = {}
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}

        # Initialize cannons for each player
        for player_id in PlayerID:
            config = self.get_player_config(player_id)
            team = config['team']
            view = config['view']
            
            # Determine which face the cannon is on based on view direction
            if view[0] != 0:  # X view
                face = '-x' if view[0] < 0 else 'x'
                x = self.height // 2  # Position on face
                y = self.length // 2
            else:  # Y view
                face = '-y' if view[1] < 0 else 'y'
                x = self.width // 2
                y = self.length // 2

            self.cannons[player_id] = Cannon(
                x=x,
                y=y,
                face=face,
                team=team,
                color=self.team_colors[team]
            )

    def get_player_score(self, player_id):
        """Get the score for a player."""
        config = self.get_player_config(player_id)
        team = config['team']
        # Count spheres that are still in play
        return sum(1 for sphere in self.spheres if sphere.team == team)

    def get_opponent_score(self, player_id):
        """Get the score for a player's opponent."""
        config = self.get_player_config(player_id)
        team = config['team']
        opponent_team = TeamID.ORANGE if team == TeamID.BLUE else TeamID.BLUE
        return sum(1 for sphere in self.spheres if sphere.team == opponent_team)

    def process_player_input(self, player_id, action):
        """Process input from a player."""
        if self.game_over_active:
            return

        cannon = self.cannons[player_id]
        move_speed = 1.0

        # Handle movement
        if action == Button.UP:
            if cannon.face in ['x', '-x']:
                cannon.y = max(cannon.radius, min(self.length - 1 - cannon.radius, cannon.y - move_speed))
            else:  # 'y' or '-y' face
                cannon.y = max(cannon.radius, min(self.length - 1 - cannon.radius, cannon.y - move_speed))
        elif action == Button.DOWN:
            if cannon.face in ['x', '-x']:
                cannon.y = max(cannon.radius, min(self.length - 1 - cannon.radius, cannon.y + move_speed))
            else:  # 'y' or '-y' face
                cannon.y = max(cannon.radius, min(self.length - 1 - cannon.radius, cannon.y + move_speed))
        elif action == Button.LEFT:
            if cannon.face in ['x', '-x']:
                cannon.x = max(cannon.radius, min(self.height - 1 - cannon.radius, cannon.x - move_speed))
            else:  # 'y' or '-y' face
                cannon.x = max(cannon.radius, min(self.width - 1 - cannon.radius, cannon.x - move_speed))
        elif action == Button.RIGHT:
            if cannon.face in ['x', '-x']:
                cannon.x = max(cannon.radius, min(self.height - 1 - cannon.radius, cannon.x + move_speed))
            else:  # 'y' or '-y' face
                cannon.x = max(cannon.radius, min(self.width - 1 - cannon.radius, cannon.x + move_speed))
        elif action == Button.SELECT:
            # Start charging the shot
            if not cannon.select_hold_start:
                cannon.select_hold_start = time.monotonic()

    def update_game_state(self):
        """Update the game state."""
        current_time = time.monotonic()

        # Check for sphere launches (when SELECT is released)
        for player_id, cannon in self.cannons.items():
            if cannon.select_hold_start is not None:
                hold_duration = current_time - cannon.select_hold_start
                if hold_duration >= 3.0:  # Maximum charge time
                    self.launch_sphere(cannon, 3.0)
                    cannon.select_hold_start = None

        # Update sphere physics
        bounds = (self.width, self.height, self.length)
        dt = 0.01  # Small timestep for better physics
        new_spheres = []

        for sphere in self.spheres:
            if not sphere.is_expired(current_time):
                sphere.update(dt, bounds)

                # Check collisions with other spheres
                for other in self.spheres:
                    if sphere != other and not other.is_expired(current_time):
                        sphere.collide_with(other)

                new_spheres.append(sphere)

        self.spheres = new_spheres

        # Update game over flash state
        if self.game_over_active:
            if current_time - self.game_over_flash_state['timer'] >= self.game_over_flash_state['interval']:
                self.game_over_flash_state['timer'] = current_time
                self.game_over_flash_state['border_on'] = not self.game_over_flash_state['border_on']
                self.game_over_flash_state['count'] += 1

    def launch_sphere(self, cannon: Cannon, charge_time: float):
        """Launch a sphere from a cannon."""
        # Calculate velocity based on charge time (1-3 seconds)
        base_speed = 10.0  # Base speed
        max_speed = 30.0   # Maximum speed
        speed = base_speed + (max_speed - base_speed) * min(charge_time / 3.0, 1.0)

        # Set initial position based on cannon face
        if cannon.face == 'x':
            x = self.width - 1
            y = cannon.x
            z = cannon.y
            vx = -speed  # Shoot towards -x
            vy = 0
            vz = 0
        elif cannon.face == '-x':
            x = 0
            y = cannon.x
            z = cannon.y
            vx = speed   # Shoot towards +x
            vy = 0
            vz = 0
        elif cannon.face == 'y':
            x = cannon.x
            y = self.height - 1
            z = cannon.y
            vx = 0
            vy = -speed  # Shoot towards -y
            vz = 0
        else:  # '-y'
            x = cannon.x
            y = 0
            z = cannon.y
            vx = 0
            vy = speed   # Shoot towards +y
            vz = 0

        # Add some random spread
        spread = 2.0
        vx += random.uniform(-spread, spread)
        vy += random.uniform(-spread, spread)
        vz += random.uniform(-spread, spread)

        # Create the sphere
        sphere = Sphere(
            x=x, y=y, z=z,
            vx=vx, vy=vy, vz=vz,
            radius=1.0,
            birth_time=time.monotonic(),
            lifetime=30.0,  # Spheres last 30 seconds
            color=cannon.color,
            team=cannon.team,
            mass=1.0
        )
        self.spheres.append(sphere)

    def render_game_state(self, raster):
        """Render the game state to the raster."""
        # Draw spheres
        for sphere in self.spheres:
            # Determine the bounding box for the sphere
            min_x = math.floor(sphere.x - sphere.radius)
            max_x = math.ceil(sphere.x + sphere.radius)
            min_y = math.floor(sphere.y - sphere.radius)
            max_y = math.ceil(sphere.y + sphere.radius)
            min_z = math.floor(sphere.z - sphere.radius)
            max_z = math.ceil(sphere.z + sphere.radius)

            for vx in range(min_x, max_x + 1):
                for vy in range(min_y, max_y + 1):
                    for vz in range(min_z, max_z + 1):
                        # Voxel center
                        voxel_center_x = vx + 0.5
                        voxel_center_y = vy + 0.5
                        voxel_center_z = vz + 0.5

                        # Distance from voxel center to sphere center
                        dist_sq = (
                            (voxel_center_x - sphere.x)**2 +
                            (voxel_center_y - sphere.y)**2 +
                            (voxel_center_z - sphere.z)**2
                        )

                        if dist_sq <= sphere.radius**2:
                            if (0 <= vx < self.width and 
                                0 <= vy < self.height and 
                                0 <= vz < self.length):
                                raster.set_pix(vx, vy, vz, sphere.color)

        # Draw cannons
        for cannon in self.cannons.values():
            # Calculate cannon color based on charge
            color = cannon.color
            if cannon.select_hold_start:
                # Make cannon pulse while charging
                charge_time = time.monotonic() - cannon.select_hold_start
                pulse = (math.sin(charge_time * 10) + 1) / 2  # 0 to 1 pulsing
                color = RGB(
                    min(255, int(color.red * (1 + pulse))),
                    min(255, int(color.green * (1 + pulse))),
                    min(255, int(color.blue * (1 + pulse)))
                )

            # Draw cannon on its face
            x, y, z = int(cannon.x), int(cannon.y), 0
            if cannon.face == 'x':
                raster.set_pix(self.width - 1, x, y, color)
            elif cannon.face == '-x':
                raster.set_pix(0, x, y, color)
            elif cannon.face == 'y':
                raster.set_pix(x, self.height - 1, y, color)
            else:  # '-y'
                raster.set_pix(x, 0, y, color)

        # Draw game over border
        if self.game_over_active and self.game_over_flash_state['border_on']:
            border_color = RGB(255, 0, 0)  # Red border
            for x in range(self.width):
                for y in range(self.height):
                    for z in range(self.length):
                        if (x == 0 or x == self.width - 1 or
                            y == 0 or y == self.height - 1 or
                            z == 0 or z == self.length - 1):
                            raster.set_pix(x, y, z, border_color) 