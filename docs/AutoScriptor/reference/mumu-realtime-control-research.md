# MuMu实时控制调研（历史）

2026-09-29: Windows10.0.26200, MuMu5.30.1.3586 instance0/1280x720, home-screen only. Warm capture n240: mean2.15ms/p95=2.59ms;900x120 HSV/contours n500: median0.170ms. Throughput is not fresh-frame/game-response assurance.

Sources: [EmulatorExtras](https://github.com/MaaXYZ/EmulatorExtras) Mumu header/README, MAA PR17425/17855, BetterGI `GameTask/AutoFishing/Behaviours.cs`. Fingers1..10, down=moving, capture success=0. MAA enabled input later, never removed; Manager>=6.3.2.0 gate contrasts local kernel-MT evidence. Game/background mapping unproven; vendor redistribution rights need review.

Proposed, not shipped: ROI colors/contours, bang-bang hysteresis, velocity/latency prediction; bounded timestamped loop, loss timeout/finally release. Calibrate per game/frame rate; binary input needn't PID. Proposed MaaTouch/minitouch fallback isn't runtime; Android10 SELinux limits minitouch. scrcpy requires custom client, ADB slow, window messages unproven; no host-driver/elevation workaround.

Current implementation: [fast-path](fast-path.md). Layout discovery: `AutoScriptor/utils/mumu_discovery.py`; historical probes are not distributed with this repo. Revalidate versions, portrait behavior, display IDs, timing and game rules before use.
