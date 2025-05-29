import argparse
import logging
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
import rtmidi
import threading

NUM_ROWS = 8
NUM_COLS = 8
NOTE_GRID = [[r + c for c in range(NUM_COLS)] for r in range(NUM_ROWS)]
for r in range(NUM_ROWS):
    for c in range(NUM_COLS):
        NOTE_GRID[r][c] = (NUM_ROWS - 1 - r) * 8 + c  # MIDI notes

class ControlMapper:
    def __init__(self, in_host: str = "127.0.0.1", in_port: int = 9000, out_host: str = "127.0.0.1", out_port: int = 9001):
        self.mapping = [[False] * NUM_COLS for _ in range(NUM_ROWS)]
        self.frozen_outputs = [0.0] * NUM_COLS
        self.midi_out = None # Initialize midi_out

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

    def handle_lfo(self, unused_addr, args, *values):
        row = args[0]
        for col in range(NUM_COLS):
            if self.mapping[row][col]:
                self.osc_client.send_message(f"/effect/{col+1}", values[-1])
                self.frozen_outputs[col] = values[-1]
            elif not any(self.mapping[r][col] for r in range(NUM_ROWS)):
                self.osc_client.send_message(f"/effect/{col+1}", self.frozen_outputs[col])

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
                    break
                except rtmidi.RtMidiError as e:
                    logging.warning(f"Could not open APC MINI MIDI output port {i} ({name}): {e}. LED feedback may be disabled.")
        else:
            logging.warning("APC MINI MIDI output port not found. LED feedback will be disabled.")
            self.midi_out = None # Ensure it's None if not opened or failed to open

        # Initialize LEDs to off
        if self.midi_out and apc_midi_out_port_index != -1:
            logging.info("Initializing APC MINI LEDs to OFF state.")
            for r_idx in range(NUM_ROWS):
                for c_idx in range(NUM_COLS):
                    note_val = NOTE_GRID[r_idx][c_idx]
                    # Send Note On with velocity 0 (typically turns LED off for APC MINI pads)
                    self.midi_out.send_message([0x90, note_val, 0])
            # Add a small delay if necessary for the APC to process all messages, though usually not needed
            # import time
            # time.sleep(0.1)

    def handle_midi(self, message_data, _):
        message, _ = message_data
        # message[0] = status byte (e.g., 0x90 for note on, 0x80 for note off for channel 1)
        # message[1] = note number
        # message[2] = velocity
        if message[0] & 0xF0 == 0x90:  # Only react to note-on messages
            if message[2] > 0:  # Check for velocity > 0 (true note-on)
                note = message[1]
                for r_pressed in range(NUM_ROWS):
                    for c_pressed in range(NUM_COLS):
                        if NOTE_GRID[r_pressed][c_pressed] == note:
                            # Found the button that was pressed (r_pressed, c_pressed)

                            if self.mapping[r_pressed][c_pressed]:
                                # Current mapping is ON, so turn it OFF
                                self.mapping[r_pressed][c_pressed] = False
                                print(f"Mapping disabled for input {r_pressed} -> output {c_pressed}")
                                if self.midi_out:
                                    led_note = NOTE_GRID[r_pressed][c_pressed]
                                    self.midi_out.send_message([0x90, led_note, 0]) # LED OFF
                                    logging.debug(f"Sent LED OFF for [{r_pressed}][{c_pressed}]")
                            else:
                                # Current mapping is OFF, so turn it ON.
                                # First, turn off any other mapping in the same column.
                                for i in range(NUM_ROWS):
                                    if i != r_pressed and self.mapping[i][c_pressed]:
                                        self.mapping[i][c_pressed] = False
                                        print(f"Mapping disabled for input {i} -> output {c_pressed} (overridden by input {r_pressed})")
                                        if self.midi_out:
                                            old_led_note = NOTE_GRID[i][c_pressed]
                                            self.midi_out.send_message([0x90, old_led_note, 0]) # LED OFF
                                            logging.debug(f"Sent LED OFF for overridden mapping [{i}][{c_pressed}]")
                                
                                # Now, turn ON the new mapping
                                self.mapping[r_pressed][c_pressed] = True
                                print(f"Mapping enabled for input {r_pressed} -> output {c_pressed}")
                                if self.midi_out:
                                    new_led_note = NOTE_GRID[r_pressed][c_pressed]
                                    # Using velocity 1 for green LED as before
                                    self.midi_out.send_message([0x90, new_led_note, 1]) # LED ON
                                    logging.debug(f"Sent LED ON for [{r_pressed}][{c_pressed}]")
                            
                            return # Processed note-on, exit loops and function

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

