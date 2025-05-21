from artnet import Scene, RGB
from games.util.game_util import ControllerInputHandler, DisplayManager, Button, Direction, ButtonState
import time
import random
from enum import Enum

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

class BaseGame:
    def __init__(self, width=20, height=20, length=20, frameRate=3, config=None, input_handler=None):
        self.width = width
        self.height = height
        self.length = length
        self.frameRate = frameRate
        self.base_frame_rate = frameRate  # Store original frame rate
        self.config = config
        self.input_handler = input_handler

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
                        role_upper = role.upper()
                        player_id = PlayerID[role_upper]
                        self.controller_mapping[dip] = player_id
                    except KeyError:
                        print(f"BaseGame: Warning: Unknown player role '{role}' in controller mapping")

        self.display_manager = DisplayManager()
        self.last_update_time = 0
        self.last_countdown_time = 0
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}
        self.menu_active = True
        self.countdown_active = False
        self.countdown_value = None
        self.difficulty = None

        # Register button callbacks for all controllers if input_handler is provided
        if self.input_handler and isinstance(self.input_handler, ControllerInputHandler):
            for controller_id in self.input_handler.controllers:
                self.input_handler.register_button_callback(controller_id, self.handle_button_event)

        self.reset_game()

    def handle_button_event(self, player_id, button, button_state):
        """Handle button events with state information.
        
        This is the new callback-based approach that provides both press and release events.
        Games should override this method to handle button events.
        
        Args:
            player_id: PlayerID enum value
            button: Button enum value
            button_state: ButtonState enum value (PRESSED, RELEASED, HELD)
        """
        # Default implementation that routes to the old-style methods for backward compatibility
        if self.menu_active:
            # In menu mode, handle menu input
            if button_state == ButtonState.PRESSED:
                if button == Button.UP:
                    self.process_menu_input(player_id, Button.UP)
                elif button == Button.DOWN:
                    self.process_menu_input(player_id, Button.DOWN)
                elif button == Button.SELECT:
                    self.process_menu_input(player_id, Button.SELECT)
        else:
            # In game mode, directly pass all button events to process_player_input
            self.process_player_input(player_id, button, button_state)

    def get_player_config(self, player_id):
        """Get the configuration for a player."""
        return PLAYER_CONFIG[player_id]

    def get_player_score(self, player_id):
        """Get the score for a player."""
        raise NotImplementedError("Subclasses must implement get_player_score")

    def get_opponent_score(self, player_id):
        """Get the score for a player's opponent."""
        raise NotImplementedError("Subclasses must implement get_opponent_score")

    def reset_game(self):
        """Reset the game state."""
        raise NotImplementedError("Subclasses must implement reset_game")

    def process_player_input(self, player_id, button, button_state):
        """Process input from a player.
        
        Args:
            player_id: PlayerID enum value
            button: Button enum value (UP, DOWN, LEFT, RIGHT, SELECT)
            button_state: ButtonState enum value (PRESSED, RELEASED, HELD)
        """
        raise NotImplementedError("Subclasses must implement process_player_input")

    def process_menu_input(self, player_id, action):
        """Process menu input from a player.
        This is used for game-specific menus, not the game selection menu.
        """
        # Default implementation does nothing
        pass

    def update_game_state(self):
        """Update the game state."""
        raise NotImplementedError("Subclasses must implement update_game_state")

    def render_game_state(self, raster):
        """Render the game state to the raster."""
        raise NotImplementedError("Subclasses must implement render_game_state")

    def cleanup(self):
        """Clean up resources."""
        print("Cleaning up game...")
        if isinstance(self.input_handler, ControllerInputHandler):
            # Unregister callbacks
            for controller_id in self.input_handler.controllers:
                self.input_handler.unregister_button_callback(controller_id)
            # Stop the input handler
            self.input_handler.stop() 