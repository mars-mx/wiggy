FROM ghcr.io/mars-mx/wiggy-base:latest

# Install Claude Code via native installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
