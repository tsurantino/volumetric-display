#!/bin/bash

set -euo pipefail

# Build the container
docker build -t test cross/

# Run the container, mounting the current directory to /app
docker run -v $(pwd):/app test
