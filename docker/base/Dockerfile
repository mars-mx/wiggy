FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    git curl wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x LTS from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create workspace and home directories
RUN mkdir -p /home/wiggy /workspace

# Create wiggy user with home at /home/wiggy (not /workspace)
# This prevents volume mounts at /workspace from shadowing installed tools
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid $USER_GID wiggy \
    && useradd --uid $USER_UID --gid $USER_GID -d /home/wiggy -s /bin/bash wiggy \
    && chown wiggy:wiggy /home/wiggy /workspace

# Create common mount point for credentials
RUN mkdir -p /mnt/credentials && chown wiggy:wiggy /mnt/credentials

# Install agent-browser as wiggy user
USER wiggy
# Configure npm to use prefix in home directory for global installs
RUN npm config set prefix '/home/wiggy/.npm-global' \
    && npm install -g agent-browser \
    && /home/wiggy/.npm-global/bin/agent-browser install --with-deps

# Add npm global bin to PATH for wiggy user
ENV PATH="/home/wiggy/.npm-global/bin:${PATH}"

# Switch back to root for any subsequent image layers
USER root

WORKDIR /workspace
