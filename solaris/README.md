# Solaris for Illium

Play [Solaris](https://github.com/YannickHerrero/solaris), the terminal idle game, from the bar. The applet plays the same save as `solaris.exe` on Windows.

## What it does

The bar shows your production per second. The popup has:

- a live energy counter with your production per second and per click,
- the sun: click it to mine energy by hand,
- **Producers**, bought by 1, 10 or as many as you can afford,
- **Upgrades**, the eight cheapest ones currently available,
- your achievements and stellar chips, and a notice when an ascension is ready.

Prestige upgrades and ascension, achievements and statistics, and auto-play stay in the terminal game. While `solaris.exe` runs, the popup only says so: the terminal game owns the save until you quit it, then the applet carries on from its last save.

## How it works

`provider/` is a small Windows program built on Solaris's own game code. Illium runs it every minute and for each action of the popup; a run takes a few milliseconds. Each run locks the save, plays the time elapsed since the last save tick by tick, applies the action, saves and prints the popup's data. The terminal game holds the same lock for as long as it runs.

- The game keeps running while Illium runs, popup open or closed: the provider plays every minute.
- A gap longer than 90 seconds (Windows asleep or shut down, Illium stopped) counts as time away, exactly like closing the terminal game: production up to 8 hours, with the prestige offline bonus.
- Between two runs the popup counts on its own. Buttons follow that live counter, and clicks on the sun are sent in batches every half second, always before a purchase.
- The save is Solaris's on Windows, in `%LOCALAPPDATA%\solaris\data\saves\` (the last one used, or `main`). It is separate from a Solaris save in WSL.

## Install

Build from WSL with [cargo-xwin](https://github.com/rust-cross/cargo-xwin) (Rust 1.89 or later), then install:

```sh
cargo xwin build --release --target x86_64-pc-windows-msvc --manifest-path solaris/provider/Cargo.toml
python3 -B solaris/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

The installer writes the applet and the provider to Illium's `applets/solaris/`, points `command` at the provider's Windows path, and puts the applet first in the drawer, or last in `right` without a drawer. The previous `bar.toml` is backed up under `~/.local/state/illium-applet-collection/backups/`. It refuses to overwrite an existing installation; to upgrade, replace `solaris-applet.exe`, `view.slint` and `icon.svg` by hand.

To play the full game on the same save, build `solaris.exe` the same way from the Solaris repository and run it in any Windows terminal.

## Tests

```sh
cargo test --manifest-path solaris/provider/Cargo.toml
python3 -B -m unittest discover -s solaris/tests
```
