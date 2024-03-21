#!/bin/bash
set -e
echo "running flake8"
flake8
echo "running isort"
isort ./ --check -q
echo "running black"
black ./ --check
echo "running pyright"
pyright --level error