#!/bin/sh
# Plays the C3 Lounge radio stream on the TV's HDMI audio, switched over MQTT:
#   krautspace/c3lounge/set    ON | OFF   (send from Home Assistant)
#   krautspace/c3lounge/state  ON | OFF   (retained, published on every change)
#
# Audio only, so the kiosk display is left alone. The player restarts itself
# if the stream drops, until it is switched OFF.
STREAM=http://live.c3lounge.de/listen/c3lounge_radio/192.mp3
SINK=plughw:0,0

set_state() {
    mosquitto_pub -r -t krautspace/c3lounge/state -m "$1"
}

stop_player() {
    pkill -f "$STREAM" 2>/dev/null
}

start_player() {
    stop_player
    sh -c "while :; do gst-launch-1.0 -q souphttpsrc location=$STREAM ! decodebin ! audioconvert ! audioresample ! alsasink device=$SINK; sleep 3; done" &
}

trap 'stop_player; set_state OFF; exit 0' TERM INT

mosquitto_pub -r -t homeassistant/switch/krautspace_c3lounge/config -m '{"name":"C3 Lounge radio","unique_id":"krautspace_c3lounge","command_topic":"krautspace/c3lounge/set","state_topic":"krautspace/c3lounge/state","payload_on":"ON","payload_off":"OFF","icon":"mdi:radio","device":{"identifiers":["krautspace_signage"],"name":"krautspaceTV","manufacturer":"Krautspace"}}'

set_state OFF
mosquitto_sub -t krautspace/c3lounge/set | while IFS= read -r cmd; do
    case "$cmd" in
        ON) start_player; set_state ON ;;
        OFF) stop_player; set_state OFF ;;
    esac
done
