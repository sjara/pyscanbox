"""Setup script for pyscanbox.

For development installation:
    pip install -e .

For development with all extras:
    pip install -e .[gui,dev]
"""

from setuptools import setup, find_packages

setup(
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    include_package_data=True,
)
