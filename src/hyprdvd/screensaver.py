import time
import json
import math
import random

from hyprdvd.settings import RESIZE
from .utils import hyprctl
from .hyprDVD import HyprDVD


def run_screensaver(manager, poll_interval=0.02, size=None, workspaces=None, exit_on='pointer'):
	'''Run the screensaver: save cursor and current workspace windows, float and animate them until cursor moves.

	This function makes a few reasonable assumptions about available hyprctl commands:
	- `hyprctl(['cursorpos'])` returns cursor coordinates as: "<x> <y>" or similar.
	- `clients -j` returns a list of client dicts with keys: 'address', 'at', 'size', 'workspace', 'focused'.

	If those commands differ on your system we can adapt parsing accordingly.
	'''

	# 1) Save cursor position
	saved_cursor = None
	try:
		out = hyprctl(['cursorpos']).stdout.strip()
		if out:
			parts = out.replace(',', ' ').split()
			if len(parts) >= 2:
				saved_cursor = (int(float(parts[0])), int(float(parts[1])))
	except Exception:
		# If cursor query fails, we'll still proceed but we can't detect movement
		saved_cursor = None


	# 2) Collect target workspaces (without switching focus) and their clients
	clients = json.loads(hyprctl(['clients', '-j']).stdout)

	def _parse_ws_arg(ws_arg):
		return [entry.strip() for entry in ws_arg.split(',') if entry.strip()]

	def _resolve_workspace(token, workspace_list):
		try:
			return int(token)
		except ValueError:
			for ws in workspace_list:
				if str(ws.get('id')) == token or ws.get('name') == token:
					return ws.get('id')
		return None

	try:
		workspaces_json = json.loads(hyprctl(['workspaces', '-j']).stdout)
	except Exception:
		workspaces_json = []

	ws_ids = []
	if workspaces:
		requested = _parse_ws_arg(workspaces)
		for token in requested:
			resolved = _resolve_workspace(token, workspaces_json)
			if resolved is not None:
				ws_ids.append(resolved)
			else:
				print(f'Warning: workspace '{token}' not found; ignoring')
		ws_ids = list(dict.fromkeys(ws_ids))
	else:
		# default: all visible workspaces (one per monitor)
		ws_ids = [w['id'] for w in workspaces_json if w.get('monitor')]

	# Fallback: active workspace only (JSON)
	if not ws_ids:
		try:
			aws = json.loads(hyprctl(['activeworkspace', '-j']).stdout)
			ws_ids = [aws['id']]
		except Exception:
			pass

	if not ws_ids:
		print('No visible/active workspaces — aborting screensaver')
		return

	clients_in_ws = [c for c in clients if c.get('workspace', {}).get('id') in set(ws_ids)]
	monitors = json.loads(hyprctl(['monitors', '-j']).stdout)

	ws_geom = {}    # ws_id -> (screen_w, screen_h) in pixels, rotation-aware, scale-compensated
	ws_origin = {}  # ws_id -> (origin_x, origin_y) in global compositor coordinates

	for m in monitors:
		try:
			wsid = m['activeWorkspace']['id']
			rotated = m.get('transform') in (1, 3, 5, 7)
			w = int(m['width']  / m['scale'])
			h = int(m['height'] / m['scale'])
			ws_geom[wsid] = (h, w) if rotated else (w, h)
			ws_origin[wsid] = (int(m.get('x', 0)), int(m.get('y', 0)))
		except Exception:
			pass

	# sensible fallbacks
	fallback_w, fallback_h = (1920, 1080)
	fallback_ox, fallback_oy = (0, 0)
	if monitors:
		m0 = monitors[0]
		rotated0 = m0.get('transform') in (1, 3, 5, 7)
		w0 = int(m0['width']  / m0['scale'])
		h0 = int(m0['height'] / m0['scale'])
		fallback_w, fallback_h = ((h0, w0) if rotated0 else (w0, h0))
		fallback_ox, fallback_oy = (int(m0.get('x', 0)), int(m0.get('y', 0)))
	# Map visible workspaces to their monitor pixel size (accounts for transform & scale)
	monitors = json.loads(hyprctl(['monitors', '-j']).stdout)
	ws_geom = {}
	for m in monitors:
		try:
			wsid = m['activeWorkspace']['id']
			# rotated transforms: 1,3,5,7
			rotated = m.get('transform') in (1, 3, 5, 7)
			w = int(m['width']  / m['scale'])
			h = int(m['height'] / m['scale'])
			ws_geom[wsid] = (h, w) if rotated else (w, h)
		except Exception:
			pass

	# Map visible workspaces to their monitor global origin (x,y)
	ws_origin = {}
	for m in monitors:
		try:
			wsid = m['activeWorkspace']['id']
			# Hyprland monitor origin in the global layout
			ws_origin[wsid] = (int(m['x']), int(m['y']))
		except Exception:
			pass

	# Fallback origin for any workspace we didn’t see
	fallback_ox, fallback_oy = (0, 0)
	if monitors:
		m0 = monitors[0]
		fallback_ox, fallback_oy = (int(m0.get('x', 0)), int(m0.get('y', 0)))

	# A fallback in case a workspace isn't in ws_geom
	fallback_w, fallback_h = (1920, 1080)
	if monitors:
		m0 = monitors[0]
		rotated0 = m0.get('transform') in (1, 3, 5, 7)
		w0 = int(m0['width']  / m0['scale'])
		h0 = int(m0['height'] / m0['scale'])
		fallback_w, fallback_h = ((h0, w0) if rotated0 else (w0, h0))
		


	# 3) Save original states and make windows floating
	saved_windows = []

	# Compute non-overlapping sizes/positions for all windows in the workspace.
	# We'll place them on a grid (cols x rows) that fits all windows. Each window
	# will be at most a ration set in settings of the screen size and centered within its cell.
	N = len(clients_in_ws)
	computed = {}
	if N > 0:
		monitors = json.loads(hyprctl(['monitors', '-j']).stdout)
		# Prefer the monitor of the first target workspace for sizing grid
		screen_width = None
		screen_height = None
		if ws_ids:
			target_ws = int(ws_ids[0])
			for monitor in monitors:
				if monitor['activeWorkspace']['id'] == target_ws:
					transform = monitor['transform'] in [1, 3, 5, 7]
					screen_width = int(monitor['width'] / monitor['scale']) if not transform else int(monitor['height'] / monitor['scale'])
					screen_height = int(monitor['height'] / monitor['scale']) if not transform else int(monitor['width'] / monitor['scale'])
					break
		if screen_width is None or screen_height is None:
			if monitors:
				monitor = monitors[0]
				transform = monitor['transform'] in [1, 3, 5, 7]
				screen_width = int(monitor['width'] / monitor['scale']) if not transform else int(monitor['height'] / monitor['scale'])
				screen_height = int(monitor['height'] / monitor['scale']) if not transform else int(monitor['width'] / monitor['scale'])
		if screen_width is None or screen_height is None:
			screen_width = screen_width or 1920
			screen_height = screen_height or 1080

		cols = max(1, math.ceil(math.sqrt(N * (screen_width / screen_height)))) if screen_height > 0 else max(1, math.ceil(math.sqrt(N)))
		rows = max(1, math.ceil(N / cols))

		cell_w = max(1, int(screen_width / cols))
		cell_h = max(1, int(screen_height / rows))

		max_w = min(int(screen_width * RESIZE), int(cell_w * 0.9))
		max_h = min(int(screen_height * RESIZE), int(cell_h * 0.9))


		for i, c in enumerate(clients_in_ws):
			col = i % cols
			row = i // cols
			w = max(1, max_w)
			h = max(1, max_h)
			x = int(col * cell_w + (cell_w - w) / 2)
			y = int(row * cell_h + (cell_h - h) / 2)
			computed[c.get('address')] = {'size': [w, h], 'at': [x, y]}

	# assign computed sizes/positions when making windows floating
	placed_rects = []  # track placed rects to prevent overlaps after jitter: [x, y, w, h]
	for c in clients_in_ws:
		wsid = c['workspace']['id']
		sw, sh = ws_geom.get(wsid, (fallback_w, fallback_h))  # per-monitor width/height (already computed above)
#hre
		addr = c.get('address')
		if not addr:
			continue
		comp = computed.get(addr, {})
		anim_size = comp.get('size', c.get('size'))

		if size:
			anim_size[0] = min(anim_size[0], size[0])
			anim_size[1] = min(anim_size[1], size[1])

		# Add some randomness to the position so windows don't align perfectly
		base_at = comp.get('at', c.get('at'))
		if base_at:
			# Use a unique random generator per window to avoid same offsets
			rng = random.Random(str(addr))
			cell_w = max(1, cell_w)
			cell_h = max(1, cell_h)
			w, h = anim_size
			# Keep max offset within the free margin of the cell to avoid crossing cells
			max_dx = max(0, int((cell_w - w) / 2))
			max_dy = max(0, int((cell_h - h) / 2))
			retries = 0
			while True:
				dx = rng.randint(-max_dx, max_dx)
				dy = rng.randint(-max_dy, max_dy)
				x = base_at[0] + dx
				y = base_at[1] + dy
				# Ensure window is fully on screen
				if not (0 <= x <= sw - w and 0 <= y <= sh - h):
					retries += 1
					if retries > 50:
						# fallback to clamped position if too many retries
						x = min(max(0, x), sw - w)
						y = min(max(0, y), sh - h)
						anim_at = [x, y]
						break
					continue

				# Check against already placed rects to avoid overlaps
				overlap = False
				for rx, ry, rw, rh in placed_rects:
					if not (x + w <= rx or rx + rw <= x or y + h <= ry or ry + rh <= y):
						overlap = True
						break
				if not overlap:
					anim_at = [x, y]
					break
				retries += 1
				if retries > 50:
					# give up on jitter and use base position instead
					anim_at = [base_at[0], base_at[1]]
					break

		# save minimal state including original client values so we can restore them
		saved_windows.append({
			'address': addr,
			'at': anim_at,
			'size': anim_size,
			'orig_at': c.get('at'),
			'orig_size': c.get('size'),
			'floating': c.get('floating', False),
		})

		# Make floating and ensure size/position match animation values
		hyprctl(['dispatch', 'setfloating', f'address:{addr}'])
		if anim_size:
			hyprctl(['dispatch', 'resizewindowpixel', 'exact', str(anim_size[0]), str(anim_size[1]), f',address:{addr}'])
		# Ensure we have a valid anim_at even if base_at wasn't available
		if not base_at:
			# fallback to client position or origin
			anim_at = list(c.get('at') or [0, 0])
			# clamp to screen
			try:
				w, h = anim_size
				anim_at[0] = min(max(0, int(anim_at[0])), max(0, sw - w))
				anim_at[1] = min(max(0, int(anim_at[1])), max(0, sh - h))
			except Exception:
				pass
		if anim_at:
			# convert RELATIVE (monitor-local) to GLOBAL (compositor)
			ox, oy = ws_origin.get(wsid, (fallback_ox, fallback_oy))
			gx = int(anim_at[0] + ox)
			gy = int(anim_at[1] + oy)
			hyprctl(['dispatch', 'movewindowpixel', 'exact', str(gx), str(gy), f',address:{addr}'])
			# remember rect to avoid overlaps for next windows
			placed_rects.append((anim_at[0], anim_at[1], anim_size[0], anim_size[1]))

		# Add to manager so it will be animated, pass pixel size and initial position to HyprDVD
		inst = HyprDVD.from_client(c, manager, size=anim_size, at=anim_at)
		inst.screen_width  = sw
		inst.screen_height = sh
		inst.offset_x, inst.offset_y = ws_origin.get(wsid, (fallback_ox, fallback_oy))
		manager.windows.append(inst)

	if not manager.windows:
		print('No windows found in current workspace to animate')
		return

	print(f'Running screensaver on workspaces {ws_ids} with {len(manager.windows)} windows')

	# Choose exit behavior
	stop_requested = False
	if exit_on == 'signal':
		import signal
		def _sigint(*_):
			nonlocal stop_requested
			stop_requested = True
		signal.signal(signal.SIGINT, _sigint)

	# 4) Animate until cursor moves
	try:
		while True:
			# check cursor movement
			moved = False
			if exit_on == 'pointer' and saved_cursor is not None:
				try:
					out = hyprctl(['cursorpos']).stdout.strip()
					parts = out.replace(',', ' ').split()
					if len(parts) >= 2:
						cur = (int(float(parts[0])), int(float(parts[1])))
						if cur != saved_cursor:
							moved = True
				except Exception:
					# unable to read cursor; do not treat as moved
					pass

			if moved or stop_requested:
				print('Cursor moved — restoring windows and exiting screensaver')
				break

			# otherwise update animation
			manager.update_windows()
			time.sleep(poll_interval)
	finally:
		# 5) restore saved windows to original positions/sizes/floating state
		# Restore window sizes/positions and floating state to their ORIGINAL
		# values (orig_at / orig_size) when available, while keeping them
		# floating. Collect original area so we can tile largest->smallest.
		batch_cmds = []
		addr_area = []
		for w in saved_windows:
			addr = w['address']
			orig_size = w.get('orig_size') or w.get('size')
			orig_at = w.get('orig_at') or w.get('at')
			if orig_size:
				hyprctl(['dispatch', 'resizewindowpixel', 'exact', str(orig_size[0]), str(orig_size[1]), f',address:{addr}'])
			if orig_at:
				hyprctl(['dispatch', 'movewindowpixel', 'exact', str(orig_at[0]), str(orig_at[1]), f',address:{addr}'])
			# restore floating state
			if not w.get('floating'):
				hyprctl(['dispatch', 'setfloating', 'no', f'address:{addr}'])

			# compute area for ordering (fallback to animation size if orig_size missing)
			area = 0
			try:
				s = orig_size or w.get('size')
				area = int((s[0] or 0) * (s[1] or 0))
			except Exception:
				area = 0
			addr_area.append((addr, area))

		# Now tile from largest to smallest by building a batched list of
		# focus+settiled commands in that order and executing them once.
		if addr_area:
			addr_area.sort(key=lambda x: x[1], reverse=True)
			for addr, _ in addr_area:
				batch_cmds.append(f'dispatch focuswindow address:{addr}')
				batch_cmds.append(f'dispatch settiled address:{addr}')
			if batch_cmds:
				hyprctl(['--batch', ';'.join(batch_cmds)])

		print('Restored windows. Screensaver finished.')
		# set the cursor back to the saved position if available
		if saved_cursor is not None:
			hyprctl(['dispatch', 'movecursor', str(saved_cursor[0]), str(saved_cursor[1])])
