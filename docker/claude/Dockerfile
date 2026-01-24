FROM ghcr.io/mars-mx/wiggy-base:latest

# Switch to wiggy user for Claude installation
USER wiggy

# Install Claude Code (installs to ~/.local/bin = /home/wiggy/.local/bin)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Update PATH for wiggy user (home is /home/wiggy)
ENV PATH="/home/wiggy/.local/bin:${PATH}"

# Copy entrypoint script (root can write to /usr/local/bin)
USER root
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Run as wiggy
USER wiggy

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
