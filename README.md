# HyprDVD

A tiny utility for hyprland that makes windows titled "DVD" float and bounce around like the classic DVD logo — now with a screensaver mode that temporarily animates all windows on the current workspace and restores them when the cursor moves.

## Highlights

- Animates windows titled "DVD" by making them floating and moving them with collision detection.
- Screensaver mode: captures the current workspace windows, makes them float and animate, and restores their original state when the cursor moves.
- Restore behavior attempts to faithfully restore original size/position and then tiles windows.


## Installation

### From the AUR
```bash
yay -S hyprdvd
```

### From source
```bash
git clone https://github.com/nevimmu/hyprdvd
cd hyprdvd

# Install into your environment (pipx recommended)
pipx install .
```

## Usage

Basic usage runs the event-driven mode that listens to Hyprland events and animates any newly opened window whose title is exactly `DVD`:

```bash
hyprdvd
kitty --title DVD
```

Screensaver mode — animate all windows on the current workspace until the cursor moves. You can add it to your idle daemon (ex: hypridle)

```bash
hyprdvd --screensaver
# or
hyprdvd -s
```

You can customize the size of bouncing windows using the `--size` flag with the width and height you want

```bash
# Make windows 200x150 pixels
hyprdvd --size 200x150
```
## Multi-monitor screensaver

`hyprdvd` can animate *all visible workspaces* (i.e., one per monitor) without switching focus or warping the cursor. It restores windows cleanly when asked to stop.

### New flags

- `--workspaces <id,id,...>`  
  Animate only the specified workspace IDs. If omitted, all *visible* workspaces are used (one per monitor).

- `--exit-on {pointer,signal}`  
  Choose how the screensaver exits:
  - `pointer` (default): stop when the cursor moves.
  - `signal`: ignore pointer motion; exit only on `SIGINT` (e.g., via your idle daemon).

### Examples

Run on all visible workspaces, ignore pointer until signaled:
```bash
hyprdvd --screensaver --size 200x150 --exit-on signal
# later:
pkill -INT hyprdvd
