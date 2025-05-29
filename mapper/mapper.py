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
                logging.info(f"Connected to APC MINI on MIDI port {i}: {name}")
                break
        else:
            raise RuntimeError("APC MINI not found")

        self.midi_in.set_callback(self.handle_midi)

    def handle_midi(self, message_data, _):
        message, _ = message_data
        if message[0] & 0xF0 in [0x90, 0x80]:
            note = message[1]
            for r in range(NUM_ROWS):
                for c in range(NUM_COLS):
                    if NOTE_GRID[r][c] == note:
                        self.mapping[r][c] = not self.mapping[r][c]
                        print(f"Mapping {'enabled' if self.mapping[r][c] else 'disabled'} for input {r} -> output {c}")

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

