import collect_agent
import os
import sys
import argparse

def main():
    config_file = '/opt/openbach/agent/jobs/queueManager/queueManager_rstats_filter.conf'

    # Registra la configurazione con collect_agent
    success = collect_agent.register_collect(config_file)
    if not success:
        print("ERROR: Could not connect to rstats.")
        sys.exit(1)

    # Parsing degli argomenti e logica del job
    parser = argparse.ArgumentParser(description="Queue Manager Job")
    parser.add_argument('action', type=str, choices=['reset_queue', 'set_queue'], help="Action to perform")
    parser.add_argument('queue_type', type=str, choices=['HTB', 'FIFO', 'FQ_CoDel'], nargs='?', default='HTB', help="Type of queue to configure")
    parser.add_argument('--bond', action='store_true', help="Apply to both eth3 and eth4")

    args = parser.parse_args()

    # Logica per gestire i parametri
    if args.action == "reset_queue":
        reset_queue(args.bond)
    elif args.action == "set_queue" and args.queue_type:
        set_queue(args.queue_type, args.bond)
    else:
        print("ERROR: Invalid arguments.")
        sys.exit(1)

def reset_queue(bond):
    interfaces = ['eth3']
    if bond:
        interfaces.append('eth4')

    for iface in interfaces:
        os.system(f"tc qdisc del dev {iface} root")

def set_queue(queue_type, bond):
    interfaces = ['eth3']
    if bond:
        interfaces.append('eth4')

    for iface in interfaces:
        if queue_type == "HTB":
            os.system(f"tc qdisc add dev {iface} handle 1: root htb")
            os.system(f"tc class add dev {iface} classid 1:1 root htb rate 100mbit ceil 100mbit burst 15k cburst 15k")
            os.system(f"tc filter add dev {iface} pref 0 protocol ip u32 match ip dst 0.0.0.0/0 classid 1:1")
        elif queue_type == "FIFO":
            os.system(f"tc qdisc add dev {iface} root pfifo_fast")
        elif queue_type == "FQ_CoDel":
            os.system(f"tc qdisc add dev {iface} root fq_codel")

if __name__ == "__main__":
    main()

