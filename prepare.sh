#!/bin/bash
virtualenv venv --python=python3
source venv/bin/activate
pip install -r requirements.pip
make
