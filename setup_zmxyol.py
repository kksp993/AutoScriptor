from setuptools import setup, find_packages

setup(
    name="ZmxyOL",
    version="0.1.0",
    packages=find_packages(include=["ZmxyOL", "ZmxyOL.*"]),
    include_package_data=True,
    package_data={
        "ZmxyOL": ["*.py", "*.pyi"],
    },
    include_package_data=True,
    install_requires=[],  # 依赖通过外部requirements.txt安装，不打包进wheel
) 