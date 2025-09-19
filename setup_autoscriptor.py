from setuptools import setup, find_packages
from nuitka.distutils import NuitkaExtension

setup(
    name="AutoScriptor",
    version="0.1.0",
    packages=find_packages(include=["AutoScriptor", "AutoScriptor.*"]),
    ext_modules=[NuitkaExtension(module_name="AutoScriptor")],
    include_package_data=True,
    install_requires=[],  # 依赖通过外部requirements.txt安装，不打包进wheel
) 