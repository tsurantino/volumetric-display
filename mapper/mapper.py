import argparse
import logging
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
import rtmidi
import threading

NUM_ROWS = 8
NUM_COLS = 8
# Bank switching additions
NUM_LFO_BANKS = 4
NUM_EFFECT_BANKS = 4
TOTAL_ROWS = NUM_ROWS * NUM_LFO_BANKS
TOTAL_COLS = NUM_COLS * NUM_EFFECT_BANKS

# APC MINI LED Velocities (examples, adjust as needed for your device)
LED_OFF = 0
LED_GREEN = 1       # Standard active mapping
LED_RED = 3         # LFO mapping overridden by fader
LED_ORANGE = 5      # Active LFO bank button
LED_BLUE_ISH = 6    # Active Effect bank button (e.g., Yellow Blink on some APCs)

NOTE_GRID = [[r + c for c in range(NUM_COLS)] for r in range(NUM_ROWS)]
for r in range(NUM_ROWS):
    for c in range(NUM_COLS):
        NOTE_GRID[r][c] = (NUM_ROWS - 1 - r) * 8 + c  # MIDI notes

class ControlMapper:
    def __init__(self, in_host: str = "127.0.0.1", in_port: int = 9000, out_host: str = "127.0.0.1", out_port: int = 9001):
        self.current_lfo_bank = 0
        self.current_effect_bank = 0

        self.mapping = [[False] * TOTAL_COLS for _ in range(TOTAL_ROWS)]
        self.frozen_outputs = [0.0] * TOTAL_COLS
        self.midi_out = None # Initialize midi_out
        self.fader_override_active = [False] * TOTAL_COLS # For fader override
        self.fader_override_value = [0.0] * TOTAL_COLS  # Stores last fader value

        self.in_host = in_host
        self.in_port = in_port
        self.out_host = out_host
        self.out_port = out_port
        self.osc_client = SimpleUDPClient(self.out_host, self.out_port)

        self.setup_osc()
        self.setup_midi()

    def setup_osc(self):
        self.dispatcher = Dispatcher()
        for row in range(NUM_ROWS):
            self.dispatcher.map(f"/lfo/{row+1}", self.handle_lfo, row)

        self.osc_server = ThreadingOSCUDPServer((self.in_host, self.in_port), self.dispatcher)
        threading.Thread(target=self.osc_server.serve_forever, daemon=True).start()

    def _update_bank_select_leds(self):
        if not self.midi_out:
            return

        # LFO Bank LEDs (Notes 82-85)
        for i in range(NUM_LFO_BANKS):
            note = 82 + i
            velocity = LED_ORANGE if i == self.current_lfo_bank else LED_OFF
            self.midi_out.send_message([0x90, note, velocity])
            #logging.debug(f"Set LFO Bank {i} LED (Note {note}) to Vel {velocity}")

        # Effect Bank LEDs (Notes 86-89)
        for i in range(NUM_EFFECT_BANKS):
            note = 86 + i
            velocity = LED_BLUE_ISH if i == self.current_effect_bank else LED_OFF
            self.midi_out.send_message([0x90, note, velocity])
            #logging.debug(f"Set Effect Bank {i} LED (Note {note}) to Vel {velocity}")

    def _refresh_grid_leds(self):
        if not self.midi_out:
            return
        #logging.debug(f"Refreshing grid LEDs for LFO Bank {self.current_lfo_bank}, Effect Bank {self.current_effect_bank}")
        for r_vis in range(NUM_ROWS):
            for c_vis in range(NUM_COLS):
                actual_r = self.current_lfo_bank * NUM_ROWS + r_vis
                actual_c = self.current_effect_bank * NUM_COLS + c_vis
                
                led_velocity = LED_OFF
                if self.fader_override_active[actual_c] and self.mapping[actual_r][actual_c]:
                    led_velocity = LED_RED # Fader override on a mapped LFO
                elif self.mapping[actual_r][actual_c]:
                    led_velocity = LED_GREEN # LFO mapped
                
                led_note = NOTE_GRID[r_vis][c_vis]
                self.midi_out.send_message([0x90, led_note, led_velocity])
                #logging.debug(f"Grid LED [{r_vis}][{c_vis}] (Actual [{actual_r}][{actual_c}], Note {led_note}) set to Vel {led_velocity}")

    def handle_lfo(self, unused_addr, args, *values):
        #logging.debug(f"Received OSC message: Address: {unused_addr}, Args: {args}, Values: {values}")
        lfo_source_on_grid = args[0] # This is 0-7, relative to current LFO bank
        actual_lfo_row_idx = self.current_lfo_bank * NUM_ROWS + lfo_source_on_grid
        value = values[-1] 

        # Iterate through ALL actual effect columns
        for actual_col_idx in range(TOTAL_COLS):
            if self.fader_override_active[actual_col_idx]:
                # Fader is overriding this actual column.
                # OSC for this column is primarily sent from handle_midi when fader moves.
                # We also send it here to ensure continuous output if it's the sole controller for this column.
                current_fader_val = self.fader_override_value[actual_col_idx]
                self.osc_client.send_message(f"/effect/{actual_col_idx + 1}", current_fader_val)
                self.frozen_outputs[actual_col_idx] = current_fader_val # Keep frozen_outputs updated
            
            else: # No fader override for this actual_col_idx
                if self.mapping[actual_lfo_row_idx][actual_col_idx]: 
                    # The currently updating LFO IS mapped to this actual_col_idx
                    self.osc_client.send_message(f"/effect/{actual_col_idx + 1}", value)
                    self.frozen_outputs[actual_col_idx] = value
                
                # If the currently updating LFO is NOT mapped to this actual_col_idx,
                # AND no OTHER LFO is mapped to this actual_col_idx either,
                # then send the frozen value for this column.
                # This ensures unmapped/un-overridden channels continue to send their last known good value.
                elif not any(self.mapping[any_lfo_row][actual_col_idx] for any_lfo_row in range(TOTAL_ROWS)):
                    self.osc_client.send_message(f"/effect/{actual_col_idx + 1}", self.frozen_outputs[actual_col_idx])
                # If some other LFO is mapped (and not the current one), that LFO's update will handle sending its value.

    def setup_midi(self):
        self.midi_in = rtmidi.MidiIn()
        ports = self.midi_in.get_ports()
        for i, name in enumerate(ports):
            if "APC MINI" in name.upper():
                self.midi_in.open_port(i)
                logging.info(f"Connected to APC MINI MIDI input on port {i}: {name}")
                break
        else:
            raise RuntimeError("APC MINI MIDI input not found")

        self.midi_in.set_callback(self.handle_midi)

        # Setup MIDI output for LED feedback
        self.midi_out = rtmidi.MidiOut()
        out_ports = self.midi_out.get_ports()
        apc_midi_out_port_index = -1
        for i, name in enumerate(out_ports):
            if "APC MINI" in name.upper(): # Assuming the output port also contains "APC MINI"
                try:
                    self.midi_out.open_port(i)
                    logging.info(f"Opened APC MINI MIDI output port {i}: {name} for LED feedback.")
                    apc_midi_out_port_index = i
                    
                    # Comprehensive LED clear for notes 0-95
                    logging.info("Attempting to clear all LEDs on APC MINI (Notes 0-95).")
                    for note_to_clear in range(96): # Notes 0 through 95
                        self.midi_out.send_message([0x90, note_to_clear, LED_OFF])
                    logging.info("Finished clearing LEDs.")
                    break # Exit loop once port is successfully opened and LEDs cleared
                except rtmidi.RtMidiError as e:
                    logging.warning(f"Could not open APC MINI MIDI output port {i} ({name}): {e}. LED feedback may be disabled.")
                    self.midi_out = None # Ensure midi_out is None if this attempt failed
        else: # This else belongs to the for loop: executed if the loop completes without break
            if apc_midi_out_port_index == -1: # Double check, though break should prevent this if successful
                 logging.warning("APC MINI MIDI output port not found. LED feedback will be disabled.")
                 self.midi_out = None # Ensure midi_out is None if no port was found/opened

        # Set up initial LED states for banks and current grid view if MIDI out is available
        if self.midi_out and apc_midi_out_port_index != -1:
            self._update_bank_select_leds()
            self._refresh_grid_leds()
            logging.info("Set initial active bank and grid LED states.")

    def handle_midi(self, message_data, _):
        message, _ = message_data
        # message[0] = status byte
        # message[1] = note number or CC number
        # message[2] = velocity or CC value

        if message[0] & 0xF0 == 0x90:  # Note-on message (buttons)
            note = message[1]
            velocity = message[2]

            if velocity > 0: # True note-on
                # Bank Selection Buttons (Notes 82-89)
                if 82 <= note <= 85: # LFO Bank Select
                    new_lfo_bank = note - 82
                    if new_lfo_bank != self.current_lfo_bank:
                        self.current_lfo_bank = new_lfo_bank
                        logging.info(f"Switched to LFO Bank {self.current_lfo_bank}")
                        self._update_bank_select_leds()
                        self._refresh_grid_leds()
                    return # Processed bank select

                elif 86 <= note <= 89: # Effect Bank Select
                    new_effect_bank = note - 86
                    if new_effect_bank != self.current_effect_bank:
                        self.current_effect_bank = new_effect_bank
                        logging.info(f"Switched to Effect Bank {self.current_effect_bank}")
                        self._update_bank_select_leds()
                        self._refresh_grid_leds()
                    return # Processed bank select

                # Grid Buttons
                for r_pressed_vis in range(NUM_ROWS): # Visible row on 8x8 grid
                    for c_pressed_vis in range(NUM_COLS): # Visible col on 8x8 grid
                        if NOTE_GRID[r_pressed_vis][c_pressed_vis] == note:
                            actual_r_pressed = self.current_lfo_bank * NUM_ROWS + r_pressed_vis
                            actual_c_pressed = self.current_effect_bank * NUM_COLS + c_pressed_vis
                            
                            #logging.debug(f"Button press: Vis ({r_pressed_vis},{c_pressed_vis}), Actual ({actual_r_pressed},{actual_c_pressed}), Note {note}")

                            if self.fader_override_active[actual_c_pressed]:
                                self.fader_override_active[actual_c_pressed] = False
                                #logging.info(f"Fader override on actual col {actual_c_pressed} cleared by button. Restoring LFO control.")

                                if self.midi_out:
                                    for r_iter_vis in range(NUM_ROWS):
                                        actual_r_iter = self.current_lfo_bank * NUM_ROWS + r_iter_vis
                                        self.mapping[actual_r_iter][actual_c_pressed] = False
                                        if r_iter_vis != r_pressed_vis: # Turn off other LEDs in this visible column
                                             self.midi_out.send_message([0x90, NOTE_GRID[r_iter_vis][c_pressed_vis], LED_OFF])
                                
                                self.mapping[actual_r_pressed][actual_c_pressed] = True
                                #print(f"Mapping enabled for LFO input {actual_r_pressed} -> output {actual_c_pressed} (fader override removed).")
                                if self.midi_out:
                                    self.midi_out.send_message([0x90, NOTE_GRID[r_pressed_vis][c_pressed_vis], LED_GREEN])
                            
                            else: # Fader override IS NOT Active (Normal button operation for this actual column)
                                if self.mapping[actual_r_pressed][actual_c_pressed]:
                                    self.mapping[actual_r_pressed][actual_c_pressed] = False
                                    #print(f"Mapping disabled for LFO {actual_r_pressed} -> Effect {actual_c_pressed}")
                                    if self.midi_out:
                                        self.midi_out.send_message([0x90, NOTE_GRID[r_pressed_vis][c_pressed_vis], LED_OFF])
                                else:
                                    # Turn off any other LFO mapping in the *current LFO bank* to this *actual effect column*.
                                    if self.midi_out:
                                        for r_iter_vis in range(NUM_ROWS):
                                            actual_r_iter = self.current_lfo_bank * NUM_ROWS + r_iter_vis
                                            if actual_r_iter != actual_r_pressed and self.mapping[actual_r_iter][actual_c_pressed]:
                                                self.mapping[actual_r_iter][actual_c_pressed] = False
                                                self.midi_out.send_message([0x90, NOTE_GRID[r_iter_vis][c_pressed_vis], LED_OFF])
                                    
                                    self.mapping[actual_r_pressed][actual_c_pressed] = True
                                    #print(f"Mapping enabled for LFO {actual_r_pressed} -> Effect {actual_c_pressed}")
                                    if self.midi_out:
                                        self.midi_out.send_message([0x90, NOTE_GRID[r_pressed_vis][c_pressed_vis], LED_GREEN])
                            
                            self._refresh_grid_leds() # Refresh to ensure all states are correct after a change. More robust.
                            return 
                return 

        elif message[0] & 0xF0 == 0xB0:  # Control Change message (Faders)
            cc_number = message[1]
            cc_value = message[2]

            # APC MINI Faders (Channels 1-8 on the device, map to CC 48-55)
            if 48 <= cc_number <= 55:
                col_index_on_grid = cc_number - 48  # Visible column index 0-7
                actual_col_idx_fader = self.current_effect_bank * NUM_COLS + col_index_on_grid
                
                if not self.fader_override_active[actual_col_idx_fader]:
                    logging.info(f"Fader CC {cc_number} taking control of actual output column {actual_col_idx_fader} (Vis col {col_index_on_grid} in Bank {self.current_effect_bank}).")
                
                self.fader_override_active[actual_col_idx_fader] = True
                fader_float_value = cc_value / 127.0
                self.fader_override_value[actual_col_idx_fader] = fader_float_value 

                self.osc_client.send_message(f"/effect/{actual_col_idx_fader + 1}", fader_float_value)
                #logging.debug(f"Fader override OSC sent for actual col {actual_col_idx_fader}: CC {cc_number} val {fader_float_value}")

                if self.midi_out:
                    for r_vis_idx in range(NUM_ROWS): # Iterate visible rows
                        actual_r_loop = self.current_lfo_bank * NUM_ROWS + r_vis_idx
                        if self.mapping[actual_r_loop][actual_col_idx_fader]: 
                            led_note_vis = NOTE_GRID[r_vis_idx][col_index_on_grid]
                            self.midi_out.send_message([0x90, led_note_vis, LED_RED]) 
                            #logging.debug(f"Fader override: LED for LFO mapping Actual [{actual_r_loop}][{actual_col_idx_fader}] (Vis Note {led_note_vis}) set to RED")
            return # Processed CC message

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSC Control Mapper for APC MINI.")
    parser.add_argument("--in-host", default="127.0.0.1", help="IP address to listen for incoming OSC messages.")
    parser.add_argument("--in-port", type=int, default=9000, help="Port to listen for incoming OSC messages.")
    parser.add_argument("--out-host", default="127.0.0.1", help="IP address to send outgoing OSC messages.")
    parser.add_argument("--out-port", type=int, default=9001, help="Port to send outgoing OSC messages.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    mapper = ControlMapper(args.in_host, args.in_port, args.out_host, args.out_port)
    print("Control mapper running... Press buttons on APC MINI.")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("Exiting...")

