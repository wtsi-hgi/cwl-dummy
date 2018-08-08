from setuptools import setup


setup(
    name="cwl-dummy",
    version="0.0.1",
    packages=["cwl_dummy"],
    python_requires=">=3.6",
    install_requires=[
        "ruamel.yaml < 0.16",
    ],
    entry_points={
        "console_scripts": ["cwl-dummy=cwl_dummy:main"],
    },
)
