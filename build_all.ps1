# build_all.ps1

# 1. 激活 zmxy 环境
conda activate zmxy

# 2. 安装打包依赖
pip install --upgrade pip setuptools wheel nuitka

# 3. 清理旧产物（可选）
Remove-Item -Recurse -Force build, wheelhouse, *.dist, *.egg-info -ErrorAction SilentlyContinue

# 4. 编译 AutoScriptor 并打包 wheel
python -m nuitka `
  --module `
  --include-package=AutoScriptor `
  --follow-import-to=AutoScriptor `
  --output-dir=wheelhouse `
  AutoScriptor

# 5. 编译 ZmxyOL 并打包 wheel
python -m nuitka `
  --module `
  --include-package=ZmxyOL `
  --follow-import-to=ZmxyOL `
  --include-data-dir=ZmxyOL/assets=ZmxyOL/assets `
  --include-data-dir=ZmxyOL/task=ZmxyOL/task `
  --output-dir=wheelhouse `
  ZmxyOL

Write-Host "✅ compile done." 