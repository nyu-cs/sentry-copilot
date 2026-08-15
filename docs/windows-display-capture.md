# Windows live display capture

M0.3a.4 adds a read-only `WindowsDisplayFrameSource` backed by `mss`. It selects an explicit
physical monitor using MSS indices starting at `1`; index `0` (the virtual aggregate desktop) is
rejected. MSS returns physical monitor pixels, and every emitted immutable `Frame` records the
actual captured image width and height instead of relying on DPI-scaled logical coordinates.

The bounded smoke command writes only to its caller-selected directory. It does not track windows,
inspect private inputs, detect a viewport or game UI, emit domain observations, or interact with
the game.

```powershell
python -m sentry_copilot.cli capture-display --monitor 1 --target-fps 5 --start-delay-seconds 5 --duration-seconds 10 --dump-every 1 --output data/private/live_validation/sessions/live_capture_smoke_001/
```

This captures the primary physical monitor for a short manual smoke test. It writes `manifest.jsonl`
and sampled PNGs beneath that directory only.
