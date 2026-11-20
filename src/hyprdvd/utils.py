import subprocess

def hyprctl(cmd):
	'''A wrapper for the hyprctl command.'''
	return subprocess.run(
		['hyprctl'] + cmd,
		capture_output = True,
		text = True,
		errors = 'ignore',
	)

# Hyprland >= 0.57 uses a Lua config: `hyprctl dispatch` takes a Lua expression.

def _win(address):
	return f"window = 'address:{address}'"

def float_window(address):
	return f'hl.dsp.window.float({{ {_win(address)}, action = "enable" }})'

def tile_window(address):
	return f'hl.dsp.window.float({{ {_win(address)}, action = "disable" }})'

def resize_window(address, w, h):
	return f'hl.dsp.window.resize({{ {_win(address)}, x = {int(w)}, y = {int(h)} }})'

def move_window(address, x, y):
	return f'hl.dsp.window.move({{ {_win(address)}, x = {int(x)}, y = {int(y)} }})'

def focus_window(address):
	return f'hl.dsp.focus({{ {_win(address)} }})'

def close_window(address):
	return f'hl.dsp.window.close({{ {_win(address)} }})'

def fullscreen_state(address, internal, client):
	return (f'hl.dsp.window.fullscreen_state({{ {_win(address)}, '
			f'internal = {int(internal)}, client = {int(client)}, action = "set" }})')

def move_cursor(x, y):
	return f'hl.dsp.cursor.move({{ x = {int(x)}, y = {int(y)} }})'

def dispatch(expr):
	'''Run one Lua dispatcher expression.'''
	return hyprctl(['dispatch', expr])

def dispatch_batch(exprs):
	'''Run several Lua dispatcher expressions in one hyprctl call.'''
	if exprs:
		return hyprctl(['--batch', ';'.join(f'dispatch {e}' for e in exprs)])

def set_animations(enabled):
	'''Enable/disable animations at runtime.'''
	value = 'true' if enabled else 'false'
	return hyprctl(['eval', f'hl.config({{ animations = {{ enabled = {value} }} }})'])
