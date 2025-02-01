#!/bin/bash

CONFIG_FILE="/opt/openbach/scripts/curr_route.conf"
HOSTNAME=$(hostname)

if [ "$HOSTNAME" == "b1" ]; then
    cmd_sat="sudo ip route change 10.0.40.0/24 via 10.0.100.1"
    cmd_terr="sudo ip route change 10.0.40.0/24 via 10.0.30.1"
elif [ "$HOSTNAME" == "s1" ]; then
    cmd_sat="sudo ip route change 10.0.10.0/24 via 10.0.40.254"
    cmd_terr="sudo ip route change 10.0.10.0/24 via 10.0.40.1"
else
    echo "Error: script can only be executed on b1 or s1."
    exit 1
fi

curr_route=$(head -n 1 "$CONFIG_FILE")
echo "Current route: $curr_route"

# Switch della rotta
if [ "$curr_route" == "sat" ]; then
    echo "Switching from sat to terr communication"
    $cmd_terr
    echo "terr" > "$CONFIG_FILE"
else
    echo "Switching from terr to sat communication"
    $cmd_sat
    echo "sat" > "$CONFIG_FILE"
fi

wait
echo All subshells finished
