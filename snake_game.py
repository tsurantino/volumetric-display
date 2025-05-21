from base_game import BaseGame, PlayerID, TeamID, Difficulty, RGB
from collections import deque
import random
import time
from game_util import ControllerInputHandler, Button, Direction

class SnakeGame(BaseGame):
    def __init__(self, width=20, height=20, length=20, frameRate=30, config=None, input_handler=None):
        self.thickness = 2  # Each snake segment is 2x2x2 voxels
        self.width = width // self.thickness
        self.height = height // self.thickness
        self.length = length // self.thickness
        super().__init__(width, height, length, frameRate, config=config, input_handler=input_handler)
        self.snakes = {}  # Maps player_id to snake body (deque of positions)
        self.food = None
        self.food_color = RGB(255, 0, 0)  # Red food
        self.snake_colors = {
            TeamID.BLUE: RGB(0, 0, 255),    # Blue snake
            TeamID.ORANGE: RGB(255, 165, 0)  # Orange snake
        }
        self.last_step_time = 0  # Track last game step update
        self.step_rate = 3  # Default to 3 steps per second (MEDIUM/HARD)
        
        # Menu-related attributes
        self.menu_active = True
        self.countdown_active = False
        self.countdown_value = None
        self.difficulty = None
        self.menu_selections = {}  # Maps controller_id to their current selection (0=EASY, 1=MEDIUM, 2=HARD)
        self.menu_votes = {}  # Maps controller_id to their difficulty vote
        self.voting_states = {}  # Maps controller_id to whether they have voted
        self.last_countdown_time = 0
        self.game_started = False  # Track whether the game has started
        
        self.reset_game()

    def reset_game(self):
        """Reset the game state."""
        self.snakes = {}
        self.food = None
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}
        self.last_step_time = 0
        self.step_rate = 3  # Reset to default step rate
        self.game_started = False  # Reset game started state
        self.menu_active = True  # Start in menu state
        self.countdown_active = False
        self.countdown_value = None
        self.difficulty = None
        self.menu_selections.clear()
        self.menu_votes.clear()
        self.voting_states.clear()

        # Initialize snakes for each player
        for player_id in PlayerID:
            config = self.get_player_config(player_id)
            team = config['team']
            view = config['view']
            
            # Start position based on view direction
            if view[0] != 0:  # X view
                start_x = 0 if view[0] < 0 else self.width - 1
                start_y = self.height // 2
                start_z = self.length // 2
                direction = (-view[0], 0, 0)  # Move in opposite direction of view
            else:  # Y view
                start_x = self.width // 2
                start_y = 0 if view[1] < 0 else self.height - 1
                start_z = self.length // 2
                direction = (0, -view[1], 0)  # Move in opposite direction of view

            # Initialize snake with 3 segments
            snake = deque()
            for i in range(3):
                pos = (
                    start_x + direction[0] * i,
                    start_y + direction[1] * i,
                    start_z + direction[2] * i
                )
                snake.append(pos)
            self.snakes[player_id] = snake

        # Spawn initial food
        self.spawn_food()

    def spawn_food(self):
        """Spawn food at a random location."""
        while True:
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            z = random.randint(0, self.length - 1)
            pos = (x, y, z)
            
            # Check if position is not occupied by any snake
            if not any(pos in snake for snake in self.snakes.values()):
                self.food = pos
                break

    def get_player_score(self, player_id):
        """Get the score for a player."""
        return len(self.snakes[player_id])

    def get_opponent_score(self, player_id):
        """Get the score for a player's opponent."""
        config = self.get_player_config(player_id)
        team = config['team']
        opponent_team = TeamID.ORANGE if team == TeamID.BLUE else TeamID.BLUE
        
        # Sum up scores of all players on the opponent's team
        total_score = 0
        for pid, snake in self.snakes.items():
            if self.get_player_config(pid)['team'] == opponent_team:
                total_score += len(snake)
        return total_score

    def select_difficulty(self):
        """Handle difficulty selection and voting."""
        if not self.input_handler or not hasattr(self.input_handler, 'controllers'):
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
            self.step_rate = 1  # 1 step per second
        else:
            self.step_rate = 3  # 3 steps per second

        # Start countdown
        self.menu_active = False
        self.countdown_active = True
        self.countdown_value = 3
        self.last_countdown_time = time.monotonic()

    def process_menu_input(self, player_id, action):
        """Process menu-related input."""
        if not self.input_handler or not hasattr(self.input_handler, 'controllers'):
            return

        try:
            controller_id = next(cid for cid, (_, pid) in self.input_handler.controllers.items() if pid == player_id)
        except StopIteration:
            return  # No matching controller found
        
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

    def update_game_state(self):
        """Update the game state."""
        current_time = time.monotonic()

        # Handle menu and countdown
        if self.menu_active:
            self.select_difficulty()
        elif self.countdown_active:
            # Decrement countdown every second
            if current_time - self.last_countdown_time >= 1.0:
                self.countdown_value -= 1
                self.last_countdown_time = current_time
                if self.countdown_value <= 0:
                    self.countdown_active = False
                    self.game_started = True
                    print("Game started!")  # Debug log

        # Only update snake positions at the step rate if game has started
        if self.game_started and not self.game_over_active:
            if current_time - self.last_step_time >= 1.0/self.step_rate:
                self.last_step_time = current_time
                # Update all snakes
                for player_id in PlayerID:
                    if player_id in self.snakes:
                        snake = self.snakes[player_id]
                        if len(snake) > 1:
                            head = snake[0]
                            # Get current direction
                            current_dir = (
                                head[0] - snake[1][0],
                                head[1] - snake[1][1],
                                head[2] - snake[1][2]
                            )
                            # Calculate new head position
                            new_head = (
                                head[0] + current_dir[0],
                                head[1] + current_dir[1],
                                head[2] + current_dir[2]
                            )
                            # Check for collisions
                            if (new_head[0] < 0 or new_head[0] >= self.width or
                                new_head[1] < 0 or new_head[1] >= self.height or
                                new_head[2] < 0 or new_head[2] >= self.length):
                                self.game_over_active = True
                                return

                            # Check for self-collision
                            if new_head in snake:
                                self.game_over_active = True
                                return

                            # Check for collision with other snakes
                            for other_id, other_snake in self.snakes.items():
                                if other_id != player_id and new_head in other_snake:
                                    self.game_over_active = True
                                    return

                            # Move snake
                            snake.appendleft(new_head)

                            # Check for food collision
                            if new_head == self.food:
                                self.spawn_food()
                            else:
                                snake.pop()

        # Update game over flash state (this can run at frame rate)
        if self.game_over_active:
            if current_time - self.game_over_flash_state['timer'] >= self.game_over_flash_state['interval']:
                self.game_over_flash_state['timer'] = current_time
                self.game_over_flash_state['border_on'] = not self.game_over_flash_state['border_on']
                self.game_over_flash_state['count'] += 1

    def render_game_state(self, raster):
        """Render the game state to the raster."""
        # Clear the raster first
        for x in range(raster.width):
            for y in range(raster.height):
                for z in range(raster.length):
                    raster.set_pix(x, y, z, RGB(0, 0, 0))  # Black background

        # Draw food
        if self.food:
            x, y, z = self.food
            x *= self.thickness
            y *= self.thickness
            z *= self.thickness
            for dx in range(self.thickness):
                for dy in range(self.thickness):
                    for dz in range(self.thickness):
                        if (x+dx < raster.width and 
                            y+dy < raster.height and 
                            z+dz < raster.length):
                            raster.set_pix(x+dx, y+dy, z+dz, self.food_color)

        # Draw snakes
        for player_id, snake in self.snakes.items():
            config = self.get_player_config(player_id)
            team = config['team']
            color = self.snake_colors[team]
            for i, pos in enumerate(snake):
                x, y, z = pos
                x *= self.thickness
                y *= self.thickness
                z *= self.thickness
                for dx in range(self.thickness):
                    for dy in range(self.thickness):
                        for dz in range(self.thickness):
                            if (x+dx < raster.width and 
                                y+dy < raster.height and 
                                z+dz < raster.length):
                                if i == 0:  # Head
                                    raster.set_pix(x+dx, y+dy, z+dz, RGB(255, 0, 0))  # Red head
                                else:  # Body
                                    raster.set_pix(x+dx, y+dy, z+dz, color)

        # Draw game over border
        if self.game_over_active and self.game_over_flash_state['border_on']:
            border_color = RGB(255, 0, 0)  # Red border
            for x in range(raster.width):
                for y in range(raster.height):
                    for z in range(raster.length):
                        if (x == 0 or x == raster.width-1 or
                            y == 0 or y == raster.height-1 or
                            z == 0 or z == raster.length-1):
                            raster.set_pix(x, y, z, border_color)

    def process_player_input(self, player_id, action):
        """Process input from a player."""
        if self.game_over_active:
            return

        if self.menu_active:
            self.process_menu_input(player_id, action)
            return

        if not self.game_started:
            return

        config = self.get_player_config(player_id)
        snake = self.snakes[player_id]
        head = snake[0]

        # Get current direction
        if len(snake) > 1:
            current_dir = (
                head[0] - snake[1][0],
                head[1] - snake[1][1],
                head[2] - snake[1][2]
            )
        else:
            # If snake is length 1, use view direction
            current_dir = (-config['view'][0], -config['view'][1], 0)

        # Calculate new direction based on input
        if action == Button.UP:
            new_dir = config['up_dir']
        elif action == Button.DOWN:
            new_dir = config['down_dir']
        elif action == Button.LEFT:
            new_dir = config['left_dir']
        elif action == Button.RIGHT:
            new_dir = config['right_dir']
        else:
            return

        # Don't allow 180-degree turns
        if (current_dir[0] == -new_dir[0] and
            current_dir[1] == -new_dir[1] and
            current_dir[2] == -new_dir[2]):
            return

        # Calculate new head position
        new_head = (
            head[0] + new_dir[0],
            head[1] + new_dir[1],
            head[2] + new_dir[2]
        )

        # Check for collisions
        if (new_head[0] < 0 or new_head[0] >= self.width or
            new_head[1] < 0 or new_head[1] >= self.height or
            new_head[2] < 0 or new_head[2] >= self.length):
            self.game_over_active = True
            return

        # Check for self-collision
        if new_head in snake:
            self.game_over_active = True
            return

        # Check for collision with other snakes
        for other_id, other_snake in self.snakes.items():
            if other_id != player_id and new_head in other_snake:
                self.game_over_active = True
                return

        # Move snake
        snake.appendleft(new_head)

        # Check for food collision
        if new_head == self.food:
            self.spawn_food()
        else:
            snake.pop() 