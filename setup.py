# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Setup script for pyscanbox.

Default installation (includes GUI):
    pip install -e .

For development (adds testing and linting tools):
    pip install -e .[dev]
"""

from setuptools import setup, find_packages

setup(
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    include_package_data=True,
)
