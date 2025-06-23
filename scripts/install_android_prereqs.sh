#!/bin/bash
set -e  # Exit on error

# Function to print status messages
print_status() {
    echo "==> $1"
}

# Install system dependencies
print_status "Updating package lists"
sudo apt update

print_status "Installing system dependencies"
sudo apt install -y \
    git \
    zip \
    unzip \
    openjdk-17-jdk \
    python3-pip \
    autoconf \
    libtool \
    pkg-config \
    zlib1g-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libtinfo5 \
    cmake \
    libffi-dev \
    libssl-dev

# Add local bin to PATH if not already there
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    print_status "Adding ~/.local/bin to PATH"
    echo 'export PATH=$PATH:~/.local/bin/' >> ~/.bashrc
    export PATH=$PATH:~/.local/bin/
fi

print_status "Buildozer dependencies installed successfully"
print_status "You may need to restart your terminal or run 'source ~/.bashrc' to update your PATH" 