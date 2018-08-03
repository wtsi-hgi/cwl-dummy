from setuptools import setup


setup(
    name="cwl-dummy",
    version="0.0.1",
    python_requires=">=3.6",
    install_requires=[
        "cwlgen",
        "ruamel.yaml < 0.16",
    ],
    entry_points={
        "console_scripts": ["cwl-dummy=cwl_dummy:main"],
    },
)
