FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    git curl wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create workspace directory first (will be wiggy's home)
RUN mkdir -p /workspace

# Create wiggy user with home at /workspace
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid $USER_GID wiggy \
    && useradd --uid $USER_UID --gid $USER_GID -d /workspace -s /bin/bash wiggy \
    && chown wiggy:wiggy /workspace

# Create common mount point for credentials
RUN mkdir -p /mnt/credentials && chown wiggy:wiggy /mnt/credentials

WORKDIR /workspace
