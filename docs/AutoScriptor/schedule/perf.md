# 性能边界

No Windows power/sleep/away mode/display keepalive, CPU affinity or Python/MuMu process/thread-priority changes. All entrypoints use normal scheduling; no boost/unboost/AutoScriptor.utils.perf shell.

Check OCR frequency, screenshot reuse, ADB/NemuIpc/loops. Electron rendering≠Paddle GPU. Preserve [lifecycle](../runtime/lifecycle.md)/cancellation; no contention-hiding retries/sleeps.
