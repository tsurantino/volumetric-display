import asyncio
import threading
import time
from collections import deque
from enum import Enum
import control_port

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
            if game_state.countdown_active:
                # Show countdown display
                controller_state.clear()
                config = game_state.get_player_config(player_id)
                team = config['team']
                difficulty_text = ">>> EASY <<<" if game_state.difficulty == game_state.Difficulty.EASY else ">>> MEDIUM <<<" if game_state.difficulty == game_state.Difficulty.MEDIUM else ">>> HARD <<<"
                
                controller_state.write_lcd(0, 0, f"TEAM {team.name}")
                controller_state.write_lcd(0, 1, difficulty_text)
                controller_state.write_lcd(0, 2, f"GET READY! {game_state.countdown_value}...")
                controller_state.write_lcd(0, 3, "Hold SELECT to EXIT")
                await controller_state.commit()
                return

            if game_state.menu_active:
                # Show game selection menu
                input_handler = game_state.input_handler
                current_selection = game_state.menu_selections.get(controller_state.dip, 0)
                has_voted = game_state.voting_states.get(controller_state.dip, False)
                waiting_count = sum(1 for v in game_state.voting_states.values() if v)
                total_players = len(controllers)
                
                # Count votes for each game
                game_votes = {game: 0 for game in game_state.available_games}
                for vote in game_state.menu_votes.values():
                    if vote is not None:
                        game_votes[vote] += 1
                
                # Show '<' for current selection, 'X' for confirmed vote
                controller_state.clear()
                controller_state.write_lcd(0, 0, "SELECT GAME")
                
                for i, game in enumerate(game_state.available_games):
                    marker = "X" if has_voted and game_state.menu_votes.get(controller_state.dip) == game else "<" if current_selection == i else " "
                    votes = game_votes[game]
                    controller_state.write_lcd(0, i+1, game.upper())
                    controller_state.write_lcd(7, i+1, marker)
                    if votes > 0:
                        controller_state.write_lcd(17, i+1, str(votes))
                
                status_text = f"Waiting for {total_players - waiting_count} more" if has_voted else "Press SELECT to vote"
                controller_state.write_lcd(0, 4, status_text)
                
                await controller_state.commit()
            elif game_state.game_over_active:
                # Show game over screen
                config = game_state.get_player_config(player_id)
                team = config['team']
                score = game_state.get_player_score(player_id)
                other_score = game_state.get_opponent_score(player_id)

                # Determine winner
                if score > other_score:
                    result = "WIN"
                elif score < other_score:
                    result = "LOSE"
                else:
                    result = "DRAW"

                controller_state.clear()
                controller_state.write_lcd(0, 0, f"GAME OVER! YOU {result}")
                controller_state.write_lcd(0, 1, f"TEAM {team.name}: {score}")
                controller_state.write_lcd(0, 2, f"OPPONENT: {other_score}")

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
                config = game_state.get_player_config(player_id)
                team = config['team']
                score = game_state.get_player_score(player_id)
                other_score = game_state.get_opponent_score(player_id)

                controller_state.clear()
                controller_state.write_lcd(0, 0, f"TEAM: {team.name}")
                controller_state.write_lcd(0, 1, "SCORE:")
                controller_state.write_lcd(16, 1, str(score))
                controller_state.write_lcd(0, 2, "OPPONENT:")
                controller_state.write_lcd(16, 2, str(other_score))

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
        print("Enumerating controllers...")
        try:
            discovered_controller_states = await self.cp.enumerate(timeout=5.0)
            
            if not discovered_controller_states:
                print("ControllerInputHandler: No controllers found/returned by ControlPort.enumerate.")
                self.initialized = False
                self.init_event.set()
                return

            connect_tasks = []
            for ip, state_from_cp in discovered_controller_states.items():
                if state_from_cp.dip in self.controller_mapping:
                    player_id = self.controller_mapping[state_from_cp.dip]
                    print(f"ControllerInputHandler: Attempting to connect and register discovered/queried controller DIP {state_from_cp.dip} ({ip}:{state_from_cp.port}) as {player_id.name}")
                    connect_tasks.append(self._connect_and_register(state_from_cp, player_id))
                else:
                    print(f"ControllerInputHandler: Discovered/queried controller {ip}:{state_from_cp.port} (DIP: {state_from_cp.dip}) not assigned a role in mapping. Skipping.")
            
            if connect_tasks:
                results = await asyncio.gather(*connect_tasks, return_exceptions=True)
            
            self.initialized = len(self.controllers) > 0

        except Exception as e:
            print(f"Error during controller async initialization: {e}")
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