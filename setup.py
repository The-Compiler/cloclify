#!/usr/bin/env python
import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="cloclify",
    version="0.0.1",
    author="Florian Bruhin",
    author_email="me@the-compiler.org",
    description="A CLI for Clockify, with colors and beautiful output.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/The-Compiler/cloclify",
    project_urls={
        "Bug Tracker": "https://github.com/The-Compiler/cloclify/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="src"),
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "cloclify=cloclify.main:main",
        ],
    },
)
