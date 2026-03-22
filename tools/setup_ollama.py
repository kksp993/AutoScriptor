"""
Ollama + qwen3-vl 部署辅助脚本
==============================
Usage:
    python tools/setup_ollama.py          # 检查 Ollama 状态并拉取模型
    python tools/setup_ollama.py --check  # 仅检查状态
"""

import argparse
import json
import subprocess
import sys
import urllib.request
import urllib.error

OLLAMA_API = "http://localhost:11434"
DEFAULT_MODEL = "hf.co/bartowski/UI-TARS-2B-SFT-GGUF"


def check_ollama_running() -> bool:
    try:
        resp = urllib.request.urlopen(f"{OLLAMA_API}/api/version", timeout=5)
        data = json.loads(resp.read())
        print(f"[OK] Ollama 已运行，版本: {data.get('version', 'unknown')}")
        return True
    except (urllib.error.URLError, OSError):
        print("[FAIL] Ollama 未运行，请先启动 Ollama")
        print("       下载地址: https://ollama.com/download")
        return False


def check_model_available(model: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{OLLAMA_API}/api/show",
            data=json.dumps({"name": model}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        size_gb = data.get("size", 0) / (1024 ** 3)
        print(f"[OK] 模型 {model} 已就绪 ({size_gb:.1f} GB)")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def pull_model(model: str):
    print(f"[...] 正在拉取模型 {model}，请稍候...")
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            check=True,
            text=True,
        )
        print(f"[OK] 模型 {model} 拉取完成")
        return True
    except FileNotFoundError:
        print("[FAIL] 未找到 ollama 命令，请确保 Ollama 已安装并加入 PATH")
        return False
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] 模型拉取失败: {e}")
        return False


def check_openai_endpoint() -> bool:
    try:
        req = urllib.request.Request(
            f"{OLLAMA_API}/v1/models",
            headers={"Authorization": "Bearer ollama"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        models = [m.get("id", "") for m in data.get("data", [])]
        print(f"[OK] OpenAI 兼容端点可用，可用模型: {models[:5]}")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[WARN] OpenAI 兼容端点不可用: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Ollama 部署检查与模型拉取")
    parser.add_argument("--check", action="store_true", help="仅检查状态，不拉取模型")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"模型名称 (默认: {DEFAULT_MODEL})")
    args = parser.parse_args()

    print("=" * 50)
    print("  Ollama + VLM 部署检查")
    print("=" * 50)

    if not check_ollama_running():
        sys.exit(1)

    check_openai_endpoint()

    if check_model_available(args.model):
        print("\n所有检查通过！VLM 已就绪。")
        return

    if args.check:
        print(f"\n[INFO] 模型 {args.model} 未安装，使用 --no-check 来自动拉取")
        sys.exit(1)

    print(f"\n[INFO] 模型 {args.model} 未安装，开始拉取...")
    if pull_model(args.model):
        print("\n部署完成！VLM 已就绪。")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
