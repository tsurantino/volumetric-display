from games.util.base_game import BaseGame, PlayerID, TeamID, RGB
from games.util.game_util import Button, ButtonState
import random
import math
import time
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Set


# Configuration mapping player roles to their team and view orientation
PLAYER_CONFIG = {
    PlayerID.BLUE_P1: {
        'team': TeamID.BLUE,
        'view': (1, 0, 0),  # -X view
        'left_dir': (0, 1, 0),  # -Y
        'right_dir': (0, -1, 0),  # +Y
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.BLUE_P2: {
        'team': TeamID.BLUE,
        'view': (0, 1, 0),  # -Y view
        'left_dir': (-1, 0, 0),  # +X
        'right_dir': (1, 0, 0), # -X
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.ORANGE_P1: {
        'team': TeamID.ORANGE,
        'view': (-1, 0, 0),   # +X view
        'left_dir': (0, -1, 0),  # +Y
        'right_dir': (0, 1, 0), # -Y
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.ORANGE_P2: {
        'team': TeamID.ORANGE,
        'view': (0, -1, 0),   # +Y view
        'left_dir': (1, 0, 0), # -X
        'right_dir': (-1, 0, 0),  # +X
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    }
}

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
    owner: PlayerID  # Which player fired this sphere
    bounce_count: int = 0  # How many times the sphere has bounced off a wall/floor/ceiling

    # Physics constants
    GRAVITY = 1000.0  # Gravity acceleration
    ELASTICITY = 0.95  # Bounce elasticity (1.0 = perfect bounce)
    AIR_DAMPING = 0.999  # Air resistance (velocity multiplier per update)
    GROUND_FRICTION = 0.95  # Additional friction when touching ground
    MINIMUM_SPEED = 0.01  # Speed below which we stop movement
    MAX_BOUNCES = 5  # Expire after this many bounces

    def update(self, dt: float, bounds: tuple[float, float, float]):
        # Apply gravity
        self.vz -= self.GRAVITY * dt

        # Apply air resistance
        self.vx *= self.AIR_DAMPING
        self.vy *= self.AIR_DAMPING
        self.vz *= self.AIR_DAMPING

        # Apply additional ground friction when touching bottom (z = 0 plane)
        if self.z - self.radius <= 0:
            self.vx *= self.GROUND_FRICTION
            self.vy *= self.GROUND_FRICTION

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
        bounced = False  # Track if we bounced this update
        if self.x - self.radius < 0:
            self.x = self.radius
            self.vx = abs(self.vx) * self.ELASTICITY
            bounced = True
        elif self.x + self.radius > width - 1:
            self.x = width - 1 - self.radius
            self.vx = -abs(self.vx) * self.ELASTICITY
            bounced = True

        if self.y - self.radius < 0:
            self.y = self.radius
            self.vy = abs(self.vy) * self.ELASTICITY
            bounced = True
        elif self.y + self.radius > height - 1:
            self.y = height - 1 - self.radius
            self.vy = -abs(self.vy) * self.ELASTICITY
            bounced = True

        if self.z - self.radius < 0:
            self.z = self.radius
            self.vz = abs(self.vz) * self.ELASTICITY
            bounced = True
        elif self.z + self.radius > length - 1:
            self.z = length - 1 - self.radius
            self.vz = -abs(self.vz) * self.ELASTICITY
            bounced = True

        # Increment bounce counter if we hit anything
        if bounced:
            self.bounce_count += 1

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
        # Expire after lifetime OR after too many bounces
        return (current_time - self.birth_time > self.lifetime) or (self.bounce_count >= self.MAX_BOUNCES)

@dataclass
class Cannon:
    x: float  # Position on the face
    y: float
    face: str  # Which face of the cube ('x', '-x', 'y', '-y')
    team: TeamID
    color: RGB
    owner: PlayerID
    select_hold_start: float = None  # When SELECT was pressed
    radius: float = 1.0
    charging: bool = False  # Whether the cannon is charging
    held_dirs: Set[Button] = field(default_factory=set)  # Directions currently held down
    draw_radius: float = 2.0  # Visual radius when rendering

# ------------------------
# Hoop representation
# ------------------------

@dataclass
class Hoop:
    """A moving hoop that sits on the floor (y == 0) and slowly drifts around."""
    x: float
    z: float
    radius: float
    color: RGB = field(default_factory=lambda: RGB(255, 255, 255))  # default white

class SphereShooterGame(BaseGame):
    def __init__(self, width=20, height=20, length=20, frameRate=30, config=None, input_handler=None):
        self.team_colors = {
            TeamID.BLUE: RGB(0, 0, 255),    # Blue team
            TeamID.ORANGE: RGB(255, 165, 0)  # Orange team
        }

        # Hoop parameters – must exist before BaseGame.__init__ triggers reset_game
        self.hoop_angle = 0.0
        hoop_radius = 3.0
        self.hoop = Hoop(width / 2, height / 2, hoop_radius)

        # Hoop motion state variables
        self.hoop_moving = False
        self.hoop_dwell_timer = random.uniform(1.0, 2.0)
        self.hoop_move_progress = 0.0

        # Call parent constructor (this invokes reset_game)
        super().__init__(width, height, length, frameRate, config, input_handler)

        # Player score map (reset_game will have created it; keep for clarity)
        if not hasattr(self, 'player_scores'):
            self.player_scores: Dict[PlayerID, int] = {pid: 0 for pid in PlayerID}

        self.last_update_time = time.monotonic()

    def reset_game(self):
        """Reset the game state."""
        self.spheres = []
        self.cannons = {}
        self.player_scores = {pid: 0 for pid in PlayerID}

        # Reset hoop
        self.hoop_angle = 0.0
        self.hoop.x = self.width / 2
        self.hoop.z = self.height / 2

        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}

        # Initialize cannons for each player
        for player_id in PlayerID:
            config = PLAYER_CONFIG[player_id]
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
                color=self.team_colors[team],
                owner=player_id
            )

        # Reset hoop motion state
        self.hoop_moving = False
        self.hoop_dwell_timer = random.uniform(1.0, 2.0)
        self.hoop_move_progress = 0.0

    def get_player_score(self, player_id):
        """Get the score for a player."""
        return self.player_scores.get(player_id, 0)

    def get_opponent_score(self, player_id):
        """Get the score for a player's opponent."""
        return max(score for pid, score in self.player_scores.items() if pid != player_id)

    def process_player_input(self, player_id, button, button_state):
        """Process input from a player."""
        if self.game_over_active or player_id not in self.cannons:
            return

        cannon = self.cannons[player_id]
        
        # Handle SELECT button (charging and firing)
        if button == Button.SELECT:
            if button_state == ButtonState.PRESSED:
                # Start charging when SELECT is pressed
                cannon.select_hold_start = time.monotonic()
                cannon.charging = True
            elif button_state == ButtonState.RELEASED and cannon.charging:
                # Fire the shot when SELECT is released
                if cannon.select_hold_start is not None:
                    charge_time = time.monotonic() - cannon.select_hold_start
                    self.launch_sphere(cannon, charge_time)
                # Reset charging state
                cannon.select_hold_start = None
                cannon.charging = False
            return
        
        # Track directional button holds
        if button in {Button.LEFT, Button.RIGHT, Button.UP, Button.DOWN}:
            if button_state == ButtonState.PRESSED:
                cannon.held_dirs.add(button)
            elif button_state == ButtonState.RELEASED:
                cannon.held_dirs.discard(button)

    def update_game_state(self):
        """Update the game state."""
        current_time = time.monotonic()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time

        # ---------- Move hoop with random smoothstep ----------
        if not hasattr(self, 'hoop_moving'):
            self.hoop_moving = False
            self.hoop_dwell_timer = random.uniform(1.0, 2.0)

        if not self.hoop_moving:
            # Waiting period before picking a new target
            self.hoop_dwell_timer -= dt
            if self.hoop_dwell_timer <= 0.0:
                # Pick new random target position on floor within bounds
                margin = self.hoop.radius + 1
                target_x = random.uniform(margin, self.width - margin)
                target_y = random.uniform(margin, self.height - margin)

                self.hoop_start_x = self.hoop.x
                self.hoop_start_y = self.hoop.z  # stored as z
                self.hoop_target_x = target_x
                self.hoop_target_y = target_y

                self.hoop_move_duration = random.uniform(2.0, 4.0)  # seconds to move
                self.hoop_move_progress = 0.0
                self.hoop_moving = True
        else:
            # Progress the move
            self.hoop_move_progress += dt / self.hoop_move_duration
            if self.hoop_move_progress >= 1.0:
                self.hoop_move_progress = 1.0
                self.hoop_moving = False
                self.hoop_dwell_timer = random.uniform(1.0, 2.0)

            # Smoothstep interpolation
            t = self.hoop_move_progress
            t_smooth = t * t * (3 - 2 * t)
            self.hoop.x = self.hoop_start_x + (self.hoop_target_x - self.hoop_start_x) * t_smooth
            self.hoop.z = self.hoop_start_y + (self.hoop_target_y - self.hoop_start_y) * t_smooth

        # ---------- Move cannons based on held directions ----------
        cannon_speed = 5.0  # voxels per second
        move_amt = cannon_speed * dt
        for cannon in self.cannons.values():
            # Movement in face plane
            if Button.LEFT in cannon.held_dirs:
                if cannon.face in ['x', '-y']:
                    cannon.x -= move_amt
                else:
                    cannon.x += move_amt
            if Button.RIGHT in cannon.held_dirs:
                if cannon.face in ['x', '-y']:
                    cannon.x += move_amt
                else:
                    cannon.x -= move_amt
            if Button.UP in cannon.held_dirs:
                cannon.y = min(self.length - 1 - cannon.radius, cannon.y + move_amt)
            if Button.DOWN in cannon.held_dirs:
                cannon.y = max(cannon.radius, cannon.y - move_amt)

            # Clamp within bounds of face
            cannon.x = max(cannon.radius, min(self.height - 1 - cannon.radius, cannon.x))

        # ---------- Update sphere physics, check scoring ----------
        bounds = (self.width, self.height, self.length)
        new_spheres = []

        for sphere in self.spheres:
            if sphere.is_expired(current_time):
                continue

            # Update physics
            sphere.update(dt, bounds)

            # Collision with other spheres
            for other in self.spheres:
                if sphere != other and not other.is_expired(current_time):
                    sphere.collide_with(other)

            # Check if sphere scores through hoop (on floor and within radius)
            if (sphere.z - sphere.radius) <= 0.5:
                dx = sphere.x - self.hoop.x
                dy = sphere.y - self.hoop.z  # treat hoop.z as y for floor plane
                if math.sqrt(dx * dx + dy * dy) <= self.hoop.radius:
                    # Score for owner
                    self.player_scores[sphere.owner] += 1
                    continue  # Do not keep this sphere

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
        base_speed = 50.0  # Base speed
        max_speed = 500.0   # Maximum speed
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
            radius=2.0,
            birth_time=time.monotonic(),
            lifetime=15.0,  # Spheres last 15 seconds
            color=cannon.color,
            team=cannon.team,
            mass=1.0,
            owner=cannon.owner
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
            # Calculate cannon color (include charging pulse as before)
            color = cannon.color
            if cannon.charging and cannon.select_hold_start:
                charge_time = time.monotonic() - cannon.select_hold_start
                charge_percentage = min(1.0, charge_time / 3.0)
                pulse_speed = 5 + charge_percentage * 15
                pulse = (math.sin(charge_time * pulse_speed) + 1) / 2
                brightness = 1.0 + charge_percentage * 1.5
                color = RGB(
                    min(255, int(color.red * brightness * (1 + pulse * 0.5))),
                    min(255, int(color.green * brightness * (1 + pulse * 0.5))),
                    min(255, int(color.blue * brightness * (1 + pulse * 0.5)))
                )

            # Draw cannon as filled circle on its face
            for u in range(-int(cannon.draw_radius), int(cannon.draw_radius) + 1):
                for v in range(-int(cannon.draw_radius), int(cannon.draw_radius) + 1):
                    if u*u + v*v > cannon.draw_radius * cannon.draw_radius:
                        continue
                    if cannon.face == 'x':
                        xx = self.width - 1
                        yy = int(cannon.x + u)
                        zz = int(cannon.y + v)
                        if 0 <= yy < self.height and 0 <= zz < self.length:
                            raster.set_pix(xx, yy, zz, color)
                    elif cannon.face == '-x':
                        xx = 0
                        yy = int(cannon.x + u)
                        zz = int(cannon.y + v)
                        if 0 <= yy < self.height and 0 <= zz < self.length:
                            raster.set_pix(xx, yy, zz, color)
                    elif cannon.face == 'y':
                        yy = self.height - 1
                        xx = int(cannon.x + u)
                        zz = int(cannon.y + v)
                        if 0 <= xx < self.width and 0 <= zz < self.length:
                            raster.set_pix(xx, yy, zz, color)
                    else:  # '-y'
                        yy = 0
                        xx = int(cannon.x + u)
                        zz = int(cannon.y + v)
                        if 0 <= xx < self.width and 0 <= zz < self.length:
                            raster.set_pix(xx, yy, zz, color)

        # Draw hoop (ring on floor y==0)
        ring_thickness = 0.5
        for xx in range(self.width):
            for yy in range(self.height):
                dx = xx + 0.5 - self.hoop.x
                dy = yy + 0.5 - self.hoop.z  # hoop.z stores y coordinate on floor plane
                dist = math.sqrt(dx*dx + dy*dy)
                if abs(dist - self.hoop.radius) <= ring_thickness:
                    raster.set_pix(xx, yy, 0, self.hoop.color)

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

    async def update_controller_display_state(self, controller_state, player_id):
        """Update the controller display for this player."""
        if self.game_over_active:
            # Use default game over display
            super().update_display(controller_state, player_id)
            return
            
        config = PLAYER_CONFIG[player_id]
        team_name = config['team'].name
        
        # Get the player's cannon
        cannon = self.cannons.get(player_id)

        controller_state.clear()
        
        if cannon and cannon.charging and cannon.select_hold_start:
            # Show charging animation when SELECT is held
            charge_time = time.monotonic() - cannon.select_hold_start
            charge_percent = min(int(charge_time / 3.0 * 100), 100)
            
            controller_state.write_lcd(0, 0, f"SPHERE SHOOTER")
            controller_state.write_lcd(0, 1, f"TEAM: {team_name}")
            
            # Create a charging progress bar
            charge_bar = ""
            bar_length = 18
            filled = int(charge_percent / 100 * bar_length)
            charge_bar = "[" + "#" * filled + "-" * (bar_length - filled) + "]"
            
            controller_state.write_lcd(0, 2, f"CHARGING: {charge_percent}%")
            controller_state.write_lcd(0, 3, charge_bar)
        else:
            # Regular game display
            my_score = self.get_player_score(player_id)
            opponent_score = self.get_opponent_score(player_id)
            
            controller_state.write_lcd(0, 0, "SPHERE SHOOTER")
            controller_state.write_lcd(0, 1, f"YOU: {my_score}")
            controller_state.write_lcd(0, 2, f"BEST OPP: {opponent_score}")
            controller_state.write_lcd(0, 3, "HOLD SELECT TO CHARGE") 

        await controller_state.commit()