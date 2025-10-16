import requests
import zipfile
from pathlib import Path
import shutil
import time

class DownloadService:
    def __init__(self, env_config, project_name):
        self.env_config = env_config
        self.project_name = project_name

    def download_file(self, url, save_path, proxy=None):
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(url, stream=True, timeout=30, proxies=proxy)
        if resp.status_code != 200:
            return False
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
        return True

    def download_and_extract(self, file_name, temp_dir, extract_dir, retry=2, proxy=None):
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = temp_dir / file_name
        download_url = f"{self.env_config.env_source}/{self.project_name}/{file_name}"
        for i in range(retry):
            if not zip_path.exists():
                ok = self.download_file(download_url, zip_path, proxy)
                if not ok:
                    time.sleep(1)
                    continue
            # 解压
            extract_dir = Path(extract_dir)
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_dir)
            return True
        return False