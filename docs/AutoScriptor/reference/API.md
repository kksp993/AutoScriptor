# Script API

## Version

`AutoScriptor/api_version.py`: API_VERSION/get_api_version/pending/releases; runtime-free, software/HTTP-independent.

Bump MINOR for substantial/user-requested public core/api.py changes; otherwise accumulate. Exclude UI/docs/comments/refactors; confirm breaking migrations; synchronize catalog/tests/records.

[Reference](../../../backend/core/script_api_reference.py): runtime-free AST signatures. [Catalog](../../../backend/core/script_api_catalog.py): plain language, practical limits. [Tests](../../../test/webui/test_script_api_reference.py).

## Contracts

- Lazy imports; init(launch_app=False) skips game. init: session-only emulator_index/adb_addr; None=cfg. ensure_app_running requires resolved matching adb_addr, rejects None. Local instances 0..31/IPC ports; verify Manager/ADB/Android/capture. Never silently switch/cache mixctrl/mumu.
- T/I/B=text/image/coordinate. locate: tuple=OR,list=AND,mixed=image-first; partials contain None. Plain B always hits; coordinate/Box B retains color for locating, resource-key B drops it. Direct click/click_all(B) ignore color/if_exist. match=dict/None(all/index/path/target/box/boxes); path=nested index.
- click lists=OR; if_exist missing=False; repeat=same box; until interval0.5s, otherwise0s. seq_click: ordered transitions,10s/item,empty=True,until final-only,if_exist first-only; reuse transition boxes/two-frame stability; failure/cancel stops clicks.
- click_all: frozen row-order matches/count. swipe random; swipe_precise center-to-center. input/key_event deliver only; sleep cancellable. ui_T/ui_F: fixed screenshot; appear=TimeoutError,disappear=RuntimeError; get_colors=matrix,coloris=OR/AND.
- Box=(x,y,width,height),1280x720 absolute. Other apps: native orientation, margin(frame_size=...); mismatch warns/returns original.
- extract_info: text=OCR,img=registered key,both=image-first/cell; preserves scalar/list/grid. Unread=None/empty; post_process retries then None; screenshot_frame=fixed BGR. pretext/posttext/prenum/postnum=edge nondigits/unsigned integers, not decimals/units. Stale nonempty != success.
- locate_dyn: fixed frame 0, 8-connected differences, first-hit list[Box], else TimeoutError; min_area=side/(width,height), tolerance=5/side. interval=0.2, threshold=20, timeout=5; shared deadline, resolve-all B, no accumulation. Changes != claimability. test/runtime/test_locate_dyn.py.

[Configuration/paths](../architecture.md),[realtime](fast-path.md),[WebUI](../webui/api-contract.md),[tasks](../tasks/script-authoring.md). Exports: AutoScriptor/__init__.py; tests: test/framework/test_framework_public_api.py,test/runtime/test_core_utils.py.

Maintenance: scripts/audit_ui_assets.py,run_recognition_baselines.py; 1280x720 fixtures, empty exit=2. ZmxyOL/nav/api.py::try_close_via_x: fresh candidates, fails after 20 attempts; loading=30s.
