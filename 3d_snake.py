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
import json

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

class Button(Enum):
    UP = 0
    LEFT = 1
    DOWN = 2
    RIGHT = 3
    SELECT = 4

class Difficulty(Enum):
    EASY = 1
    MEDIUM = 2
    HARD = 3

class PlayerID(Enum):
    BLUE_P1 = 1  # Controls from -X view
    BLUE_P2 = 2  # Controls from -Y view
    ORANGE_P1 = 3  # Controls from +X view
    ORANGE_P2 = 4  # Controls from +Y view

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
    PlayerID.ORANGE_P1: {
        'team': TeamID.ORANGE,
        'view': (1, 0, 0),   # +X view
        'left_dir': (0, 1, 0),  # +Y
        'right_dir': (0, -1, 0), # -Y
        'up_dir': (0, 0, 1),    # +Z
        'down_dir': (0, 0, -1), # -Z
    },
    PlayerID.ORANGE_P2: {
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

class DisplayManager:
    def __init__(self):
        self.last_display_update = 0
        self.display_update_interval = 0.1  # Update displays every 100ms

    def _log_lcd_command(self, controller_id, line, text):
        """Log an LCD command being sent to a controller."""
        print(f"LCD[{controller_id}] Line {line}: {text}")

    async def update_displays(self, controllers, game_state):
        """Update all controller displays with current game state."""
        current_time = time.monotonic()
        if current_time - self.last_display_update < self.display_update_interval:
            return

        self.last_display_update = current_time

        async def update_single_controller(controller_state, player_id):
            if game_state.countdown_active:
                # Show countdown display
                controller_state.clear()
                config = PLAYER_CONFIG[player_id]
                team = config['team']
                difficulty_text = ">>> EASY <<<" if game_state.difficulty == Difficulty.EASY else ">>> MEDIUM <<<" if game_state.difficulty == Difficulty.MEDIUM else ">>> HARD <<<"
                
                controller_state.write_lcd(0, 0, f"TEAM {team.name}")
                controller_state.write_lcd(0, 1, difficulty_text)
                controller_state.write_lcd(0, 2, f"GET READY! {game_state.countdown_value}...")
                controller_state.write_lcd(0, 3, "Hold SELECT to EXIT")
                await controller_state.commit()
                return

            if game_state.menu_active:
                # Show difficulty selection menu
                input_handler = game_state.input_handler
                current_selection = game_state.menu_selections.get(controller_state.dip, 0)
                has_voted = game_state.voting_states.get(controller_state.dip, False)
                waiting_count = sum(1 for v in game_state.voting_states.values() if v)
                total_players = len(controllers)
                
                # Count votes for each difficulty
                easy_votes = sum(1 for v in game_state.menu_votes.values() if v == Direction.UP)
                medium_votes = sum(1 for v in game_state.menu_votes.values() if v == Direction.DOWN)
                hard_votes = sum(1 for v in game_state.menu_votes.values() if v is None)
                
                # Show '<' for current selection, 'X' for confirmed vote
                easy_marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) == Direction.UP else "<" if current_selection == 0 else " "
                medium_marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) == Direction.DOWN else "<" if current_selection == 1 else " "
                hard_marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) is None else "<" if current_selection == 2 else " "
                
                # Clear the back buffer
                controller_state.clear()
                
                controller_state.write_lcd(0, 0, "SELECT DIFFICULTY")
                controller_state.write_lcd(0, 1, "EASY")
                controller_state.write_lcd(7, 1, easy_marker)
                if easy_votes > 0:
                    controller_state.write_lcd(17, 1, str(easy_votes))
                
                controller_state.write_lcd(0, 2, "MEDIUM")
                controller_state.write_lcd(7, 2, medium_marker)
                if medium_votes > 0:
                    controller_state.write_lcd(17, 2, str(medium_votes))
                
                controller_state.write_lcd(0, 3, "HARD")
                controller_state.write_lcd(7, 3, hard_marker)
                if hard_votes > 0:
                    controller_state.write_lcd(17, 3, str(hard_votes))
                
                status_text = f"Waiting for {total_players - waiting_count} more" if has_voted else "Press SELECT to vote"
                controller_state.write_lcd(0, 4, status_text)
                
                # Commit the changes to the display
                await controller_state.commit()
            elif game_state.game_over_active:
                # Show game over screen
                config = PLAYER_CONFIG[player_id]
                team = config['team']
                snake_id = team.name.lower()
                snake = game_state.snakes[snake_id]
                other_snake_id = 'orange' if snake_id == 'blue' else 'blue'
                other_snake = game_state.snakes[other_snake_id]

                # Determine winner
                if snake.score > other_snake.score:
                    result = "WIN"
                elif snake.score < other_snake.score:
                    result = "LOSE"
                else:
                    result = "DRAW"

                controller_state.clear()
                controller_state.write_lcd(0, 0, f"GAME OVER! YOU {result}")
                controller_state.write_lcd(0, 1, f"TEAM {team.name}: {snake.score}")
                controller_state.write_lcd(0, 2, f"OPPONENT: {other_snake.score}")

                # Show exit countdown if SELECT is being held
                hold_data = game_state.input_handler.select_hold_data.get(controller_state.dip, {'is_counting_down': False, 'start_time': 0})
                if hold_data['is_counting_down']:
                    remaining = 5 - (current_time - hold_data['start_time'])
                    if remaining > 0:
                        controller_state.write_lcd(0, 3, f"EXIT: {remaining:.1f}s")
                    else:
                        controller_state.write_lcd(0, 3, "EXITING...")
                else:
                    controller_state.write_lcd(0, 3, "Hold SELECT to EXIT")

                await controller_state.commit()
            else:
                # Show game state (team assignment and scores)
                config = PLAYER_CONFIG[player_id]
                team = config['team']
                snake_id = team.name.lower()
                snake = game_state.snakes[snake_id]
                other_snake_id = 'orange' if snake_id == 'blue' else 'blue'
                other_snake = game_state.snakes[other_snake_id]

                # Clear the back buffer
                controller_state.clear()

                # Show team assignment and scores
                controller_state.write_lcd(0, 0, f"TEAM: {team.name}")
                controller_state.write_lcd(0, 1, "SCORE:")
                controller_state.write_lcd(16, 1, str(snake.score))
                controller_state.write_lcd(0, 2, "OPPONENT:")
                controller_state.write_lcd(16, 2, str(other_snake.score))

                # Show exit countdown if SELECT is being held
                hold_data = game_state.input_handler.select_hold_data.get(controller_state.dip, {'is_counting_down': False, 'start_time': 0})
                if hold_data['is_counting_down']:
                    remaining = 5 - (current_time - hold_data['start_time'])
                    if remaining > 0:
                        controller_state.write_lcd(0, 3, f"EXIT: {remaining:.1f}s")
                    else:
                        controller_state.write_lcd(0, 3, "EXITING...")
                else:
                    controller_state.write_lcd(0, 3, "Hold SELECT to EXIT")

                # Commit the changes to the display
                await controller_state.commit()

        # Create and gather all controller update tasks
        update_tasks = [
            update_single_controller(controller_state, player_id)
            for controller_id, (controller_state, player_id) in controllers.items()
        ]
        if update_tasks:
            await asyncio.gather(*update_tasks)

class ControllerInputHandler:
    def __init__(self, controller_mapping=None):
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
        self.last_button_states = {}  # Maps controller_id to list of button states
        self.menu_selection_time = 0  # Time of last menu selection change
        self.menu_votes = {}  # Maps controller_id to their difficulty vote
        self.voting_states = {}  # Maps controller_id to whether they have voted
        self.controller_mapping = controller_mapping or {}

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

            # Assign roles to controllers based on mapping
            for ip, state in sorted_controllers:
                if state.dip in self.controller_mapping:
                    player_id = self.controller_mapping[state.dip]
                    if await state.connect():
                        print(f"Connected to controller {ip} (DIP: {state.dip}) as {player_id.name}")
                        # Clear the LCD on first connect
                        await state.clear_lcd()
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
                    print(f"Controller {ip} (DIP: {state.dip}) not assigned - no mapping found")

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

        # Map button indices to their logical meaning
        button_to_enum = {
            0: Button.UP,
            1: Button.LEFT,
            2: Button.DOWN,
            3: Button.RIGHT,
            4: Button.SELECT
        }

        # Handle SELECT button for menu selection
        if buttons[Button.SELECT.value]:  # SELECT pressed
            if not self.select_hold_data[controller_id]['is_counting_down']:
                self.select_hold_data[controller_id] = {
                    'start_time': time.monotonic(),
                    'is_counting_down': True
                }
        else:  # SELECT released
            if self.select_hold_data[controller_id]['is_counting_down']:
                # If held for less than 1 second, treat as menu selection
                if time.monotonic() - self.select_hold_data[controller_id]['start_time'] < 1.0:
                    with self._lock:
                        self.event_queue.append((player_id, Button.SELECT))
            self.select_hold_data[controller_id]['is_counting_down'] = False

        # Handle directional buttons for snake control
        # Map Button enum to Direction enum for game controls
        button_to_direction = {
            Button.UP: Direction.UP,
            Button.LEFT: Direction.LEFT,
            Button.DOWN: Direction.DOWN,
            Button.RIGHT: Direction.RIGHT
        }

        # Check each directional button and queue the corresponding direction
        for button in [Button.UP, Button.LEFT, Button.DOWN, Button.RIGHT]:
            if buttons[button.value] and not self.last_button_states.get(controller_id, [False] * 5)[button.value]:
                with self._lock:
                    self.event_queue.append((player_id, button_to_direction[button]))

        # Handle UP/DOWN for menu navigation
        current_time = time.monotonic()
        if current_time - self.menu_selection_time > 0.2:  # Debounce menu selection
            if buttons[Button.UP.value] and not self.last_button_states.get(controller_id, [False] * 5)[Button.UP.value]:
                with self._lock:
                    self.event_queue.append((player_id, Button.UP))
                self.menu_selection_time = current_time
            elif buttons[Button.DOWN.value] and not self.last_button_states.get(controller_id, [False] * 5)[Button.DOWN.value]:
                with self._lock:
                    self.event_queue.append((player_id, Button.DOWN))
                self.menu_selection_time = current_time

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

    def clear_menu_votes(self):
        """Clear all menu votes and selections."""
        self.menu_votes.clear()
        self.menu_selections.clear()
        self.voting_states.clear()

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

class RainbowExplosion:
    def __init__(self, position, time):
        self.position = position
        self.birth_time = time
        self.lifetime = 1.0  # Explosion lasts 1 second
        self.radius = 0
        self.max_radius = 5

    def is_expired(self, current_time):
        return current_time - self.birth_time > self.lifetime

    def get_current_radius(self, current_time):
        age = current_time - self.birth_time
        if age < self.lifetime:
            # Expand from 0 to max_radius over lifetime
            return self.max_radius * (age / self.lifetime)
        return 0

class SnakeData:
    def __init__(self, id, color, start_pos, start_dir):
        self.id = id
        self.color = color
        self.body = [start_pos]
        self.direction = start_dir
        self.length = 3
        self.score = 0

class SnakeScene(Scene):
    def __init__(self, width=20, height=20, length=20, frameRate=3, input_handler_type='controller', config=None):
        super().__init__()
        self.thickness = 2
        self.width = width // self.thickness
        self.height = height // self.thickness
        self.length = length // self.thickness
        self.frameRate = frameRate
        self.base_frame_rate = frameRate  # Store original frame rate
        self.explosions = []  # List to track active explosions

        # Initialize menu-related attributes
        self.menu_selections = {}  # Maps controller_id to their current selection (0=EASY, 1=MEDIUM, 2=HARD)
        self.menu_votes = {}  # Maps controller_id to their difficulty vote
        self.voting_states = {}  # Maps controller_id to whether they have voted

        # Store controller mapping from config
        self.controller_mapping = {}
        if config and 'scene' in config and '3d_snake' in config['scene']:
            scene_config = config['scene']['3d_snake']
            if 'controller_mapping' in scene_config:
                print("Found controller mapping in config:", scene_config['controller_mapping'])
                # Convert string keys to PlayerID enum values
                for role, dip in scene_config['controller_mapping'].items():
                    try:
                        # Convert role to uppercase
                        role_upper = role.upper()
                        player_id = PlayerID[role_upper]
                        self.controller_mapping[dip] = player_id
                        print(f"Mapped controller DIP {dip} to {player_id.name}")
                    except KeyError:
                        print(f"Warning: Unknown player role '{role}' in controller mapping")
            else:
                print("No controller_mapping found in scene config")
        else:
            print("No scene config found in config file")

        print("Final controller mapping:", {dip: pid.name for dip, pid in self.controller_mapping.items()})

        print(f"Initializing SnakeScene with input type: {input_handler_type}")
        if input_handler_type == 'controller':
            print("Attempting to initialize controller input...")
            controller_handler = ControllerInputHandler(controller_mapping=self.controller_mapping)
            if controller_handler.start_initialization():
                self.input_handler = controller_handler
                print("Controller input handler started.")
            else:
                print("Controller initialization failed, falling back to Pygame.")
                self.input_handler = PygameInputHandler()
        else:
            self.input_handler = PygameInputHandler()

        self.display_manager = DisplayManager()
        self.reset_game()
        self.last_update_time = 0
        self.last_countdown_time = 0
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}
        self.menu_active = True
        self.countdown_active = False
        self.countdown_value = None
        self.difficulty = None

    def valid(self, x, y, z):
        if self.difficulty in [Difficulty.EASY, Difficulty.MEDIUM]:
            # Wrap around in EASY and MEDIUM modes
            x = x % self.width
            y = y % self.height
            z = z % self.length
            return True
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

        # Handle wrapping in EASY and MEDIUM modes
        if self.difficulty in [Difficulty.EASY, Difficulty.MEDIUM]:
            new_head = (new_head[0] % self.width,
                       new_head[1] % self.height,
                       new_head[2] % self.length)

        # Check for collisions
        if (not self.valid(*new_head) or  # Wall collision (only in HARD mode)
            new_head in snake.body or      # Self collision
            new_head in other_snake.body):
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
            snake.score += 1  # Increment score when eating an apple
            # Create explosion effect at apple position
            self.explosions.append(RainbowExplosion(self.apple, self.last_update_time))
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
        self.menu_active = True
        self.countdown_active = False
        self.countdown_value = None
        self.difficulty = None
        self.frameRate = self.base_frame_rate

        # Clear menu and voting states
        self.menu_selections.clear()
        self.menu_votes.clear()
        self.voting_states.clear()

    def select_difficulty(self):
        """Handle difficulty selection and voting."""
        if not isinstance(self.input_handler, ControllerInputHandler):
            return

        # Check if all active controllers have voted
        active_controllers = set(self.input_handler.controllers.keys())
        voted_controllers = set(self.voting_states.keys())
        if not active_controllers.issubset(voted_controllers):
            return  # Not all controllers have voted yet

        # All players have voted
        vote_counts = {Difficulty.EASY: 0, Difficulty.MEDIUM: 0, Difficulty.HARD: 0}
        for vote in self.menu_votes.values():
            if vote == Direction.UP:
                vote_counts[Difficulty.EASY] += 1
            elif vote == Direction.DOWN:
                vote_counts[Difficulty.MEDIUM] += 1
            else:
                vote_counts[Difficulty.HARD] += 1

        # Find highest vote count
        max_votes = max(vote_counts.values())
        # Get all difficulties with max votes
        max_difficulties = [d for d, v in vote_counts.items() if v == max_votes]
        # Randomly select from tied difficulties
        self.difficulty = random.choice(max_difficulties)

        # Set game speed based on difficulty
        if self.difficulty == Difficulty.EASY:
            self.frameRate = self.base_frame_rate // 2  # Half speed
        else:
            self.frameRate = self.base_frame_rate  # Normal speed

        # Start countdown
        self.menu_active = False
        self.countdown_active = True
        self.countdown_value = 3
        self.last_countdown_time = time.monotonic()  # Initialize countdown timer
        self.input_handler.clear_all_select_holds()  # Clear any held SELECT buttons

    def process_menu_input(self, player_id, action):
        """Process menu-related input."""
        if not isinstance(self.input_handler, ControllerInputHandler):
            return

        controller_id = next(cid for cid, (_, pid) in self.input_handler.controllers.items() if pid == player_id)
        
        if action == Button.SELECT:
            if controller_id in self.voting_states and self.voting_states[controller_id]:
                # If already voted, remove vote
                self.voting_states[controller_id] = False
                self.menu_votes.pop(controller_id, None)
            else:
                # Convert current selection to vote
                selection = self.menu_selections.get(controller_id, 0)
                if selection == 0:
                    self.menu_votes[controller_id] = Direction.UP  # EASY
                elif selection == 1:
                    self.menu_votes[controller_id] = Direction.DOWN  # MEDIUM
                else:
                    self.menu_votes[controller_id] = None  # HARD
                self.voting_states[controller_id] = True
        elif action == Button.UP:
            # Move selection up (0->1->2->0)
            current = self.menu_selections.get(controller_id, 0)
            self.menu_selections[controller_id] = (current - 1) % 3
            # If player was in voting state, remove their vote
            if controller_id in self.voting_states and self.voting_states[controller_id]:
                self.voting_states[controller_id] = False
                self.menu_votes.pop(controller_id, None)
        elif action == Button.DOWN:
            # Move selection down (0->2->1->0)
            current = self.menu_selections.get(controller_id, 0)
            self.menu_selections[controller_id] = (current + 1) % 3
            # If player was in voting state, remove their vote
            if controller_id in self.voting_states and self.voting_states[controller_id]:
                self.voting_states[controller_id] = False
                self.menu_votes.pop(controller_id, None)

    def render(self, raster, current_time):
        # Update controller displays independently of game state
        if isinstance(self.input_handler, ControllerInputHandler):
            # Update controller displays
            asyncio.run_coroutine_threadsafe(
                self.display_manager.update_displays(
                    self.input_handler.controllers,
                    self
                ),
                self.input_handler.loop
            )

        # Update game state
        if current_time - self.last_update_time >= 1.0/self.frameRate:
            self.last_update_time = current_time

            if isinstance(self.input_handler, ControllerInputHandler):
                # Handle menu and countdown
                if self.menu_active:
                    self.select_difficulty()
                elif self.countdown_active:
                    # Decrement countdown every second
                    current_time = time.monotonic()
                    if current_time - self.last_countdown_time >= 1.0:  # Use separate timer for countdown
                        print(f"Countdown: {self.countdown_value}")  # Debug log
                        self.countdown_value -= 1
                        self.last_countdown_time = current_time  # Update the countdown timer
                        if self.countdown_value <= 0:
                            print("Countdown finished, starting game")  # Debug log
                            self.countdown_active = False
                            self.game_started = True
                            print(f"Game started with difficulty: {self.difficulty.name}")

                # Process controller inputs
                input_event = self.input_handler.get_direction_key()
                if input_event:
                    player_id, action = input_event
                    if self.game_started and not self.game_over_active:
                        self.process_player_input(player_id, action)
                    elif self.menu_active:
                        self.process_menu_input(player_id, action)

                # Update game state if started and not in menu/countdown
                if self.game_started and not self.game_over_active:
                    # Update both snakes
                    self.update_snake('blue')
                    self.update_snake('orange')

                # Check for restart signal
                if self.input_handler.check_for_restart_signal():
                    self.reset_game()
                    self.input_handler.clear_all_select_holds()

        # Clear the raster
        for y in range(raster.height):
            for x in range(raster.width):
                for z in range(raster.length):
                    raster.set_pix(x, y, z, black)

        # Draw explosions
        active_explosions = []
        for explosion in self.explosions:
            if not explosion.is_expired(current_time):
                active_explosions.append(explosion)
                radius = explosion.get_current_radius(current_time)
                x, y, z = explosion.position
                x *= self.thickness
                y *= self.thickness
                z *= self.thickness
                
                # Draw rainbow shell
                for dx in range(-int(radius), int(radius) + 1):
                    for dy in range(-int(radius), int(radius) + 1):
                        for dz in range(-int(radius), int(radius) + 1):
                            # Only draw points on the shell
                            if abs(math.sqrt(dx*dx + dy*dy + dz*dz) - radius) < 0.5:
                                nx = x + dx
                                ny = y + dy
                                nz = z + dz
                                if (0 <= nx < raster.width and 
                                    0 <= ny < raster.height and 
                                    0 <= nz < raster.length):
                                    # Create rainbow color based on position
                                    hue = ((dx + dy + dz) * 4 + current_time * 50) % 256
                                    raster.set_pix(nx, ny, nz, RGB.from_hsv(HSV(hue, 255, 255)))
        self.explosions = active_explosions

        # Draw game over border if active
        if self.game_over_active and self.game_over_flash_state['border_on']:
            # Draw red border on all edges
            for y in range(raster.height):
                for x in range(raster.width):
                    for z in range(raster.length):
                        if (x == 0 or x == raster.width-1 or
                            y == 0 or y == raster.height-1 or
                            z == 0 or z == raster.length-1):
                            raster.set_pix(x, y, z, red)

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
                                if i == 0:  # Head
                                    raster.set_pix(x+dx, y+dy, z+dz, red)
                                else:  # Body
                                    raster.set_pix(x+dx, y+dy, z+dz, snake.color)

        # Draw the apple
        x, y, z = self.apple
        x *= self.thickness
        y *= self.thickness
        z *= self.thickness
        for dx in range(self.thickness):
            for dy in range(self.thickness):
                for dz in range(self.thickness):
                    raster.set_pix(x+dx, y+dy, z+dz, white)

    def cleanup(self):
        """Clean up resources."""
        print("Cleaning up SnakeScene...")
        if isinstance(self.input_handler, ControllerInputHandler):
            self.input_handler.stop()
                        