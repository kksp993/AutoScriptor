from setuptools import setup, find_packages
from nuitka.distutils import NuitkaExtension

setup(
    name="ZmxyOL",
    version="0.1.0",
    packages=find_packages(include=["ZmxyOL", "ZmxyOL.*"]),
    ext_modules=[NuitkaExtension(module_name="ZmxyOL")],
    include_package_data=True,
    install_requires=[],  # 依赖通过外部requirements.txt安装，不打包进wheel
) 