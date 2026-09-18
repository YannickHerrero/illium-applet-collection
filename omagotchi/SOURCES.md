# Sources and license

Independent, unofficial Windows/Slint port of [SLcode777/omagotchi](https://github.com/SLcode777/omagotchi), revision `c04d94a` (see upstream `Service.qml`, `Panel.qml`, `PetSprite.qml`).

The growth chart, care rules and original monochrome sprites/decorations are adapted under the MIT license, copyright (c) 2026 SLcode777. The complete upstream notice is preserved in `LICENSE`. Windows provider, room-only gameplay, Slint presentation and installer adaptations: copyright (c) 2026 YannickHerrero, also MIT.

`assets/sprites/*.png` are unchanged upstream artwork. Root-level PNGs are identical copies of the idle/sleep first frames, because Winarchy's dynamic bar icon field accepts only plain filenames in the applet directory. No sound files, playback code or audio settings are included. The Creative Commons sound assets are not redistributed.

Differences from upstream: no desktop roaming, no package/update probes, no middle-click bar action, no animated bar icon, no system notifications. Room play replaces roaming's boredom relief. A snack restores 35 hunger points, scrubbing restores up to 25 cleanliness points per gesture, playing restores 25 fun points and costs 3 energy points. Care animations are visual feedback, not asynchronous transactions; completed actions save immediately. Tired pets settle at the next active-minute tick instead of a 30-second doze timer. Evolution thresholds and adult branches follow upstream.
