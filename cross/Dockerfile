# Dockerfile for running `bazel test //...` in a Linux container

# Use the nixpkgs/nix image as the base image
FROM nixpkgs/nix:latest

# Set the working directory
WORKDIR /app

# Run the tests
CMD nix --extra-experimental-features nix-command --extra-experimental-features flakes develop ./cross/; bazel test //...
