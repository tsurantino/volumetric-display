import asyncio
import threading
import time
from collections import deque
from enum import Enum
import control_port

# Attempt to import GameScene and BaseGame for type checking
# This might create a circular dependency if they also import from game_util
# A cleaner solution might involve a state type enum or attribute checking
try:
    from game_scene import GameScene
except ImportError:
    GameScene = None # Fallback if import fails, to avoid crashing if files are temporarily unavailable

try:
    from base_game import BaseGame, Difficulty # Import Difficulty for BaseGame countdown screen
except ImportError:
    BaseGame = None
    Difficulty = None # Fallback

class Button(Enum):
    UP = 0
    LEFT = 1
    DOWN = 2
    RIGHT = 3
    SELECT = 4

class Direction(Enum):
    LEFT = 1
    RIGHT = 2
    UP = 3
    DOWN = 4

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
            controller_state.clear() # Clear at the beginning of each update for a controller

            game_state_class_name = None
            if hasattr(game_state, '__class__') and hasattr(game_state.__class__, '__name__'):
                game_state_class_name = game_state.__class__.__name__

            print("Current game state class name:", game_state_class_name)

            if game_state_class_name == 'GameScene':
                # Handling display for GameScene (Game Selection Menu & Countdown)
                if game_state.menu_active:
                    # GameScene: Game Selection Menu
                    # input_handler is on game_state (GameScene instance)
                    current_selection = game_state.menu_selections.get(controller_state.dip, 0)
                    has_voted = game_state.voting_states.get(controller_state.dip, False)
                    waiting_count = sum(1 for v_dip in game_state.voting_states if game_state.voting_states[v_dip])
                    # CORRECTED: total_players calculation using game_state.input_handler
                    total_players = 0
                    if game_state.input_handler and hasattr(game_state.input_handler, 'controllers') and game_state.input_handler.controllers:
                        total_players = len(game_state.input_handler.controllers)
                    
                    game_votes = {game_name: 0 for game_name in game_state.available_games.keys()}
                    for voted_game_name in game_state.menu_votes.values():
                        if voted_game_name in game_votes:
                            game_votes[voted_game_name] += 1
                    
                    # Write header
                    controller_state.write_lcd(0, 0, "SELECT GAME:")
                    
                    # Get sorted list of game names
                    game_names = list(game_state.available_games.keys())
                    num_games = len(game_names)
                    
                    # Calculate which games to display (show 3 at a time with scrolling)
                    display_start = 0
                    if num_games > 3:
                        # If selection is 0 or 1, start from 0
                        if current_selection <= 0:
                            display_start = 0
                        # If selection is at the end, show the last 3 games
                        elif current_selection >= num_games - 1:
                            display_start = max(0, num_games - 3)
                        # Otherwise, center the selection
                        else:
                            display_start = current_selection - 1
                    
                    # Display the visible games (up to 3)
                    for i in range(3):
                        if display_start + i < num_games:
                            game_index = display_start + i
                            game_name_key = game_names[game_index]
                            game_display_name = game_name_key.replace('_game', '').upper()
                            
                            # Determine if this game is selected or voted for
                            marker = " "
                            if current_selection == game_index:
                                marker = "<"
                            elif has_voted and game_state.menu_votes.get(controller_state.dip) == game_name_key:
                                marker = "X"
                            
                            # Get vote count for this game
                            votes = game_votes.get(game_name_key, 0)
                            
                            # Display game name (left-aligned) and marker (right-aligned)
                            controller_state.write_lcd(0, i+1, game_display_name)
                            controller_state.write_lcd(19, i+1, marker)
                            
                            # Show vote count if there are votes
                            if votes > 0:
                                controller_state.write_lcd(17, i+1, str(votes))
                    
                    # Display status at the bottom (line 4)
                    status_text = f"Wait: {total_players - waiting_count} more" if has_voted and total_players > 0 else "SELECT to vote"
                    controller_state.write_lcd(0, 4, status_text)

                elif game_state.countdown_active:
                    # GameScene: Countdown to start a selected game
                    selected_game_name = "GAME"
                    if game_state.current_game:
                        selected_game_name = game_state.current_game.__class__.__name__.replace('Game', '').upper()
                    
                    controller_state.write_lcd(0, 0, f"STARTING:")
                    controller_state.write_lcd(0, 1, selected_game_name)
                    controller_state.write_lcd(0, 2, f"IN {game_state.countdown_value}...")
                    controller_state.write_lcd(0, 3, "GET READY!")
            
            # Check for BaseGame derivatives by specific class names for now
            # A more robust check could be `'BaseGame' in [cls.__name__ for cls in type(game_state).mro()]`
            # but that still relies on `BaseGame` class identity for MRO building if not careful.
            elif game_state_class_name in ['SnakeGame', 'BlinkyGame']: # Add other game class names if needed
                # Handling display for a specific game (BaseGame derivative like SnakeGame)
                config = game_state.get_player_config(player_id) # player_id is passed to update_single_controller
                team_name = config['team'].name if config and 'team' in config else "NO TEAM"

                if game_state.menu_active: # Game-specific menu (e.g., Snake difficulty)
                    # This part needs to be made more generic or use a dispatch mechanism
                    # For now, let's assume a generic "MENU ACTIVE" message or adapt Snake's old menu
                    if game_state.__class__.__name__ == 'SnakeGame': # Specific to SnakeGame for now
                        current_selection = game_state.menu_selections.get(controller_state.dip, 0) # 0:EASY, 1:MEDIUM, 2:HARD
                        has_voted = game_state.voting_states.get(controller_state.dip, False)
                        
                        easy_votes = sum(1 for v in game_state.menu_votes.values() if v == Direction.UP) # Assuming UP for EASY
                        medium_votes = sum(1 for v in game_state.menu_votes.values() if v == Direction.DOWN) # Assuming DOWN for MEDIUM
                        hard_votes = sum(1 for v in game_state.menu_votes.values() if v is None) # Assuming None for HARD (default select)

                        easy_marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) == Direction.UP else "<" if current_selection == 0 else " "
                        medium_marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) == Direction.DOWN else "<" if current_selection == 1 else " "
                        hard_marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) is None else "<" if current_selection == 2 else " "

                        controller_state.write_lcd(0,0, "SNAKE: DIFFICULTY")
                        controller_state.write_lcd(0,1, f"EASY   {easy_marker} ({easy_votes})")
                        controller_state.write_lcd(0,2, f"MEDIUM {medium_marker} ({medium_votes})")
                        controller_state.write_lcd(0,3, f"HARD   {hard_marker} ({hard_votes})")
                    else:
                        controller_state.write_lcd(0, 0, f"{game_state.__class__.__name__.upper()}")
                        controller_state.write_lcd(0, 1, "MENU ACTIVE")
                        controller_state.write_lcd(0, 2, "Press SELECT")

                elif game_state.countdown_active:
                    # Game-specific countdown (e.g., Snake after difficulty selection)
                    difficulty_text = "??"
                    if hasattr(game_state, 'difficulty') and game_state.difficulty and hasattr(game_state.difficulty, 'name'):
                        # Compare enum member names as strings
                        if game_state.difficulty.name == 'EASY': difficulty_text = ">> EASY <<"
                        elif game_state.difficulty.name == 'MEDIUM': difficulty_text = ">> MEDIUM <<"
                        elif game_state.difficulty.name == 'HARD': difficulty_text = ">> HARD <<"
                    
                    controller_state.write_lcd(0, 0, f"TEAM {team_name}")
                    controller_state.write_lcd(0, 1, difficulty_text)
                    controller_state.write_lcd(0, 2, f"GET READY! {game_state.countdown_value}...")
                    controller_state.write_lcd(0, 3, "Hold SELECT to EXIT")
                
                elif game_state.game_over_active:
                    # Game-specific game over screen
                    score = game_state.get_player_score(player_id)
                    other_score = game_state.get_opponent_score(player_id)
                    result = "DRAW"
                    if score > other_score: result = "WIN! :)"
                    elif score < other_score: result = "LOSE :("

                    controller_state.write_lcd(0, 0, f"GAME OVER! YOU {result}")
                    controller_state.write_lcd(0, 1, f"TEAM {team_name}: {score}")
                    controller_state.write_lcd(0, 2, f"OPPONENT: {other_score}")
                    controller_state.write_lcd(0, 3, "Hold SELECT to EXIT") # Consider exit countdown logic from old code

                else: # Game in progress
                    score = game_state.get_player_score(player_id)
                    other_score = game_state.get_opponent_score(player_id)
                    controller_state.write_lcd(0, 0, f"TEAM: {team_name}")
                    controller_state.write_lcd(0, 1, f"SCORE:    {score}")
                    controller_state.write_lcd(0, 2, f"OPPONENT: {other_score}")
                    controller_state.write_lcd(0, 3, "Hold SELECT to EXIT") # Consider exit countdown logic
            
            else:
                # Fallback or unhandled game_state type
                controller_state.write_lcd(0,0, "ARTNET DISPLAY")
                controller_state.write_lcd(0,1, "Unknown State")
                if game_state_class_name:
                     controller_state.write_lcd(0,2, game_state_class_name[:19])
                elif game_state:
                    controller_state.write_lcd(0,2, "Unnamed GS Type")
                else:
                    controller_state.write_lcd(0,2, "No GameState")

            await controller_state.commit()

        # Create and gather all controller update tasks
        update_tasks = [
            update_single_controller(controller_state, player_id)
            for controller_id, (controller_state, player_id) in controllers.items()
        ]
        if update_tasks:
            await asyncio.gather(*update_tasks)

class ControllerInputHandler:
    def __init__(self, controller_mapping=None, hosts_and_ports: list[tuple[str, int]] | None = None):
        self.cp = control_port.ControlPort(hosts_and_ports=hosts_and_ports)
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
        self.menu_votes = {}  # Maps controller_id to their game vote
        self.voting_states = {}  # Maps controller_id to whether they have voted
        self.controller_mapping = controller_mapping or {}

    async def _async_initialize_and_listen(self):
        """Runs in the asyncio thread to initialize and start listening."""
        print("ControllerInputHandler: Starting async initialization...")
        try:
            print("ControllerInputHandler: Calling cp.enumerate()...")
            discovered_controller_states = await self.cp.enumerate(timeout=5.0)
            print(f"ControllerInputHandler: cp.enumerate() returned: {discovered_controller_states}")
            
            if not discovered_controller_states:
                print("ControllerInputHandler: No controllers found/returned by ControlPort.enumerate.")
                self.initialized = False
                self.init_event.set()
                return

            connect_tasks = []
            print(f"ControllerInputHandler: Iterating discovered_controller_states items...")
            for dip_key, state_from_cp in discovered_controller_states.items():
                print(f"ControllerInputHandler: Processing discovered_controller_states item: dip_key={dip_key}, state_from_cp={state_from_cp}")
                if state_from_cp.dip in self.controller_mapping:
                    player_id = self.controller_mapping[state_from_cp.dip]
                    print(f"ControllerInputHandler: Controller DIP {state_from_cp.dip} maps to player_id={player_id}. Creating connect task.")
                    connect_tasks.append(self._connect_and_register(state_from_cp, player_id))
                else:
                    print(f"ControllerInputHandler: Discovered/queried controller {state_from_cp.ip}:{state_from_cp.port} (DIP: {state_from_cp.dip}) not assigned a role in mapping. Skipping.")
            
            print(f"ControllerInputHandler: Built connect_tasks list: {connect_tasks}")
            if connect_tasks:
                print(f"ControllerInputHandler: Calling asyncio.gather for {len(connect_tasks)} tasks...")
                results = await asyncio.gather(*connect_tasks, return_exceptions=True)
                print(f"ControllerInputHandler: asyncio.gather results: {results}")
            
            self.initialized = len(self.controllers) > 0
            print(f"ControllerInputHandler: Initialization complete. self.initialized = {self.initialized}, self.controllers = {self.controllers}")

        except Exception as e:
            print(f"Error during controller async initialization: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            self.initialized = False
        finally:
            self.init_event.set()

    async def _connect_and_register(self, controller_state_instance: control_port.ControllerState, player_id):
        """Helper to connect a single controller (given as ControllerState instance) and register callback."""
        dip = controller_state_instance.dip

        if not controller_state_instance._connected:
            if not await controller_state_instance.connect():
                return
        
        print(f"ControllerInputHandler: Successfully connected/verified controller DIP {dip} ({player_id.name})")
        
        self.controllers[dip] = (controller_state_instance, player_id)
        if controller_state_instance not in self.active_controllers:
            self.active_controllers.append(controller_state_instance)
        
        controller_state_instance.register_button_callback(
            lambda buttons, controller_dip=dip: self._button_callback(buttons, controller_dip)
        )

        self.select_hold_data[dip] = {'start_time': 0, 'is_counting_down': False}
        self.last_button_states[dip] = [False] * 5

    def _button_callback(self, buttons, controller_id):
        """Called from the asyncio thread when a controller's buttons change."""
        if controller_id not in self.controllers:
            return

        controller_state, player_id = self.controllers[controller_id]

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

        # Handle directional buttons
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