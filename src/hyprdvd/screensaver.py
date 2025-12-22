import time
import json
import math
import random
from collections import defaultdict

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

	try:
		monitors = json.loads(hyprctl(['monitors', '-j']).stdout)
	except Exception:
		monitors = []

	ws_ids = []
	if workspaces:
		requested = _parse_ws_arg(workspaces)
		for token in requested:
			resolved = _resolve_workspace(token, workspaces_json)
			if resolved is not None:
				ws_ids.append(resolved)
			else:
				print(f'Warning: workspace {token} not found; ignoring')
		ws_ids = list(dict.fromkeys(ws_ids))
	else:
		for monitor in monitors:
			try:
				wsid = monitor['activeWorkspace']['id']
			except Exception:
				continue
			ws_ids.append(wsid)
		ws_ids = list(dict.fromkeys(ws_ids))

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

	target_ws_ids = set(ws_ids)
	clients_by_ws = {wsid: [] for wsid in ws_ids}
	for client in clients:
		wsid = client.get('workspace', {}).get('id')
		if wsid in target_ws_ids:
			clients_by_ws[wsid].append(client)

	clients_in_ws = [client for wsid in ws_ids for client in clients_by_ws.get(wsid, [])]

	ws_geom = {}    # ws_id -> (screen_w, screen_h) in pixels, rotation-aware, scale-compensated
	ws_origin = {}  # ws_id -> (origin_x, origin_y) in global compositor coordinates

	for m in monitors:
		try:
			wsid = m['activeWorkspace']['id']
		except Exception:
			continue

		try:
			scale = float(m.get('scale', 1)) or 1.0
		except Exception:
			scale = 1.0

		try:
			width = int(float(m['width']) / scale)
			height = int(float(m['height']) / scale)
		except Exception:
			continue

		if m.get('transform') in (1, 3, 5, 7):
			width, height = height, width

		ws_geom[wsid] = (max(1, width), max(1, height))
		ws_origin[wsid] = (int(m.get('x', 0)), int(m.get('y', 0)))

	# fallbacks in case monitor info is missing
	fallback_w, fallback_h = (1920, 1080)
	fallback_ox, fallback_oy = (0, 0)
	if monitors:
		m0 = monitors[0]
		try:
			scale = float(m0.get('scale', 1)) or 1.0
		except Exception:
			scale = 1.0
		try:
			width = int(float(m0['width']) / scale)
			height = int(float(m0['height']) / scale)
		except Exception:
			width, height = fallback_w, fallback_h
		if m0.get('transform') in (1, 3, 5, 7):
			width, height = height, width
		fallback_w, fallback_h = (max(1, width), max(1, height))
		fallback_ox, fallback_oy = (int(m0.get('x', 0)), int(m0.get('y', 0)))



	# 3) Save original states and make windows floating
	saved_windows = []
	saved_focus = None

	# Compute non-overlapping sizes/positions for all windows in the workspace.
	# We'll place them on a grid (cols x rows) that fits all windows. Each window
	# will be at most a ratio set in settings of the screen size and centered within its cell.
	computed = {}
	for wsid, ws_clients in clients_by_ws.items():
		N = len(ws_clients)
		if N == 0:
			continue

		sw, sh = ws_geom.get(wsid, (fallback_w, fallback_h))
		sw = max(1, sw)
		sh = max(1, sh)

		if sh > 0:
			cols = max(1, math.ceil(math.sqrt(N * (sw / sh))))
		else:
			cols = max(1, math.ceil(math.sqrt(N)))
		rows = max(1, math.ceil(N / cols))

		cell_w = max(1, int(sw / cols))
		cell_h = max(1, int(sh / rows))

		max_w = min(int(sw * RESIZE), int(cell_w * 0.9))
		max_h = min(int(sh * RESIZE), int(cell_h * 0.9))

		for idx, client in enumerate(ws_clients):
			col = idx % cols
			row = idx // cols
			w = max(1, max_w)
			h = max(1, max_h)
			x = int(col * cell_w + (cell_w - w) / 2)
			y = int(row * cell_h + (cell_h - h) / 2)
			computed[client.get('address')] = {
				'size': [w, h],
				'at': [x, y],
				'cell_w': cell_w,
				'cell_h': cell_h,
			}

	# assign computed sizes/positions when making windows floating
	placed_rects = defaultdict(list)  # track rects per workspace to prevent overlaps
	for c in clients_in_ws:
		wsid = c['workspace']['id']
		sw, sh = ws_geom.get(wsid, (fallback_w, fallback_h))  # per-monitor width/height

		addr = c.get('address')
		if not addr:
			continue

		comp = computed.get(addr, {})

		if comp.get('size'):
			anim_size = list(comp['size'])
		else:
			anim_size = list(c.get('size') or [int(sw * RESIZE), int(sh * RESIZE)])

		if size:
			try:
				anim_size[0] = min(anim_size[0], size[0])
				anim_size[1] = min(anim_size[1], size[1])
			except Exception:
				pass

		base_at = comp.get('at')
		if base_at is not None:
			base_at = list(base_at)
		else:
			try:
				cx, cy = c.get('at', [0, 0])
				ox, oy = ws_origin.get(wsid, (fallback_ox, fallback_oy))
				base_at = [int(cx) - ox, int(cy) - oy]
			except Exception:
				base_at = [0, 0]

		cell_w = max(1, int(comp.get('cell_w', sw)))
		cell_h = max(1, int(comp.get('cell_h', sh)))

		anim_at = list(base_at)
		if base_at:
			# Use a unique random generator per window to avoid same offsets
			rng = random.Random(str(addr))
			w, h = int(anim_size[0]), int(anim_size[1])
			# Keep max offset within the free margin of the cell to avoid crossing cells
			max_dx = max(0, int((cell_w - w) / 2))
			max_dy = max(0, int((cell_h - h) / 2))
			retries = 0
			rects_for_ws = placed_rects[wsid]
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

				# Check against already placed rects to avoid overlaps within workspace
				overlap = False
				for rx, ry, rw, rh in rects_for_ws:
					if not (x + w <= rx or rx + rw <= x or y + h <= ry or ry + rh <= y):
						overlap = True
						break
				if not overlap:
					anim_at = [x, y]
					break
				retries += 1
				if retries > 50:
					# give up on jitter and use base position instead
					anim_at = list(base_at)
					break

		# save minimal state including original client values so we can restore them
		orig_at = c.get('at')
		distance = math.isqrt(orig_at[0] ** 2 + orig_at[1] ** 2)
		saved_windows.append({
			'address': addr,
			'at': anim_at,
			'size': anim_size,
			'fullscreen': c.get('fullscreen'),
			'fullscreenClient': c.get('fullscreenClient'),
			'orig_at': orig_at,
			'orig_size': c.get('size'),
			'floating': c.get('floating', False),
			'distance': distance,
		})

		if c.get('focusHistoryID') == 0:
			saved_focus = addr

		# Make floating and ensure size/position match animation values
		hyprctl(['dispatch', 'setfloating', f'address:{addr}'])
		if anim_size:
			hyprctl(['dispatch', 'resizewindowpixel', 'exact', str(int(anim_size[0])), str(int(anim_size[1])), f',address:{addr}'])
		# Ensure we have a valid anim_at even if base_at wasn't available
		if not base_at:
			# fallback to client position or origin
			anim_at = list(c.get('at') or [0, 0])
			# clamp to screen
			try:
				w, h = int(anim_size[0]), int(anim_size[1])
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
			placed_rects[wsid].append((anim_at[0], anim_at[1], int(anim_size[0]), int(anim_size[1])))

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
		# floating. We use the distance from (0,0) to restore tiling.
		restore_fullscreen = []
		
		saved_windows.sort(key=lambda x: x['distance'], reverse=False)

		for w in saved_windows:
			addr = w['address']
			orig_size = w.get('orig_size') or w.get('size')
			orig_at = w.get('orig_at') or w.get('at')
			if orig_size:
				hyprctl(['dispatch', 'resizewindowpixel', 'exact', str(orig_size[0]), str(orig_size[1]), f',address:{addr}'])
			if orig_at:
				hyprctl(['dispatch', 'movewindowpixel', 'exact', str(orig_at[0]), str(orig_at[1]), f',address:{addr}'])
			# restore tiling state
			if not w.get('floating'):
				hyprctl(['dispatch', 'focuswindow', f'address:{addr}'])
				hyprctl(['dispatch', 'settiled', f'address:{addr}'])
			if w.get('fullscreen') or w.get('fullscreenClient'):
				restore_fullscreen.append((addr, str(w.get('fullscreen')), str(w.get('fullscreenClient'))))

		# fullscreen state must be restored after rearranging all windows
		for w in restore_fullscreen:
			hyprctl(['--batch', 'dispatch', 'focuswindow', f'address:{w[0]}', ';', 'dispatch', 'fullscreenstate',  w[1], w[2]])

		print('Restored windows. Screensaver finished.')
		# set the cursor back to the saved position if available
		if saved_cursor is not None:
			hyprctl(['dispatch', 'movecursor', str(saved_cursor[0]), str(saved_cursor[1])])

		# set the focus back to the window
		if saved_focus is not None:
			hyprctl(['dispatch', 'focuswindow', f'address:{saved_focus}'])
