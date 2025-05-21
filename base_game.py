from artnet import Scene, RGB
from game_util import ControllerInputHandler, DisplayManager, Button, Direction
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

        self.reset_game()

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

    def process_player_input(self, player_id, action):
        """Process input from a player."""
        raise NotImplementedError("Subclasses must implement process_player_input")

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
            self.input_handler.stop() 