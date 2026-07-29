FROM soulter/astrbot:v4.26.7

USER root
WORKDIR /opt/anime-qqbot

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md NOTICE ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY astrbot_plugin_anime_tracking ./astrbot_plugin_anime_tracking
RUN python -m pip install --no-cache-dir .
RUN python -m anime_qqbot.entrypoints.card_smoke

COPY scripts/container-entrypoint.sh /usr/local/bin/anime-qqbot
RUN chmod 0755 /usr/local/bin/anime-qqbot \
    && python -c "import anime_qqbot" \
    && python -c "import sys; sys.path.insert(0, '/opt/anime-qqbot'); import astrbot_plugin_anime_tracking.main"

WORKDIR /AstrBot
ENTRYPOINT ["anime-qqbot"]
CMD ["astrbot"]
