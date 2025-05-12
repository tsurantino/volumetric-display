from base_game import BaseGame, PlayerID, TeamID, Difficulty, RGB
from collections import deque
import random
import time

class SnakeGame(BaseGame):
    def __init__(self, width=20, height=20, length=20, frameRate=30, input_handler_type='controller', config=None):
        super().__init__(width, height, length, frameRate, input_handler_type, config)
        self.snakes = {}  # Maps player_id to snake body (deque of positions)
        self.food = None
        self.food_color = RGB(255, 0, 0)  # Red food
        self.snake_colors = {
            TeamID.BLUE: RGB(0, 0, 255),    # Blue snake
            TeamID.ORANGE: RGB(255, 165, 0)  # Orange snake
        }
        self.last_step_time = 0  # Track last game step update
        self.step_rate = 3  # Default to 3 steps per second (MEDIUM/HARD)
        self.reset_game()

    def reset_game(self):
        """Reset the game state."""
        self.snakes = {}
        self.food = None
        self.game_over_active = False
        self.game_over_flash_state = {'count': 0, 'timer': 0, 'interval': 0.2, 'border_on': False}
        self.last_step_time = 0
        self.step_rate = 3  # Reset to default step rate

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

    def process_player_input(self, player_id, action):
        """Process input from a player."""
        if self.game_over_active:
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

    def set_difficulty(self, difficulty):
        """Set the game difficulty and adjust step rate."""
        if difficulty == Difficulty.EASY:
            self.step_rate = 1  # 1 step per second
        else:  # MEDIUM or HARD
            self.step_rate = 3  # 3 steps per second

    def update_game_state(self):
        """Update the game state."""
        current_time = time.monotonic()

        # Only update snake positions at the step rate
        if current_time - self.last_step_time >= 1.0/self.step_rate:
            self.last_step_time = current_time
            if not self.game_over_active:
                # Update both snakes
                self.update_snake('blue')
                self.update_snake('orange')

        # Update game over flash state (this can run at frame rate)
        if self.game_over_active:
            if current_time - self.game_over_flash_state['timer'] >= self.game_over_flash_state['interval']:
                self.game_over_flash_state['timer'] = current_time
                self.game_over_flash_state['border_on'] = not self.game_over_flash_state['border_on']
                self.game_over_flash_state['count'] += 1

    def render_game_state(self, raster):
        """Render the game state to the raster."""
        # Draw food
        if self.food:
            x, y, z = self.food
            raster.set_pix(x, y, z, self.food_color)

        # Draw snakes
        for player_id, snake in self.snakes.items():
            config = self.get_player_config(player_id)
            team = config['team']
            color = self.snake_colors[team]
            for pos in snake:
                x, y, z = pos
                raster.set_pix(x, y, z, color)

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