from artnet import Scene, RGB, HSV
import math
import pygame
from pygame.locals import *
from enum import Enum
import random
import asyncio
import threading
import control_port # Assuming control_port.py is in the same directory or PYTHONPATH
from collections import deque # Import deque
import time

white = RGB(255, 255, 255)
red = RGB(255, 0, 0)
blue = RGB(0, 0, 255)
green = RGB(0, 255, 0)
black = RGB(0, 0, 0)
orange = RGB(255, 165, 0)

digit_map = {
    '0': [(0,4), (1,4), (2,4), (0,3), (2,3), (0,2), (2,2), (0,1), (2,1), (0,0), (1,0), (2,0)],
    '1': [(1,4), (1,3), (1,2), (1,1), (1,0)],
    '2': [(0,4), (1,4), (2,4), (2,3), (0,2), (1,2), (2,2), (0,1), (0,0), (1,0), (2,0)],
    '3': [(0,4), (1,4), (2,4), (2,3), (1,2), (2,2), (2,1), (0,0), (1,0), (2,0)],
    '4': [(0,4), (2,4), (0,3), (2,3), (0,2), (1,2), (2,2), (2,1), (2,0)],
    '5': [(0,4), (1,4), (2,4), (0,3), (0,2), (1,2), (2,2), (2,1), (0,0), (1,0), (2,0)],
    '6': [(0,4), (1,4), (2,4), (0,3), (0,2), (1,2), (2,2), (0,1), (2,1), (0,0), (1,0), (2,0)],
    '7': [(0,4), (1,4), (2,4), (2,3), (2,2), (2,1), (2,0)],
    '8': [(0,4), (1,4), (2,4), (0,3), (2,3), (0,2), (1,2), (2,2), (0,1), (2,1), (0,0), (1,0), (2,0)],
    '9': [(0,4), (1,4), (2,4), (0,3), (2,3), (0,2), (1,2), (2,2), (2,1), (0,0), (1,0), (2,0)]
}

class Direction(Enum):
    LEFT = 1
    RIGHT = 2
    UP = 3
    DOWN = 4

class PlayerID(Enum):
    BLUE_P1 = 1  # Controls from -X view
    BLUE_P2 = 2  # Controls from -Y view
    ORANGE_P3 = 3  # Controls from +X view
    ORANGE_P4 = 4  # Controls from +Y view

class TeamID(Enum):
    BLUE = 1
    ORANGE = 2

# Configuration mapping player roles to their team and view orientation
PLAYER_CONFIG = {
    PlayerID.BLUE_P1: {
        'team': TeamID.BLUE,
        'view': (-1, 0, 0),  # -X view
        'left_dir': (0, -1, 0),  # -Y
        'right_dir': (0, 1, 0),  # +Y
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.BLUE_P2: {
        'team': TeamID.BLUE,
        'view': (0, -1, 0),  # -Y view
        'left_dir': (1, 0, 0),  # +X
        'right_dir': (-1, 0, 0), # -X
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.ORANGE_P3: {
        'team': TeamID.ORANGE,
        'view': (1, 0, 0),   # +X view
        'left_dir': (0, 1, 0),  # +Y
        'right_dir': (0, -1, 0), # -Y
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.ORANGE_P4: {
        'team': TeamID.ORANGE,
        'view': (0, 1, 0),   # +Y view
        'left_dir': (-1, 0, 0), # -X
        'right_dir': (1, 0, 0),  # +X
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    }
}

class PygameInputHandler:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((640, 480))
        pygame.display.set_caption('3D Snake Scene')

    def get_direction_key(self):
        for event in pygame.event.get():
            if event.type == KEYDOWN:
                if event.key == K_UP:
                    return Direction.UP
                elif event.key == K_DOWN:
                    return Direction.DOWN
                elif event.key == K_LEFT:
                    return Direction.LEFT
                elif event.key == K_RIGHT:
                    return Direction.RIGHT
        return None

class ControllerInputHandler:
    def __init__(self):
        self.cp = control_port.ControlPort()
        self.controllers = {}  # Maps controller_id to (controller_state, player_id)
        self.active_controllers = []  # List of active controller states
        self._lock = threading.Lock()
        self.initialized = False
        self.event_queue = deque()  # Queue for (player_id, direction) events
        self.init_event = threading.Event()
        self.loop = None
        self._init_task = None
        self._listen_tasks = {}  # Maps controller_id to its listen task
        self.select_hold_data = {}  # Maps controller_id to {'start_time': float, 'is_counting_down': bool}
        self.last_display_update = 0
        self.display_update_interval = 0.1  # Update displays every 100ms

    async def _async_initialize_and_listen(self):
        """Runs in the asyncio thread to initialize and start listening."""
        print("Enumerating controllers...")
        try:
            controllers = await self.cp.enumerate(timeout=5.0)
            if not controllers:
                print("No controllers found.")
                self.initialized = False
                return

            # Sort controllers by DIP switch ID
            sorted_controllers = sorted(
                [(ip, state) for ip, state in controllers.items()],
                key=lambda x: x[1].dip
            )

            # Assign roles to first 4 controllers
            for i, (ip, state) in enumerate(sorted_controllers[:4]):
                if i < len(PlayerID):
                    player_id = list(PlayerID)[i]
                    if await state.connect():
                        print(f"Connected to controller {ip} (DIP: {state.dip}) as {player_id.name}")
                        self.controllers[state.dip] = (state, player_id)
                        self.active_controllers.append(state)
                        # Register button callback with controller ID
                        state.register_button_callback(
                            lambda buttons, cid=state.dip: self._button_callback(buttons, cid)
                        )
                        # Start listening task for this controller
                        self._listen_tasks[state.dip] = self.loop.create_task(state._listen_buttons())
                        self.select_hold_data[state.dip] = {'start_time': 0, 'is_counting_down': False}
                    else:
                        print(f"Failed to connect to controller {ip}")
                else:
                    print(f"Controller {ip} (DIP: {state.dip}) not assigned - maximum 4 controllers supported")

            self.initialized = len(self.controllers) > 0

        except Exception as e:
            print(f"Error during controller async initialization: {e}")
            self.initialized = False
        finally:
            self.init_event.set()

    def _button_callback(self, buttons, controller_id):
        """Called from the asyncio thread when a controller's buttons change."""
        if controller_id not in self.controllers:
            return

        controller_state, player_id = self.controllers[controller_id]
        config = PLAYER_CONFIG[player_id]

        # Handle SELECT button (index 4) for restart
        if buttons[4]:  # SELECT pressed
            if not self.select_hold_data[controller_id]['is_counting_down']:
                self.select_hold_data[controller_id] = {
                    'start_time': time.monotonic(),
                    'is_counting_down': True
                }
        else:  # SELECT released
            self.select_hold_data[controller_id]['is_counting_down'] = False

        # Handle direction buttons
        if buttons[0] and not self.last_button_states.get(controller_id, [False] * 5)[0]:
            self.event_queue.append((player_id, Direction.LEFT))
        if buttons[1] and not self.last_button_states.get(controller_id, [False] * 5)[1]:
            self.event_queue.append((player_id, Direction.UP))
        if buttons[2] and not self.last_button_states.get(controller_id, [False] * 5)[2]:
            self.event_queue.append((player_id, Direction.RIGHT))
        if buttons[3] and not self.last_button_states.get(controller_id, [False] * 5)[3]:
            self.event_queue.append((player_id, Direction.DOWN))

        # Store the new state
        self.last_button_states[controller_id] = list(buttons)

    def get_direction_key(self):
        """Called from the main game thread to get the next input event."""
        if not self.initialized:
            return None

        with self._lock:
            if self.event_queue:
                return self.event_queue.popleft()
        return None

    def check_for_restart_signal(self):
        """Check if any controller has held SELECT for 5 seconds."""
        current_time = time.monotonic()
        for controller_id, hold_data in self.select_hold_data.items():
            if hold_data['is_counting_down']:
                if current_time - hold_data['start_time'] >= 5.0:
                    return True
        return False

    def clear_all_select_holds(self):
        """Clear all SELECT hold states."""
        for hold_data in self.select_hold_data.values():
            hold_data['is_counting_down'] = False

    async def _update_controller_displays(self, snakes_data, game_over_active):
        """Update all controller displays with current game state."""
        current_time = time.monotonic()
        if current_time - self.last_display_update < self.display_update_interval:
            return

        self.last_display_update = current_time

        for controller_id, (controller_state, player_id) in self.controllers.items():
            config = PLAYER_CONFIG[player_id]
            team = config['team']
            team_name = team.name.lower()
            other_team = TeamID.ORANGE if team == TeamID.BLUE else TeamID.BLUE

            # Get scores
            team_score = snakes_data[team_name].score
            other_score = snakes_data[other_team.name.lower()].score

            # Format display text
            lines = [
                f"YOU ARE TEAM {team_name.upper()}",
                f"{team_name.title()} score: {team_score}",
                f"Other score:    {other_score}"
            ]

            # Add SELECT/EXIT status
            hold_data = self.select_hold_data[controller_id]
            if hold_data['is_counting_down']:
                remaining = math.ceil(5.0 - (current_time - hold_data['start_time']))
                lines.append(f"EXIT in {remaining}")
            else:
                lines.append("Hold SELECT to EXIT")

            # Update display
            await controller_state.clear_lcd()
            for i, line in enumerate(lines):
                await controller_state.set_lcd(0, i, line)

    def start_initialization(self):
        """Starts the background thread and waits for initialization."""
        self.thread = threading.Thread(target=self._run_asyncio_loop, daemon=True)
        self.thread.start()
        initialized = self.init_event.wait(timeout=7.0)
        if not initialized:
            print("Controller initialization timed out.")
            self.stop()
            return False
        return self.initialized

    def _run_asyncio_loop(self):
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self._init_task = self.loop.create_task(self._async_initialize_and_listen())
            self.loop.run_forever()
        finally:
            print("Asyncio loop stopping...")
            if self._init_task and not self._init_task.done():
                self._init_task.cancel()

            for task in self._listen_tasks.values():
                if not task.done():
                    task.cancel()

            async def gather_cancelled():
                tasks = [t for t in asyncio.all_tasks(self.loop) if t.cancelled()]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            if self.loop.is_running():
                self.loop.run_until_complete(gather_cancelled())
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())

            self.loop.close()
            print("Asyncio loop stopped.")

    def stop(self):
        """Clean up all controller connections and tasks."""
        print("Stopping controller input handler...")
        loop = getattr(self, 'loop', None)
        if loop and loop.is_running():
            for controller_id, (controller_state, _) in self.controllers.items():
                if controller_state._connected:
                    disconnect_future = asyncio.run_coroutine_threadsafe(
                        controller_state.disconnect(), loop
                    )
                    try:
                        disconnect_future.result(timeout=2)
                        print(f"Controller {controller_id} disconnected.")
                    except Exception as e:
                        print(f"Error disconnecting controller {controller_id}: {e}")

            if self._init_task:
                loop.call_soon_threadsafe(self._init_task.cancel)

            for task in self._listen_tasks.values():
                if not task.done():
                    loop.call_soon_threadsafe(task.cancel)

            loop.call_soon_threadsafe(loop.stop)

        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=3.0)

class SnakeData:
    def __init__(self, id, color, start_pos, start_dir):
        self.id = id
        self.color = color
        self.body = [start_pos]
        self.direction = start_dir
        self.length = 3
        self.score = 0

class SnakeScene(Scene):
    def __init__(self, width=20, height=20, length=20, frameRate=3, input_handler_type='controller'):
        super().__init__()
        self.thickness = 2
        self.width = width // self.thickness
        self.height = height // self.thickness
        self.length = length // self.thickness
        self.frameRate = frameRate

        print(f"Initializing SnakeScene with input type: {input_handler_type}")
        if input_handler_type == 'controller':
            print("Attempting to initialize controller input...")
            controller_handler = ControllerInputHandler()
            if controller_handler.start_initialization():
                self.input_handler = controller_handler
                print("Controller input handler started.")
            else:
                print("Controller initialization failed, falling back to Pygame.")
                self.input_handler = PygameInputHandler()
        else:
            self.input_handler = PygameInputHandler()

        self.reset_game()
        self.last_update_time = 0
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}

    def valid(self, x, y, z):
        return 0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length

    def process_player_input(self, player_id, action):
        """Process input from a player and update their snake's direction."""
        config = PLAYER_CONFIG[player_id]
        team = config['team']
        snake_id = team.name.lower()
        snake = self.snakes[snake_id]

        # Map the action to a new direction based on player's view orientation
        if action == Direction.LEFT:
            new_dir = config['left_dir']
        elif action == Direction.RIGHT:
            new_dir = config['right_dir']
        elif action == Direction.UP:
            new_dir = config['up_dir']
        elif action == Direction.DOWN:
            new_dir = config['down_dir']
        else:
            return

        # Prevent 180-degree turns
        if (snake.direction[0] != -new_dir[0] or 
            snake.direction[1] != -new_dir[1] or 
            snake.direction[2] != -new_dir[2]):
            snake.direction = new_dir

    def update_snake(self, snake_id):
        """Update a single snake's position and handle collisions."""
        snake = self.snakes[snake_id]
        other_snake_id = 'orange' if snake_id == 'blue' else 'blue'
        other_snake = self.snakes[other_snake_id]

        # Calculate new head position
        head = snake.body[0]
        new_head = (head[0] + snake.direction[0],
                   head[1] + snake.direction[1],
                   head[2] + snake.direction[2])

        # Check for collisions
        if (not self.valid(*new_head) or  # Wall collision
            new_head in snake.body or      # Self collision
            new_head in other_snake.body): # Other snake collision
            snake.score -= 1
            snake.length -= 1
            if snake.length <= 0:
                snake.length = 0
                self.game_over_active = True
                self.game_over_flash_state = {
                    'count': 10,  # 5 flashes (on/off)
                    'timer': 0,
                    'interval': 0.2,
                    'border_on': False
                }
                return False
            else:
                # Respawn snake at a new position
                while True:
                    x = random.randint(0, self.width-1)
                    y = random.randint(0, self.height-1)
                    z = random.randint(0, self.length-1)
                    pos = (x, y, z)
                    if (pos not in snake.body and 
                        pos not in other_snake.body and 
                        pos != self.apple):
                        snake.body = [pos]
                        snake.direction = (1, 0, 0)  # Default direction
                        break
                return True

        # Move snake
        snake.body.insert(0, new_head)
        if len(snake.body) > snake.length:
            snake.body.pop()

        # Check for apple consumption
        if new_head == self.apple:
            snake.length += 1
            self.place_new_apple()

        return True

    def place_new_apple(self):
        """Place apple in a valid position not occupied by any snake."""
        while True:
            x = random.randint(0, self.width-1)
            y = random.randint(0, self.height-1)
            z = random.randint(0, self.length-1)
            pos = (x, y, z)
            if (pos not in self.snakes['blue'].body and 
                pos not in self.snakes['orange'].body):
                self.apple = pos
                break

    def reset_game(self):
        """Reset the game state."""
        # Initialize blue snake
        blue_start = (self.width//4, self.length//2, self.height//2)
        self.snakes = {
            'blue': SnakeData('blue', blue, blue_start, (1, 0, 0))
        }

        # Initialize orange snake
        orange_start = (3*self.width//4, self.length//2, self.height//2)
        self.snakes['orange'] = SnakeData('orange', orange, orange_start, (-1, 0, 0))

        # Set initial lengths
        self.snakes['blue'].length = 3
        self.snakes['orange'].length = 3

        # Reset scores
        self.snakes['blue'].score = 0
        self.snakes['orange'].score = 0

        # Place first apple
        self.place_new_apple()

        # Reset game state
        self.game_over_active = False
        self.game_started = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}

    def render(self, raster, time):
        # Update game state
        if time - self.last_update_time >= 1.0/self.frameRate:
            self.last_update_time = time

            # Process controller inputs
            if isinstance(self.input_handler, ControllerInputHandler):
                input_event = self.input_handler.get_direction_key()
                if input_event:
                    player_id, action = input_event
                    self.process_player_input(player_id, action)
                    if self.game_over_active:
                        self.reset_game()
                    self.game_started = True

            # Update game state if started and not in game over sequence
            if self.game_started and not self.game_over_active:
                # Update both snakes
                self.update_snake('blue')
                self.update_snake('orange')

                # Check for restart signal
                if isinstance(self.input_handler, ControllerInputHandler):
                    if self.input_handler.check_for_restart_signal():
                        self.reset_game()
                        self.input_handler.clear_all_select_holds()

            # Update controller displays
            if isinstance(self.input_handler, ControllerInputHandler):
                asyncio.run_coroutine_threadsafe(
                    self.input_handler._update_controller_displays(
                        self.snakes, self.game_over_active
                    ),
                    self.input_handler.loop
                )

        # Clear the raster
        for y in range(raster.height):
            for x in range(raster.width):
                for z in range(raster.length):
                    idx = y * raster.width + x + z * raster.width * raster.height
                    raster.data[idx] = black

        # Draw game over border if active
        if self.game_over_active and self.game_over_flash_state['border_on']:
            # Draw red border on all edges
            for y in range(raster.height):
                for x in range(raster.width):
                    for z in range(raster.length):
                        if (x == 0 or x == raster.width-1 or
                            y == 0 or y == raster.height-1 or
                            z == 0 or z == raster.length-1):
                            idx = y * raster.width + x + z * raster.width * raster.height
                            raster.data[idx] = red

        # Draw both snakes
        for snake_id, snake in self.snakes.items():
            for i, segment in enumerate(snake.body):
                x, y, z = segment
                if self.valid(x, y, z):
                    x *= self.thickness
                    y *= self.thickness
                    z *= self.thickness
                    for dx in range(self.thickness):
                        for dy in range(self.thickness):
                            for dz in range(self.thickness):
                                idx = (y+dy) * raster.width + (x+dx) + (z+dz) * raster.width * raster.height
                                if i == 0:  # Head
                                    raster.data[idx] = red
                                else:  # Body
                                    raster.data[idx] = snake.color

        # Draw the apple
        x, y, z = self.apple
        x *= self.thickness
        y *= self.thickness
        z *= self.thickness
        for dx in range(self.thickness):
            for dy in range(self.thickness):
                for dz in range(self.thickness):
                    idx = (y+dy) * raster.width + (x+dx) + (z+dz) * raster.width * raster.height
                    raster.data[idx] = white

    def cleanup(self):
        """Clean up resources."""
        print("Cleaning up SnakeScene...")
        if isinstance(self.input_handler, ControllerInputHandler):
            self.input_handler.stop()
                        