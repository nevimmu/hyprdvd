import json
import random
from .utils import hyprctl
from .hyprDVD import HyprDVD

class HyprDVDManager:
	'''Manages all HyprDVD windows.'''

	def __init__(self, size=None):
		self.windows = []
		self.window_size = size
		self._disabled_workspaces = set()
		self._animation_original_state = None

	def add_window(self, event_data):
		'''Add a new window to manage'''
		window = HyprDVD(event_data, self, size=self.window_size)

		attempts = 0
		max_x_span = max(0, window.screen_width - window.window_width)
		max_y_span = max(0, window.screen_height - window.window_height)

		while attempts < 100:
			random_x = random.randint(0, max_x_span) if max_x_span else 0
			random_y = random.randint(0, max_y_span) if max_y_span else 0

			overlapping = False
			for other_window in self.windows:
				if (window.workspace_id == other_window.workspace_id and
						random_x < other_window.window_x + other_window.window_width and
						random_x + window.window_width > other_window.window_x and
						random_y < other_window.window_y + other_window.window_height and
						random_y + window.window_height > other_window.window_y):
					overlapping = True
					break
			if not overlapping:
				# Set the window's internal position before appending
				window.window_x = random_x
				window.window_y = random_y
				global_x = int(window.offset_x + random_x)
				global_y = int(window.offset_y + random_y)
				hyprctl(['dispatch', 'movewindowpixel', 'exact',
							str(global_x), str(global_y), f',address:{window.address}'])
				self.windows.append(window)
				self.handle_animation(window.workspace_id, True)
				return

			attempts += 1

		# If no space is found after 100 attempts, close the window
		hyprctl(['dispatch', 'closewindow', f'address:{window.address}'])

	def cleanup_window(self, window):
		'''Cleanup a window and restore animation if it's the last one on the workspace.'''
		if window in self.windows:
			self.windows.remove(window)
			if not any(w.workspace_id == window.workspace_id for w in self.windows):
				self.handle_animation(window.workspace_id, False)

	def check_collisions(self):
		'''Check for collisions between windows and with screen borders.'''
		for i, window in enumerate(self.windows):
			# Screen border collision with position correction
			# Left border
			if window.window_x <= 0:
				window.window_x = 0
				if window.velocity_x < 0:
					window.velocity_x *= -1
			# Right border
			elif window.window_x >= window.screen_width - window.window_width:
				window.window_x = window.screen_width - window.window_width
				if window.velocity_x > 0:
					window.velocity_x *= -1
			
			# Top border
			if window.window_y <= 0:
				window.window_y = 0
				if window.velocity_y < 0:
					window.velocity_y *= -1
			# Bottom border
			elif window.window_y >= window.screen_height - window.window_height:
				window.window_y = window.screen_height - window.window_height
				if window.velocity_y > 0:
					window.velocity_y *= -1

			# Other window collision
			for other_window in self.windows[i+1:]:
				if (
					window.workspace_id == other_window.workspace_id and
					window.window_x < other_window.window_x + other_window.window_width and
					window.window_x + window.window_width > other_window.window_x and
					window.window_y < other_window.window_y + other_window.window_height and
					window.window_y + window.window_height > other_window.window_y
				):
					# Calculate overlap amounts
					overlap_x = min(window.window_x + window.window_width, other_window.window_x + other_window.window_width) - max(window.window_x, other_window.window_x)
					overlap_y = min(window.window_y + window.window_height, other_window.window_y + other_window.window_height) - max(window.window_y, other_window.window_y)

					# Separate windows based on smaller overlap
					if overlap_x < overlap_y:
						# Horizontal collision - separate horizontally
						if window.window_x < other_window.window_x:
							# window is on the left
							separation = overlap_x / 2
							window.window_x -= separation
							other_window.window_x += separation
						else:
							# window is on the right
							separation = overlap_x / 2
							window.window_x += separation
							other_window.window_x -= separation
						
						# Swap horizontal velocities only if they're moving towards each other
						if (window.velocity_x > 0 and other_window.velocity_x < 0) or \
						   (window.velocity_x < 0 and other_window.velocity_x > 0):
							window.velocity_x, other_window.velocity_x = other_window.velocity_x, window.velocity_x
					else:
						# Vertical collision - separate vertically
						if window.window_y < other_window.window_y:
							# window is above
							separation = overlap_y / 2
							window.window_y -= separation
							other_window.window_y += separation
						else:
							# window is below
							separation = overlap_y / 2
							window.window_y += separation
							other_window.window_y -= separation
						
						# Swap vertical velocities only if they're moving towards each other
						if (window.velocity_y > 0 and other_window.velocity_y < 0) or \
						   (window.velocity_y < 0 and other_window.velocity_y > 0):
							window.velocity_y, other_window.velocity_y = other_window.velocity_y, window.velocity_y

	def update_windows(self):
		'''Update all window positions and move them.'''
		clients = json.loads(hyprctl(['clients', '-j']).stdout)
		
		# Check which windows still exist
		for window in self.windows[:]:
			client = next((w for w in clients if w['address'] == window.address), None)
			if not client:
				self.cleanup_window(window)
				continue
			
			# Update size from Hyprland (can change if user resizes)
			window.window_width, window.window_height = client['size']
			
			# On first update, sync position with Hyprland to get actual position
			# After that, we manage position ourselves to avoid position conflicts
			if not window.position_synced:
				ax, ay = client['at']                  # absolute coords from Hyprland
				ox = getattr(window, 'offset_x', 0)    # monitor origin
				oy = getattr(window, 'offset_y', 0)
				window.window_x = ax - ox              # store RELATIVE position
				window.window_y = ay - oy
				window.position_synced = True

		
		# Update positions based on velocity
		for window in self.windows:
			window.update()

		# Check and correct collisions
		self.check_collisions()

		# Send corrected positions to Hyprland (convert to int)
		batch_command = []
		for window in self.windows:
			x = int(round(window.window_x))
			y = int(round(window.window_y))
			gx = int(window.window_x + getattr(window, 'offset_x', 0))
			gy = int(window.window_y + getattr(window, 'offset_y', 0))
			batch_command.append(f'dispatch movewindowpixel exact {gx} {gy},address:{window.address}')
		if batch_command:
			hyprctl(['--batch', ';'.join(batch_command)])

	def _current_animation_state(self):
		'''Return the current Hyprland animations:enabled value (best-effort).'''
		try:
			out = hyprctl(['getoption', 'animations:enabled']).stdout.strip()
			for line in out.splitlines():
				if line.startswith('int:'):
					return line.split(':', 1)[1].strip()
			# fallback: last token
			tokens = out.split()
			return tokens[1] if len(tokens) > 1 else '1'
		except Exception:
			return '1'

	def handle_animation(self, workspace_id, is_enabled):
		'''Handle animations for the workspace.'''
		if is_enabled:
			if workspace_id in self._disabled_workspaces:
				return
			self._disabled_workspaces.add(workspace_id)
			if self._animation_original_state is None:
				self._animation_original_state = self._current_animation_state()
			hyprctl(['keyword', 'animations:enabled', 'no'])
		else:
			if workspace_id not in self._disabled_workspaces:
				return
			self._disabled_workspaces.remove(workspace_id)
			if not self._disabled_workspaces and self._animation_original_state is not None:
				hyprctl(['keyword', 'animations:enabled', self._animation_original_state])
				self._animation_original_state = None

	def handle_workspace_change(self, event_data):
		'''Handle workspace change events.'''
		try:
			workspace_id = int(event_data[0])
		except (IndexError, ValueError):
			return
		if any(w.workspace_id == workspace_id for w in self.windows):
			self.handle_animation(workspace_id, True)
		else:
			self.handle_animation(workspace_id, False)

		for w_id in list(self._disabled_workspaces):
			if not any(w.workspace_id == w_id for w in self.windows):
				self.handle_animation(w_id, False)

	def handle_active_window_change(self, event_data):
		'''Handle active window change events.'''
		if len(event_data) < 2 or not event_data[1]:
			return
		window_address = f'0x{event_data[1]}'
		clients = json.loads(hyprctl(['clients', '-j']).stdout)
		active_window = next((w for w in clients if w['address'] == window_address), None)
		if active_window:
			workspace_id = active_window['workspace']['id']
			if not any(w.address == window_address for w in self.windows):
				self.handle_animation(workspace_id, False)
