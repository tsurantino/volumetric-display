from artnet import Scene, RGB
from game_util import ControllerInputHandler, DisplayManager, Button, Direction
import time
import random
from enum import Enum
import importlib.util
import os
import asyncio
from games.util.base_game import BaseGame, PlayerID, TeamID, Difficulty

class GameScene(Scene):
    def __init__(self, width=20, height=20, length=20, frameRate=30, config=None):
        super().__init__()
        self.width = width
        self.height = height
        self.length = length
        self.frameRate = frameRate
        self.menu_frame_rate = 30 
        self.config = config
        self.game_started = False  # Initialize game_started attribute

        # Initialize menu-related attributes
        self.menu_selections = {}  # Maps controller_id to their current selection
        self.menu_votes = {}  # Maps controller_id to their game vote
        self.voting_states = {}  # Maps controller_id to whether they have voted

        # Store controller mapping from config
        self.controller_mapping = {}
        if config and 'scene' in config and '3d_snake' in config['scene']:
            scene_config = config['scene']['3d_snake']
            if 'controller_mapping' in scene_config:
                for role, dip in scene_config['controller_mapping'].items():
                    try:
                        player_id = PlayerID[role.upper()]
                        self.controller_mapping[dip] = player_id
                        print(f"Mapped controller DIP {dip} to {player_id.name}")
                    except KeyError:
                        print(f"Warning: Unknown player role '{role}' in controller mapping")

        # Initialize controller input handler
        # Prepare addresses_to_enumerate for ControllerInputHandler
        addresses_for_handler = None
        if self.config and "controller_addresses" in self.config:
            print("Found 'controller_addresses' in config.")
            controller_addr_config = self.config["controller_addresses"]
            if isinstance(controller_addr_config, dict): # Expecting dict like {"0": {"ip": ..., "port": ...}}
                addresses_for_handler = []
                for dip_str, addr_info in controller_addr_config.items():
                    if isinstance(addr_info, dict) and 'ip' in addr_info and 'port' in addr_info:
                        addresses_for_handler.append((addr_info['ip'], addr_info['port']))
                    else:
                        print(f"Warning: Invalid address info format for DIP {dip_str} in controller_addresses. Expected {{ip:str, port:int}}.")
                if not addresses_for_handler:
                    print("Warning: 'controller_addresses' was present but parsed into an empty list.")
                    addresses_for_handler = None # Fallback to no specific addresses
            else:
                print("Warning: 'controller_addresses' is not a dictionary as expected. Will not use for specific enumeration.")
        
        if addresses_for_handler:
            print(f"Passing specific addresses to ControllerInputHandler for enumeration: {addresses_for_handler}")
        else:
            print("No specific controller_addresses to pass; ControllerInputHandler will use its default enumeration (if any).")

        # Pass controller_mapping for role assignment AND addresses_for_handler for ControlPort
        self.input_handler = ControllerInputHandler(
            controller_mapping=self.controller_mapping,
            hosts_and_ports=addresses_for_handler
        )
        if not self.input_handler.start_initialization():
            print("GameScene: ControllerInputHandler initialization failed.")
            self.input_handler = None # Ensure it's None on failure
        else:
            print("GameScene: ControllerInputHandler initialized successfully.")
        
        self.display_manager = DisplayManager()
        self.last_update_time = 0
        self.last_countdown_time = 0
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}
        self.menu_active = True
        self.countdown_active = False
        self.countdown_value = None
        self.difficulty = None

        # Load available games
        self.available_games = self._load_available_games()
        self.current_game = None

    def _load_available_games(self):
        """Load all available game modules."""
        games = {}
        games_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games")
        print(f"Looking for game modules in directory: {games_dir}")
        
        for filename in os.listdir(games_dir):
            if filename.endswith('_game.py'):
                module_name = filename[:-3]  # Remove .py extension
                print(f"Found game module file: {filename}, module name: {module_name}")
                
                try:
                    print(f"Attempting to load module: {module_name}")
                    spec = importlib.util.spec_from_file_location(module_name, os.path.join(games_dir, filename))
                    if spec is None:
                        print(f"Error: Could not create spec for module {module_name}")
                        continue
                        
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Find the game class (should be the only class that inherits from BaseGame)
                    game_class_found = False
                    for name, obj in module.__dict__.items():
                        if isinstance(obj, type) and issubclass(obj, BaseGame) and obj != BaseGame:
                            print(f"Found game class '{name}' in module {module_name}")
                            games[module_name] = obj
                            game_class_found = True
                            break
                            
                    if not game_class_found:
                        print(f"Warning: No game class found in module {module_name}")
                        print(f"Module contains these objects: {[name for name in module.__dict__ if not name.startswith('__')]}")
                        
                except ImportError as e:
                    print(f"ImportError loading game module {filename}: {e}")
                    print(f"Module might have missing dependencies: {e.__class__.__name__}: {str(e)}")
                except AttributeError as e:
                    print(f"AttributeError loading game module {filename}: {e}")
                    print(f"Module might be missing expected attributes: {e.__class__.__name__}: {str(e)}")
                except TypeError as e:
                    print(f"TypeError loading game module {filename}: {e}")
                    print(f"Possible type mismatch in module: {e.__class__.__name__}: {str(e)}")
                except Exception as e:
                    print(f"Error loading game module {filename}: {e.__class__.__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    
        print(f"Successfully loaded {len(games)} game modules: {list(games.keys())}")
        return games

    def get_player_config(self, player_id):
        """Get the configuration for a player."""
        return PLAYER_CONFIG[player_id]

    def get_player_score(self, player_id):
        """Get the score for a player."""
        if self.current_game:
            return self.current_game.get_player_score(player_id)
        return 0

    def get_opponent_score(self, player_id):
        """Get the score for a player's opponent."""
        if self.current_game:
            return self.current_game.get_opponent_score(player_id)
        return 0

    def reset_game(self):
        """Reset the game state."""
        if self.current_game:
            self.current_game.reset_game()
        else:
            # Initialize with first available game
            if self.available_games:
                game_class = next(iter(self.available_games.values()))
                self.current_game = game_class(
                    width=self.width,
                    height=self.height,
                    length=self.length,
                    frameRate=self.frameRate,
                    config=self.config,
                    input_handler=self.input_handler
                )

    def process_player_input(self, player_id, action):
        """Process input from a player."""
        if self.current_game:
            self.current_game.process_player_input(player_id, action)

    def update_game_state(self):
        """Update the game state."""
        if self.current_game:
            self.current_game.update_game_state()

    def render(self, raster, current_time):
        """Render the game state."""
        # Update controller displays independently of game state
        if self.input_handler:
            # Update controller displays
            asyncio.run_coroutine_threadsafe(
                self.display_manager.update_displays(
                    self.input_handler.controllers,
                    self
                ),
                self.input_handler.loop
            )

        # Use higher frame rate for menu and countdown
        current_frame_rate = self.menu_frame_rate if (self.menu_active or self.countdown_active) else self.frameRate

        # Update game state
        if current_time - self.last_update_time >= 1.0/current_frame_rate:
            self.last_update_time = current_time

            if self.input_handler:
                # Handle menu and countdown
                if self.menu_active:
                    self.select_game(current_time)
                elif self.countdown_active:
                    # Decrement countdown every second
                    if current_time - self.last_countdown_time >= 1.0:
                        print(f"Countdown: {self.countdown_value}")
                        self.countdown_value -= 1
                        self.last_countdown_time = current_time
                        if self.countdown_value <= 0:
                            print("Countdown finished, starting game")
                            self.countdown_active = False
                            self.game_started = True

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
                    self.update_game_state()

                # Check for restart signal
                if self.input_handler.check_for_restart_signal():
                    self.reset_game()
                    self.input_handler.clear_all_select_holds()

        # Clear the raster
        raster.clear()

        # Render game state
        if self.current_game:
            self.current_game.render_game_state(raster)

    def select_game(self, current_time):
        """Handle game selection and voting."""
        if not self.input_handler:
            return

        # Check if all active controllers have voted
        active_controllers = set(self.input_handler.controllers.keys())
        voted_controllers = set(self.voting_states.keys())
        if not active_controllers.issubset(voted_controllers):
            return  # Not all controllers have voted yet

        # All players have voted
        vote_counts = {game: 0 for game in self.available_games}
        for vote in self.menu_votes.values():
            if vote is not None:
                vote_counts[vote] += 1

        # Find highest vote count
        max_votes = max(vote_counts.values())
        # Get all games with max votes
        max_games = [g for g, v in vote_counts.items() if v == max_votes]
        # Randomly select from tied games
        selected_game = random.choice(max_games)

        # Create new game instance
        game_class = self.available_games[selected_game]
        self.current_game = game_class(
            width=self.width,
            height=self.height,
            length=self.length,
            frameRate=self.frameRate,
            config=self.config,
            input_handler=self.input_handler
        )

        # Set difficulty for snake game
        if hasattr(self.current_game, 'set_difficulty') and self.difficulty is not None:
            self.current_game.set_difficulty(self.difficulty)

        # Start countdown
        self.menu_active = False
        self.countdown_active = True
        self.countdown_value = 3
        self.last_countdown_time = current_time
        self.input_handler.clear_all_select_holds()

    def process_menu_input(self, player_id, action):
        """Process menu-related input."""
        if not self.input_handler:
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
                selected_game = list(self.available_games.keys())[selection]
                self.menu_votes[controller_id] = selected_game
                self.voting_states[controller_id] = True
        elif action == Button.UP:
            # Move selection up with wraparound
            current = self.menu_selections.get(controller_id, 0)
            self.menu_selections[controller_id] = (current - 1) % len(self.available_games)
            # If player was in voting state, remove their vote
            if controller_id in self.voting_states and self.voting_states[controller_id]:
                self.voting_states[controller_id] = False
                self.menu_votes.pop(controller_id, None)
        elif action == Button.DOWN:
            # Move selection down with wraparound
            current = self.menu_selections.get(controller_id, 0)
            self.menu_selections[controller_id] = (current + 1) % len(self.available_games)
            # If player was in voting state, remove their vote
            if controller_id in self.voting_states and self.voting_states[controller_id]:
                self.voting_states[controller_id] = False
                self.menu_votes.pop(controller_id, None)

    def cleanup(self):
        """Clean up resources."""
        print("Cleaning up game...")
        if self.input_handler:
            self.input_handler.stop() 