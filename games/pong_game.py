from games.util.base_game import BaseGame, PlayerID, TeamID, RGB
from games.util.game_util import Button, ButtonState
from dataclasses import dataclass, field
from typing import Dict, List, Set
import random, math, time

# ----------------------------
# Basic config
# ----------------------------

JOIN_WINDOW = 10.0  # seconds to join before game starts
PADDLE_SIZE = 2     # half-size (extent) of paddle square in voxels
BALL_SPEED = 20.0   # constant ball speed voxels/second
BALL_RADIUS = 1.5
PADDLE_MOVE_SPEED = 30.0  # voxels per second for smooth movement
SPIKE_TIME_WINDOW = 0.1  # seconds after bounce in which a SELECT press counts as a spike
SPIKE_STRENGTH = 0.5     # how strongly paddle motion influences spike
WIN_SCORE = 11           # points needed to win a game

PLAYER_FACE = {
    PlayerID.P1: 'x-',   # -X face
    PlayerID.P2: 'y-',   # -Y
    PlayerID.P3: 'x+', # +X
    PlayerID.P4: 'y+'  # +Y
}
PLAYER_TEAM = {
    PlayerID.P1: TeamID.RED,
    PlayerID.P2: TeamID.ORANGE,
    PlayerID.P3: TeamID.GREEN,
    PlayerID.P4: TeamID.BLUE
}

# Tennis score progression
TENNIS_ORDER = ['LOVE','15','30','40','A','WIN']

def next_tennis_score(cur):
    idx = TENNIS_ORDER.index(cur)
    return TENNIS_ORDER[min(idx+1,len(TENNIS_ORDER)-1)]

@dataclass
class Paddle:
    cx: float
    cy: float
    face: str
    player: PlayerID
    held_dirs: Set[Button] = field(default_factory=set)
    last_select_press: float = -math.inf  # time of last SELECT press
    last_move_dx: float = 0.0  # last frame movement dir in first axis of face
    last_move_dy: float = 0.0  # last frame movement dir in second axis of face

@dataclass
class Ball:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    attached_to: PlayerID|None = None  # if serving

# Particle for explosions
@dataclass
class Particle:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    birth: float
    lifetime: float
    color: RGB
    radius: float = 0.5

    AIR_DAMP=0.98

    def update(self,dt):
        self.x+=self.vx*dt
        self.y+=self.vy*dt
        self.z+=self.vz*dt
        self.vx*=self.AIR_DAMP
        self.vy*=self.AIR_DAMP
        self.vz*=self.AIR_DAMP

    def expired(self,t):
        return t-self.birth>self.lifetime

class PongGame(BaseGame):
    def __init__(self,width=20,height=20,length=20,frameRate=30,config=None,input_handler=None):
        super().__init__(width,height,length,frameRate,config,input_handler)
        self.game_phase = 'lobby' # lobby, running, gameover
        self.join_deadline = time.monotonic()+JOIN_WINDOW
        self.active_players:Set[PlayerID]=set()
        self.paddles:Dict[PlayerID,Paddle]={}
        self.ball:Ball|None=None
        self.server:PlayerID|None=None
        self.scores:Dict[PlayerID,str]={pid:0 for pid in PlayerID}
        self.particles:List[Particle]=[]
        self.reset_game()

    def reset_game(self):
        self.game_phase='lobby'
        self.join_deadline = time.monotonic()+JOIN_WINDOW
        self.active_players=set()
        self.paddles={}
        self.ball=None
        self.server=None
        self.scores={pid:0 for pid in PlayerID}
        self.particles=[]

    # Utility to place paddle at center
    def _default_paddle(self,pid):
        face=PLAYER_FACE[pid]
        if face in ['x-','x+']:
            cx=self.height/2
            cy=self.length/2
        else:
            cx=self.width/2
            cy=self.length/2
        return Paddle(cx,cy,face,pid)

    def process_player_input(self,player_id,button,button_state):
        # Track held dirs
        if player_id in self.paddles:
            pad=self.paddles[player_id]
            if button==Button.SELECT and button_state==ButtonState.PRESSED:
                pad.last_select_press=time.monotonic()
            if button in {Button.LEFT,Button.RIGHT,Button.UP,Button.DOWN}:
                if button_state==ButtonState.PRESSED:
                    pad.held_dirs.add(button)
                elif button_state==ButtonState.RELEASED:
                    pad.held_dirs.discard(button)

        if button_state!=ButtonState.PRESSED:
            return
        # Lobby join
        if self.game_phase=='lobby':
            if button==Button.SELECT:
                if player_id not in self.active_players:
                    self.active_players.add(player_id)
                    self.paddles[player_id]=self._default_paddle(player_id)
                # Start if 4 players
                if len(self.active_players)==4:
                    self._start_match()
            return
        # Running phase
        if self.game_phase!='running' or player_id not in self.active_players:
            return
        pad=self.paddles[player_id]
        # Immediate directional bump still
        dx=dy=0
        if button==Button.LEFT:
            dx=-1
        elif button==Button.RIGHT:
            dx=1
        elif button==Button.UP:
            dy=1
        elif button==Button.DOWN:
            dy=-1
        # Small nudge so tap feels responsive (one voxel)
        pad.cx+=dx
        pad.cy+=dy
        # clamp to face bounds 0-7
        self._clamp_paddle(pad)
        pad.last_move_dx=dx  # record movement direction this frame
        pad.last_move_dy=dy
        if button==Button.SELECT and self.server==player_id and self.ball and self.ball.attached_to==player_id:
            # Serve
            self._launch_ball_from(pad)

    def _start_match(self):
        self.game_phase='running'
        self.server=random.choice(list(self.active_players))
        self.ball=Ball(0,0,0,0,0,0,attached_to=self.server)
        self._attach_ball_to_paddle()

    def _attach_ball_to_paddle(self):
        if not self.ball:return
        pad=self.paddles[self.ball.attached_to]
        face=pad.face
        if face=='x-':
            self.ball.x=BALL_RADIUS
            self.ball.y=pad.cx
            self.ball.z=pad.cy
        elif face=='x+':
            self.ball.x=self.width-1-BALL_RADIUS
            self.ball.y=pad.cx
            self.ball.z=pad.cy
        elif face=='y-':
            self.ball.y=BALL_RADIUS
            self.ball.x=pad.cx
            self.ball.z=pad.cy
        else:
            self.ball.y=self.height-1-BALL_RADIUS
            self.ball.x=pad.cx
            self.ball.z=pad.cy
        self.ball.vx=self.ball.vy=self.ball.vz=0

    def _launch_ball_from(self,pad:Paddle):
        # direction bias from last movement? simplify random
        dir_vector=[random.choice([-1,1]) for _ in range(3)]
        if pad.face in ['x-','x+']:
            dir_vector[0]=1 if pad.face=='x-' else -1
        else:
            dir_vector[1]=1 if pad.face=='y-' else -1
        norm=math.sqrt(dir_vector[0]**2+dir_vector[1]**2+dir_vector[2]**2)
        self.ball.vx=BALL_SPEED*dir_vector[0]/norm
        self.ball.vy=BALL_SPEED*dir_vector[1]/norm
        self.ball.vz=BALL_SPEED*dir_vector[2]/norm
        self.ball.attached_to=None

    def update_game_state(self):
        current=time.monotonic()
        if self.game_phase=='lobby':
            if current>=self.join_deadline and self.active_players:
                self._start_match()
            return
        if self.game_phase!='running':
            return
        dt=1.0/self.frameRate
        # Smooth paddle movement for held directions
        for pad in self.paddles.values():
            dx=dy=0
            if Button.LEFT in pad.held_dirs:
                dx-=1
            if Button.RIGHT in pad.held_dirs:
                dx+=1
            if Button.UP in pad.held_dirs:
                dy+=1
            if Button.DOWN in pad.held_dirs:
                dy-=1
            pad.cx+=dx*PADDLE_MOVE_SPEED*dt
            pad.cy+=dy*PADDLE_MOVE_SPEED*dt
            pad.last_move_dx=dx  # record movement direction this frame
            pad.last_move_dy=dy
            self._clamp_paddle(pad)

        # Keep ball attached to paddle before serve
        if self.ball and self.ball.attached_to is not None:
            self._attach_ball_to_paddle()

        # move ball
        if self.ball and not self.ball.attached_to:
            self.ball.x+=self.ball.vx*dt
            self.ball.y+=self.ball.vy*dt
            self.ball.z+=self.ball.vz*dt
            # Bounce floor/ceiling (z axis) considering radius
            if self.ball.z<=BALL_RADIUS:
                self.ball.z=BALL_RADIUS
                self.ball.vz*=-1
            elif self.ball.z>=self.length-1-BALL_RADIUS:
                self.ball.z=self.length-1-BALL_RADIUS
                self.ball.vz*=-1
            # Check faces
            if self.ball.x<=BALL_RADIUS:
                self._handle_face('x-',BALL_RADIUS)
            elif self.ball.x>=self.width-1-BALL_RADIUS:
                self._handle_face('x+',self.width-1-BALL_RADIUS)
            if self.ball.y<=BALL_RADIUS:
                self._handle_face('y-',BALL_RADIUS,axis='y')
            elif self.ball.y>=self.height-1-BALL_RADIUS:
                self._handle_face('y+',self.height-1-BALL_RADIUS,axis='y')

        # update particles
        new_parts=[]
        for p in self.particles:
            if p.expired(current):
                continue
            p.update(dt)
            if 0<=p.x<self.width and 0<=p.y<self.height and 0<=p.z<self.length:
                new_parts.append(p)
        self.particles=new_parts

    def _handle_face(self,face,bound,axis='x'):
        if face in [pad.face for pad in self.paddles.values()]:
            # find player
            player=[pid for pid,p in self.paddles.items() if p.face==face][0]
            pad=self.paddles[player]
            # compute hit against paddle area
            dx= self.ball.y - pad.cx if axis=='x' else self.ball.x - pad.cx
            dy= self.ball.z - pad.cy
            if abs(dx)<=PADDLE_SIZE+BALL_RADIUS and abs(dy)<=PADDLE_SIZE+BALL_RADIUS:
                # bounce
                if axis=='x':
                    self.ball.vx*=-1
                    # Reposition ball just inside play area
                    self.ball.x = BALL_RADIUS if face=='x-' else self.width-1-BALL_RADIUS
                else:
                    self.ball.vy*=-1
                    self.ball.y = BALL_RADIUS if face=='y-' else self.height-1-BALL_RADIUS
                # Possible spike redirect
                self._apply_spike(pad,axis)
                return
            else:
                # miss -> point to server
                scorer=self.server  # keep the serving player for explosion color
                self.scores[scorer]+=1
                # explosion with scorer color
                self._spawn_explosion(self.ball.x,self.ball.y,self.ball.z,PLAYER_TEAM[scorer].get_color())
                # check game over
                if self.scores[scorer]>=WIN_SCORE:
                    self.game_phase='gameover'
                    self.game_over_active=True
                    max_score=max(self.scores.values())
                    self.winner_players=[pid for pid,sc in self.scores.items() if sc==max_score]
                # new server becomes player who missed
                self.server=player
                self.ball.attached_to=self.server
                self._attach_ball_to_paddle()
                return
        # wall bounce
        if axis=='x':
            self.ball.vx*=-1
            self.ball.x = BALL_RADIUS if face=='x-' else self.width-1-BALL_RADIUS
        else:
            self.ball.vy*=-1
            self.ball.y = BALL_RADIUS if face=='y-' else self.height-1-BALL_RADIUS

    def get_player_score(self,player_id):
        return self.scores.get(player_id,0)

    def get_opponent_score(self,player_id):
        return max((score for pid,score in self.scores.items() if pid!=player_id), default=0)

    def render_game_state(self,raster):
        # Draw paddles
        for pid,pad in self.paddles.items():
            col=PLAYER_TEAM[pid].get_color()
            for u in range(-PADDLE_SIZE,PADDLE_SIZE+1):
                for v in range(-PADDLE_SIZE,PADDLE_SIZE+1):
                    if pad.face=='x-':
                        x=0
                        y=int(round(pad.cx+u))
                        z=int(round(pad.cy+v))
                    elif pad.face=='x+':
                        x=self.width-1
                        y=int(round(pad.cx+u))
                        z=int(round(pad.cy+v))
                    elif pad.face=='y-':
                        y=0
                        x=int(round(pad.cx+u))
                        z=int(round(pad.cy+v))
                    else: # y+
                        y=self.height-1
                        x=int(round(pad.cx+u))
                        z=int(round(pad.cy+v))
                    if 0<=x<self.width and 0<=y<self.height and 0<=z<self.length:
                        raster.set_pix(x,y,z,col)

        # Draw ball
        if self.ball:
            bx,by,bz=self.ball.x,self.ball.y,self.ball.z
            radius=BALL_RADIUS
            minx=int(math.floor(bx-radius))
            maxx=int(math.ceil(bx+radius))
            miny=int(math.floor(by-radius))
            maxy=int(math.ceil(by+radius))
            minz=int(math.floor(bz-radius))
            maxz=int(math.ceil(bz+radius))
            for x in range(minx,maxx+1):
                for y in range(miny,maxy+1):
                    for z in range(minz,maxz+1):
                        if 0<=x<self.width and 0<=y<self.height and 0<=z<self.length:
                            if (x+0.5-bx)**2+(y+0.5-by)**2+(z+0.5-bz)**2<=radius**2:
                                raster.set_pix(x,y,z,RGB(255,255,255))

        # Draw particles
        for p in self.particles:
            vx=int(round(p.x))
            vy=int(round(p.y))
            vz=int(round(p.z))
            if 0<=vx<self.width and 0<=vy<self.height and 0<=vz<self.length:
                raster.set_pix(vx,vy,vz,p.color)

    def _spawn_explosion(self,x,y,z,color,count=30):
        for _ in range(count):
            speed=random.uniform(5,20)
            theta=random.uniform(0,2*math.pi)
            phi=random.uniform(0,math.pi)
            vx=speed*math.sin(phi)*math.cos(theta)
            vy=speed*math.sin(phi)*math.sin(theta)
            vz=speed*math.cos(phi)
            self.particles.append(Particle(x,y,z,vx,vy,vz,time.monotonic(),2.0,color))

    def _clamp_paddle(self,pad:Paddle):
        # Ensure paddle remains within bounds considering size
        if pad.face in ['x-','x+']:
            max_cx=self.height-1-PADDLE_SIZE
            max_cy=self.length-1-PADDLE_SIZE
        else:
            max_cx=self.width-1-PADDLE_SIZE
            max_cy=self.length-1-PADDLE_SIZE
        pad.cx=max(PADDLE_SIZE,min(max_cx,pad.cx))
        pad.cy=max(PADDLE_SIZE,min(max_cy,pad.cy))

    def _apply_spike(self,pad:Paddle,axis:str):
        """Apply spike redirection if SELECT was recently pressed."""
        if time.monotonic()-pad.last_select_press>SPIKE_TIME_WINDOW:
            return
        # Direction components from paddle motion
        movx, movy = pad.last_move_dx, pad.last_move_dy
        if movx==0 and movy==0:
            return
        # Apply to ball velocity
        if axis=='x':
            self.ball.vy += movx * BALL_SPEED * SPIKE_STRENGTH
            self.ball.vz += movy * BALL_SPEED * SPIKE_STRENGTH
        else:  # axis=='y'
            self.ball.vx += movx * BALL_SPEED * SPIKE_STRENGTH
            self.ball.vz += movy * BALL_SPEED * SPIKE_STRENGTH
        # Renormalize to constant speed
        speed=math.sqrt(self.ball.vx**2+self.ball.vy**2+self.ball.vz**2)
        if speed>0:
            scale=BALL_SPEED/speed
            self.ball.vx*=scale
            self.ball.vy*=scale
            self.ball.vz*=scale

    async def update_controller_display_state(self, controller_state, player_id):
        """Update the LCD for this player according to game phase."""
        current=time.monotonic()
        controller_state.clear()
        if self.game_phase=='lobby':
            remaining=max(0,int(self.join_deadline-current))
            controller_state.write_lcd(0,0,"PONG LOBBY")
            controller_state.write_lcd(0,1,f"Players: {len(self.active_players)}/4")
            controller_state.write_lcd(0,2,f"Start in: {remaining}s")
            controller_state.write_lcd(0,3,"Press SELECT")
        elif self.game_phase=='running':
            all_scores_same = True
            score=self.get_player_score(player_id)
            for pid in self.active_players:
                if score != self.get_player_score(pid):
                    all_scores_same = False
                    break
                
            my_score=TENNIS_ORDER[self.get_player_score(player_id)] + (" ALL" if all_scores_same else "")
            opp_score=TENNIS_ORDER[self.get_opponent_score(player_id)]
            controller_state.write_lcd(0,0,f"PLAYER {player_id.name}")
            controller_state.write_lcd(0,1,f"     YOU: {my_score}")
            controller_state.write_lcd(0,2,f"BEST OPP: {opp_score}")
            controller_state.write_lcd(0,3,"")
        elif self.game_phase=='gameover':
            max_score=max(self.scores.values())
            winners=[pid for pid,score in self.scores.items() if score==max_score]
            header="WINNERS" if len(winners)>1 else "WINNER"
            names=",".join([pid.name for pid in winners])
            controller_state.write_lcd(0,0,"GAME OVER")
            controller_state.write_lcd(0,1,f"{header}: ")
            controller_state.write_lcd(0,2,names[:20])
            controller_state.write_lcd(0,3,"Hold SELECT to EXIT")
        else:
            controller_state.write_lcd(0,0,"PONG")
        await controller_state.commit() 