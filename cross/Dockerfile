# Dockerfile for running `bazel test //...` in a Linux container

# Use Ubuntu 22.04 as the base image
FROM ubuntu:22.04

SHELL ["/bin/bash", "-c"]

# Set the working directory
WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y curl build-essential git libglu1-mesa libglu1-mesa-dev python3

# Install Nix using determinate systems installation
RUN curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install linux --init none --no-confirm

# Install NVM
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash

# Ensure NVM is sourced in the current shell
RUN source ~/.nvm/nvm.sh && nvm install 16 && nvm use 16

# Install Bazelisk
RUN source ~/.nvm/nvm.sh && npm install -g @bazel/bazelisk

# Run the tests
CMD ["/bin/bash", "-c", "export USER=root; source /nix/var/nix/profiles/default/etc/profile.d/nix.sh && source ~/.nvm/nvm.sh && bazel test //..."]
