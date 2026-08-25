FROM mcr.microsoft.com/devcontainers/base:ubuntu

RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends make rsync tar \
    && rm -rf /var/lib/apt/lists/*
