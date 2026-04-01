ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    python3 \
    py3-pip

COPY app/requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages \
    -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY rootfs /
COPY app /app

RUN chmod a+x /etc/s6-overlay/s6-rc.d/wu-mqtt-bridge/run \
    && chmod a+x /etc/s6-overlay/s6-rc.d/wu-mqtt-bridge/finish

LABEL \
    io.hass.name="WU-MQTT Bridge" \
    io.hass.description="Bridge WU protocol weather stations to MQTT" \
    io.hass.type="addon" \
    io.hass.version="0.1.0"
