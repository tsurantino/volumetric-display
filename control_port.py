import asyncio
import socket
import json
import base64
import subprocess
import platform

CONTROLLER_PORT = 51333
ENUM_COMMAND = b"enum\n"
BUTTON_TIMEOUT = 0.1
CONNECTION_TIMEOUT = 2.0
PING_TIMEOUT = 1.0  # seconds


class ControllerState:
    def __init__(self, ip, dip):
        self.ip = ip
        self.dip = dip
        self.button_callback = None
        self._listen_task = None
        self._socket = None
        self._connected = False
        self._buffer = b""

    async def connect(self):
        if self._connected:
            return True
        loop = asyncio.get_running_loop()
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(CONNECTION_TIMEOUT)
            await loop.sock_connect(self._socket, (self.ip, CONTROLLER_PORT))
            self._socket.setblocking(False)
            self._connected = True
            return True
        except Exception as e:
            print(f"Failed to connect to {self.ip}: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
        self._socket = None
        self._connected = False

    async def set_lcd(self, x, y, text):
        msg = f"lcd:{x}:{y}:{text}\n".encode()
        await self._send(msg)

    async def clear_lcd(self):
        msg = f"lcd:clear\n".encode()
        await self._send(msg)

    async def set_backlights(self, states):
        payload = ":".join(["1" if s else "0" for s in states])
        msg = f"backlight:{payload}\n".encode()
        await self._send(msg)

    async def set_leds(self, rgb_values):
        """Set LED colors from a list of (r,g,b) tuples."""
        # Create payload: [num_leds (16-bit LE), r0,g0,b0, r1,g1,b1, ...]
        num_leds = len(rgb_values)
        payload = bytearray([num_leds & 0xFF, (num_leds >> 8) & 0xFF])
        for r, g, b in rgb_values:
            payload.extend([r & 0xFF, g & 0xFF, b & 0xFF])
        msg = f"led:{base64.b64encode(bytes(payload)).decode()}\n".encode()
        await self._send(msg)

    def register_button_callback(self, callback):
        self.button_callback = callback
        if not self._listen_task:
            self._listen_task = asyncio.get_running_loop().create_task(self._listen_buttons())

    async def _send(self, msg):
        if not self._connected:
            if not await self.connect():
                return
        loop = asyncio.get_running_loop()
        try:
            await loop.sock_sendall(self._socket, msg)
        except Exception as e:
            print(f"Error sending to {self.ip}: {e}")
            self.disconnect()

    async def _listen_buttons(self):
        while True:
            if not self._connected:
                if not await self.connect():
                    await asyncio.sleep(1.0)
                    continue

            try:
                loop = asyncio.get_running_loop()
                data = await loop.sock_recv(self._socket, 1024)
                print(f"Received data: {data}")
                if not data:  # Connection closed
                    self.disconnect()
                    continue

                self._buffer += data
                parts = self._buffer.split(b'\n')

                self._buffer = parts[-1] if not self._buffer.endswith(b'\n') else b""

                messages_to_process = parts[:-1] if not self._buffer else parts

                for part in messages_to_process:
                    if not part:
                        continue
                    part_str = part.strip().decode()
                    if not part_str:
                        continue
                    try:
                        msg = json.loads(part_str)
                        if "buttons" in msg and self.button_callback:
                            self.button_callback(msg["buttons"])
                    except json.JSONDecodeError as e:
                        print(f"Error decoding JSON: {e} on data: '{part_str}'")
                    except Exception as e:
                        print(f"Error processing button message: {e}")
            except ConnectionResetError:
                print(f"Connection reset by {self.ip}. Reconnecting...")
                self.disconnect()
                await asyncio.sleep(1.0)
            except Exception as e:
                print(f"Error reading from socket {self.ip}: {e}")
                self.disconnect()
                await asyncio.sleep(1.0)


class ControlPort:
    def __init__(self, base_ip="192.168.0.", start=50, end=65, port=CONTROLLER_PORT, loop=None):
        self.base_ip = base_ip
        self.start = start
        self.end = end
        self.port = port
        self.loop = loop or asyncio.get_event_loop()
        self.controllers = {}

    async def ping_host(self, ip):
        """Ping a host and return True if it responds."""
        loop = asyncio.get_running_loop()
        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, "1", "-W", str(int(PING_TIMEOUT * 1000)), ip]
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    command, capture_output=True, text=True, timeout=PING_TIMEOUT
                ),
            )
            return result.returncode == 0
        except Exception as e:
            print(f"Error pinging {ip}: {e}")
            return False

    async def check_port(self, ip):
        """Check if the port is open using a socket connection."""
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)  # Short timeout for port check
        try:
            result = await loop.sock_connect(sock, (ip, self.port))
            print(f"Port {self.port} is open on {ip}")
            return True
        except Exception as e:
            print(f"Port {self.port} is closed on {ip}: {e}")
            return False
        finally:
            sock.close()

    async def discover_hosts(self):
        """Discover reachable hosts using ICMP ping and port check."""
        print("Discovering reachable hosts...")
        tasks = []
        for i in range(self.start, self.end + 1):
            ip = f"{self.base_ip}{i}"
            tasks.append(self.ping_host(ip))

        results = await asyncio.gather(*tasks)
        reachable_ips = []
        for i, is_reachable in enumerate(results):
            ip = f"{self.base_ip}{i + self.start}"
            if is_reachable:
                print(f"Host {ip} is reachable")
                # Check if the port is open
                if await self.check_port(ip):
                    reachable_ips.append(ip)
            else:
                print(f"Host {ip} is not reachable")
        return reachable_ips

    async def enumerate(self, timeout=2.0):
        # First discover reachable hosts
        reachable_ips = await self.discover_hosts()
        if not reachable_ips:
            print("No reachable hosts found")
            return self.controllers

        # Then try to enumerate only the reachable hosts
        tasks = []
        for ip in reachable_ips:
            tasks.append(self._query_controller(ip, timeout / 2))

        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
        except asyncio.TimeoutError:
            print("Global enumeration timeout")
            results = []

        for result in results:
            if result:
                ip, dip = result
                self.controllers[ip] = ControllerState(ip, dip)
        return self.controllers

    async def _query_controller(self, ip, timeout):
        print(f"\nAttempting to enumerate {ip}:{self.port}")
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            print(f"1. Connecting to {ip}:{self.port}")
            await loop.sock_connect(sock, (ip, self.port))
            print("2. Connection successful, setting non-blocking mode")
            sock.setblocking(False)

            print("3. Sending enum command")
            await loop.sock_sendall(sock, ENUM_COMMAND)
            print("4. Command sent, waiting for response")

            data = await loop.sock_recv(sock, 1024)
            print(f"5. Received response: {data}")

            msg = json.loads(data.decode())
            if msg.get("type") == "controller" and "dip" in msg:
                print(f"6. Successfully enumerated controller with DIP={msg['dip']}")
                return (ip, msg["dip"])
            else:
                print(f"6. Invalid response format: {msg}")
                return None
        except socket.timeout:
            print(f"Timeout while communicating with {ip}")
            return None
        except ConnectionRefusedError:
            print(f"Connection refused by {ip}")
            return None
        except ConnectionResetError:
            print(f"Connection reset by {ip}")
            return None
        except Exception as e:
            print(f"Error communicating with {ip}: {type(e).__name__}: {e}")
            return None
        finally:
            sock.close()
