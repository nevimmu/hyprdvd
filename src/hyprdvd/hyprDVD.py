import random
import math
import json

from .utils import hyprctl
from .settings import RESIZE

class HyprDVD:
	'''Class for a single bouncing window.'''
	def __init__(self, event_data, manager, size=None):
		self.address = f'0x{event_data[0]}'
		self.workspace_id = int(event_data[1])
		self.manager = manager

		self.requested_size = size

		self.screen_width  = 1920
		self.screen_height = 1080
		self.offset_x = 0      # global origin X of the monitor owning this window
		self.offset_y = 0      # global origin Y of the monitor owning this window


		self.get_screen_size()
		self.set_window_size()

		# Initialize position (will be set by manager)
		self.window_x = 0
		self.window_y = 0
		self.position_synced = False  # Track if we've synced with Hyprland

		self.velocity_x = 2
		self.velocity_y = 2

		self.set_window_start()

	@classmethod
	def from_client(cls, client, manager, size=None, at=None):
		'''Create a HyprDVD instance from a hyprctl client dict.

		Optional args:
		- size: tuple[int|float, int|float] -> forwarded to constructor (ratio or pixels)
		- at: tuple[int, int] -> initial position to sync with (e.g., when caller already moved window)
		'''
		addr = client.get('address', '')
		addr_stripped = addr.replace('0x', '') if addr.startswith('0x') else addr
		ev = [addr_stripped, str(client['workspace']['id'])]
		instance = cls(ev, manager, size=size)
		# If caller provides an explicit position (e.g., after moving the window), trust it.
		if at is not None and len(at) == 2:
			try:
				instance.window_x, instance.window_y = int(at[0]), int(at[1])
				# Size is already set in constructor based on requested size; do not force from client here.
				instance.position_synced = True
				return instance
			except Exception:
				# Fall back to client-provided values if casting fails
				pass

		# Otherwise, override with actual client values so the animation
		# starts from the Hyprland-reported location/size.
		try:
			ax, ay = client['at']
			instance.window_x = int(ax) - instance.offset_x
			instance.window_y = int(ay) - instance.offset_y
			instance.window_width, instance.window_height = client['size']
			instance.position_synced = True  # Position is already from Hyprland
		except Exception:
			# If client data doesn't have expected fields, leave defaults
			pass
		return instance

	def set_window_size(self):
		'''Set the size of the window relative to the screen size'''
		# If a requested size was provided, use it. Values <=1 are ratios of the
		# screen; values >1 are treated as absolute pixel sizes.
		if self.requested_size:
			try:
				rw, rh = self.requested_size
				if rw <= 1 and rh <= 1:
					self.window_width = math.ceil(self.screen_width * float(rw))
					self.window_height = math.ceil(self.screen_height * float(rh))
				else:
					self.window_width = int(rw)
					self.window_height = int(rh)
				return
			except Exception:
				# fallback to default if provided size is invalid
				pass

		resize = RESIZE
		self.window_width = math.ceil(self.screen_width * resize)
		self.window_height = math.ceil(self.screen_height * resize)

	def set_window_start(self):
		'''Set a random direction'''
		if random.randrange(1, 100) % 2 == 0:
			self.velocity_x *= -1
		if random.randrange(101, 200) % 2 == 0:
			self.velocity_y *= -1

		hyprctl(['dispatch', 'setfloating', f'address:{self.address}'])
		hyprctl(['dispatch', 'resizewindowpixel', 'exact',
				 str(self.window_width), str(self.window_height), f',address:{self.address}'])

	def get_screen_size(self):
		'''Get the screen size'''
		monitors_json = json.loads(hyprctl(['monitors', '-j']).stdout)
		for monitor in monitors_json:
			if monitor['activeWorkspace']['id'] == int(self.workspace_id):
				transform = monitor['transform'] in [1, 3, 5, 7]
				self.screen_width = int(monitor['width'] / monitor['scale']) if not transform else int(monitor['height'] / monitor['scale'])
				self.screen_height = int(monitor['height'] / monitor['scale']) if not transform else int(monitor['width'] / monitor['scale'])
				self.offset_x = int(monitor.get('x', 0))
				self.offset_y = int(monitor.get('y', 0))
				break

	def get_window_position_and_size(self, clients):
		'''Get the window position and size'''
		window = next((w for w in clients if w['address'] == self.address), None)

		if not window:
			return False

		self.window_x, self.window_y = window['at']
		self.window_width, self.window_height = window['size']
		return True

	def update(self):
		'''Update window position'''
		self.window_x += self.velocity_x
		self.window_y += self.velocity_y
