# Fully qualified container name prevents public registry typosquatting
FROM docker.io/library/python:3-alpine

ARG UID=1012
ARG GID=1012

RUN addgroup -S -g $GID vueprom
RUN adduser  -S -g $GID -u $UID -h /opt/vueprom vueprom

WORKDIR /opt/vueprom

# Install pip dependencies with minimal container layer size growth
COPY src/requirements.txt ./
RUN set -x && \
    apk add --no-cache build-base musl-dev linux-headers && \
    pip install --no-cache-dir -r requirements.txt && \
    apk del build-base && \
    rm -rf /var/cache/apk /opt/vueprom/requirements.txt

# Copying code in after requirements are built optimizes rebuild
# time, with only a marginal increate in image layer size; chmod
# is superfluous if "git update-index --chmod=+x ..." is done.
COPY src/*.py ./
RUN  chmod a+x *.py

# A numeric UID is required for runAsNonRoot=true to succeed
USER $UID

ENV VUE_DEBUG=False
ENV VUE_USERNAME=username
ENV VUE_PASSWORD=password

VOLUME /opt/vueprom/conf

EXPOSE 8000

CMD ["/usr/local/bin/uwsgi", "--http","0.0.0.0:8000", "--wsgi-file","vueprom.py","--callable","app","--enable-threads"]

