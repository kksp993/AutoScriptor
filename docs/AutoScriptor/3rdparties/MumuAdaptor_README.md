# MumuAdaptor索引

Adapted [mumu-python-api](https://github.com/u-wlkjyy/mumu-python-api), single-trigger instead of background processing. Upstream MuMu>=4 is not all-build assurance.

Import: `from AutoScriptor.control.MumuAdaptor.mumu import Mumu`. emulator.emu_path=MuMuManager.exe, not GUI; adb_path=adb.exe. Discover via WebUI/`AutoScriptor.utils.mumu_discovery`. Constructor: keyword adb_addr, not upstream positional Manager path. Explicit index/list; all() targets every instance.

Source root `AutoScriptor/control/MumuAdaptor/`: `mumu.py` dispatches; `device_facade.py` owns readiness/App/ADB; `api/` groups:
- core: instance create/clone/delete/rename/import/export, power, window, app install/launch/close/state, simulation, performance, shortcut;
- permission/root, driver/bridge, network NAT/bridge/static/DHCP;
- setting: get/all/set/JSON/conditional updates; None restores defaults, key dots/hyphens map to double/triple underscores;
- screen: resolution/DPI/FPS/brightness/rotation; adb: connection info, click/swipe/text/key, push/pull/clear; develop: Android events.

Launch acceptance isn't readiness: wait for ADB device/Android boot. Details: matching api modules/constant.py. GUI `api/screen/gui.py`: strings mean OCR text, images use imgOnScreen. Upstream scrcpy create_handle is not assured; don't add its dependency.

Delete/clear/uninstall/identity/network/ROOT need explicit intent; ROOT while stopped, bridge driver requires administrator, performance changes require restart. Capabilities aren't recommendations: no host elevation/power/priority/affinity fallback. Tasks use public AutoScriptor APIs.
