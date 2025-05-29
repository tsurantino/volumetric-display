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
            self.dispatcher.map(f"/lfo/{row}", self.handle_lfo, row)

        self.osc_server = ThreadingOSCUDPServer((self.in_host, self.in_port), self.dispatcher)
        threading.Thread(target=self.osc_server.serve_forever, daemon=True).start()

    def handle_lfo(self, unused_addr, args, value):
        row = args
        for col in range(NUM_COLS):
            if self.mapping[row][col]:
                self.osc_client.send_message(f"/effect/{col}", value)
                self.frozen_outputs[col] = value
            elif not any(self.mapping[r][col] for r in range(NUM_ROWS)):
                self.osc_client.send_message(f"/effect/{col}", self.frozen_outputs[col])

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
                for r in range(NUM_ROWS):
                    for c in range(NUM_COLS):
                        if NOTE_GRID[r][c] == note:
                            self.mapping[r][c] = not self.mapping[r][c]
                            print(f"Mapping {'enabled' if self.mapping[r][c] else 'disabled'} for input {r} -> output {c}")
                            
                            # Update LED feedback
                            if self.midi_out:
                                led_note = NOTE_GRID[r][c]
                                # Velocity 1 (or other low values) for dim, 127 for bright, 0 for off.
                                # APC MINI LEDs: 0=off, 1=green, 2=green blink, 3=red, 4=red blink, 5=yellow, 6=yellow blink
                                # For simple on/off, we can use a standard bright color or just 0 for off.
                                # Let's use velocity 1 for a green LED when enabled.
                                led_velocity = 1 if self.mapping[r][c] else 0 
                                self.midi_out.send_message([0x90, led_note, led_velocity])
                                logging.debug(f"Sent LED command: Note {led_note}, Velocity {led_velocity} for mapping [{r}][{c}] -> {self.mapping[r][c]}")
                            break # Found the note, no need to check further
                return # Processed note-on

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSC Control Mapper for APC MINI.")
    parser.add_argument("--in-host", default="127.0.0.1", help="IP address to listen for incoming OSC messages.")
    parser.add_argument("--in-port", type=int, default=9000, help="Port to listen for incoming OSC messages.")
    parser.add_argument("--out-host", default="127.0.0.1", help="IP address to send outgoing OSC messages.")
    parser.add_argument("--out-port", type=int, default=9001, help="Port to send outgoing OSC messages.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    mapper = ControlMapper(args.in_host, args.in_port, args.out_host, args.out_port)
    print("Control mapper running... Press buttons on APC MINI.")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("Exiting...")

