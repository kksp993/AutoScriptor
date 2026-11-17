# OCR模型实验

Historical `experiment/pp-ocrv6` compared models without changing ocr/T/extraction semantics; v4/compatibility-adapter support was experimental. Current profiles: [ocr_engine.py](../../../AutoScriptor/recognition/ocr_engine.py).

Pins: paddleocr==3.7.0; CPU paddlepaddle==3.2.0 or GPU paddlepaddle-gpu==3.2.2, official CUDA12.9 source. Never coexist. `scripts/install.bat python cpu|gpu` removes both then installs one; default=ocr.use_gpu. Branches share installed packages: reinstall when switching runtime.

Current/baseline profiles: PP-OCRv6 tiny/small/medium det+rec only. Defaults: small text/tiny digits; overrides `AUTOSCRIPTOR_OCR_MODEL/AUTOSCRIPTOR_DIGIT_OCR_MODEL`. BOS downloads. Global/thread-local/digit engines share startup snapshots: model/device changes need restart/matching installation; invalid CUDA fails visibly, no CPU fallback.

Offline entry: `scripts/benchmark_ocr_models.py IMAGE --target TEXT --roi x,y,w,h --repeat 3 --warmup 1`; no device. Separate subprocesses avoid model contention; report `logs/ocr-model-benchmark.json` records versions/device, initialization, median/p95, text/boxes/confidence/target hits. Exclude downloads and warm up. v4 in PaddleOCR3.7 is not the old2.7 stack; compare full stacks in separate environments.

Historical same1280x720 frame,2 warmups/10 runs,27 lines both: CPU mean1.301301s, RTX5060 GPU0.185395s,7.02x; one page, no accuracy/performance promise. Validate target hits/small/joined text before speed; regressions retain image/ROI/raw outputs/confidence. Online acceptance separately follows `docs/agents/online-screenshot-test.md`.
