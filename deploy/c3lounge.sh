#!/bin/sh
# Plays the C3 Lounge radio stream on the TV's HDMI audio, switched over MQTT:
#   krautspace/c3lounge/set    ON | OFF   (send from Home Assistant)
#   krautspace/c3lounge/state  ON | OFF   (retained, published on every change)
#   krautspace/c3lounge/volume 0-100      (send from Home Assistant)
#   krautspace/c3lounge/volume_state      (retained, published on every change)
#
# Broker and login come from /etc/krautspace-mqtt.env (set by the systemd unit).
# Audio only, so the kiosk display is left alone. The player restarts itself
# if the stream drops, until it is switched OFF.
STREAM=http://live.c3lounge.de/listen/c3lounge_radio/192.mp3
SINK=plughw:0,0

mqtt_pub() {
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASSWORD" "$@"
}

set_state() {
    mqtt_pub -r -t krautspace/c3lounge/state -m "$1"
}

set_volume() {
    level=$(printf '%s' "$1" | tr -cd '0-9')
    [ -z "$level" ] && return
    [ "$level" -gt 100 ] && level=100
    amixer -c 0 -q sset PCM "${level}%"
    mqtt_pub -r -t krautspace/c3lounge/volume_state -m "$level"
}

stop_player() {
    pkill -f "$STREAM" 2>/dev/null
}

start_player() {
    stop_player
    sh -c "while :; do gst-launch-1.0 -q souphttpsrc location=$STREAM ! decodebin ! audioconvert ! audioresample ! alsasink device=$SINK; sleep 3; done" &
}

trap 'stop_player; set_state OFF; exit 0' TERM INT

DEVICE='"device":{"identifiers":["krautspace_signage"],"name":"krautspaceTV","manufacturer":"Krautspace"}'
mqtt_pub -r -t homeassistant/switch/krautspace_c3lounge/config -m "{\"name\":\"C3 Lounge radio\",\"unique_id\":\"krautspace_c3lounge\",\"command_topic\":\"krautspace/c3lounge/set\",\"state_topic\":\"krautspace/c3lounge/state\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"icon\":\"mdi:radio\",$DEVICE}"
mqtt_pub -r -t homeassistant/number/krautspace_c3lounge_volume/config -m "{\"name\":\"C3 Lounge volume\",\"unique_id\":\"krautspace_c3lounge_volume\",\"command_topic\":\"krautspace/c3lounge/volume\",\"state_topic\":\"krautspace/c3lounge/volume_state\",\"min\":0,\"max\":100,\"step\":1,\"unit_of_measurement\":\"%\",\"mode\":\"slider\",\"icon\":\"mdi:volume-high\",$DEVICE}"

set_state OFF
set_volume "$(amixer -c 0 sget PCM | grep -o '[0-9]*%' | head -1 | tr -d '%')"
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASSWORD" -v -t krautspace/c3lounge/set -t krautspace/c3lounge/volume | while read -r topic payload; do
    case "$topic" in
        */set)
            case "$payload" in
                ON) start_player; set_state ON ;;
                OFF) stop_player; set_state OFF ;;
            esac ;;
        */volume) set_volume "$payload" ;;
    esac
done
