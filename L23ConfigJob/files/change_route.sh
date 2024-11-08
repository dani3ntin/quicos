#!/bin/bash

CONFIG_FILE="/opt/openbach/scripts/curr_route.conf"
vms=("c1" "s1")
cmd_sat=("sudo ip route change 10.0.40.0/24 via 10.0.100.1" "sudo ip route change 10.0.10.0/24 via 10.0.40.254")
cmd_terr=("sudo ip route change 10.0.40.0/24 via 10.0.30.1" "sudo ip route change 10.0.10.0/24 via 10.0.40.1")
curr_route=$(head -n 1 "$CONFIG_FILE")
echo "Current route: $curr_route"

if [ "$curr_route" == "sat" ]
then
    echo "switching from sat to terr communication"
    for i in "${!vms[@]}"; do
        ( vagrant ssh ${vms[i]} -c "${cmd_terr[i]}" ) &
    done
else
    echo "switching from terr to sat communication"
    for i in "${!vms[@]}"; do
        ( vagrant ssh ${vms[i]} -c "${cmd_sat[i]}" ) &
    done
fi

if [ "$curr_route" == "sat" ]; then
    echo "terr" > "$CONFIG_FILE"
else
    echo "sat" > "$CONFIG_FILE"
fi

wait
echo All subshells finished

