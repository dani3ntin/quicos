import json
import os
import argparse
import collect_agent


def calculate_client_metrics(log_directory):
    """Calcola la media di RTT e Throughput per ogni client e invia i dati."""
    print(f"Processing directory: {log_directory}")  # Debug
    client_metrics = {}
    
    for file in os.listdir(log_directory):
        print(f"Checking file: {file}")  # Debug
        if not (file.endswith(".qlog") or file.endswith(".txt")) or "log_server" in file:
            print(f"Skipping file: {file}")  # Debug
            continue
        
        total_rtt = 0
        total_bytes_in_flight = 0
        count = 0

        with open(os.path.join(log_directory, file), "r") as f:
            for line in f:
                try:
                    log_entry = json.loads(line.strip())
                    if log_entry.get("name") == "recovery:metrics_updated":
                        data = log_entry.get("data", {})
                        total_rtt += data.get("smoothed_rtt", 0)
                        total_bytes_in_flight += data.get("bytes_in_flight", 0)
                        count += 1
                except json.JSONDecodeError:
                    print(f"Skipping invalid JSON line in file: {file}")  # Debug
                    continue
        
        if count > 0:
            average_rtt = total_rtt / count
            average_throughput = total_bytes_in_flight / count
        else:
            average_rtt = 0
            average_throughput = 0

        client_name = file.replace(".qlog", "")
        client_metrics[client_name] = {
            "average_rtt": average_rtt,
            "average_throughput": average_throughput,
        }

        print(f"Metrics for {client_name}: {client_metrics[client_name]}")  # Debug

    # Invia i dati usando send_stat
    timestamp = collect_agent.now()
    for client, metrics in client_metrics.items():
        collect_agent.send_stat(
            timestamp,
            **{
                f"{client}_average_rtt": metrics["average_rtt"],
                f"{client}_average_throughput": metrics["average_throughput"],
            },
        )
        print(
            f"{client} Metrics: Average RTT = {metrics['average_rtt']}ms, "
            f"Average Throughput = {metrics['average_throughput']} bytes"
        )


def calculate_server_fairness(log_directory):
    """Calcola la fairness tra i client leggendo i sqlog dalla cartella più recente."""
    # Trova la cartella più recente in base al nome (formato: YYYY-MM-DD_HH-MM-SS)
    recent_folder = max(
        (os.path.join(log_directory, d) for d in os.listdir(log_directory) if os.path.isdir(os.path.join(log_directory, d))),
        key=lambda d: os.path.basename(d),
        default=None
    )

    if not recent_folder:
        print("Nessuna cartella trovata nella directory specificata.")
        return

    print(f"Lettura dei file dalla cartella più recente: {recent_folder}")

    client_throughputs = []

    print(f"Files in directory: {os.listdir(recent_folder)}")

    for file in os.listdir(recent_folder):
        if not file.endswith(".sqlog") or "log_server" in file:
            continue

        total_bytes_in_flight = 0
        count = 0

        with open(os.path.join(recent_folder, file), "r") as f:
            for line in f:
                try:
                    log_entry = json.loads(line.strip())
                    if log_entry.get("name") == "recovery:metrics_updated":
                        data = log_entry.get("data", {})
                        total_bytes_in_flight += data.get("bytes_in_flight", 0)
                        count += 1
                except json.JSONDecodeError:
                    continue

        if count > 0:
            average_throughput = total_bytes_in_flight / count
            client_throughputs.append(average_throughput)

    # Calcolo della fairness di Jain
    print(f"Client throughputs: {client_throughputs}")
    if client_throughputs:
        numerator = sum(client_throughputs) ** 2
        denominator = len(client_throughputs) * sum(x ** 2 for x in client_throughputs)
        fairness = numerator / denominator if denominator != 0 else 0
    else:
        fairness = 0

    # Invia il dato di fairness
    timestamp = collect_agent.now()
    collect_agent.send_stat(timestamp, fairness=fairness)
    print(f"Server Fairness: {fairness}")


def main():
    parser = argparse.ArgumentParser(description="KPIMetrics Job")
    parser.add_argument("log_directory", type=str,
                        help="Percorso base della cartella contenente i file di log.")
    parser.add_argument("mode", type=str,  choices=["server", "client"],
                        help="Modalità di esecuzione ('Server' o 'Client').")
    parser.add_argument("-id", '--experiment_id', type=str,
                        help="Nome della cartella dell'esperimento (solo per il Client).")
    args = parser.parse_args()

    # Costruzione della log_directory finale per il client
    final_log_directory = args.log_directory
    if args.mode == "client" and args.experiment_id:
        final_log_directory = os.path.join(args.log_directory, args.experiment_id)

    with collect_agent.use_configuration('/opt/openbach/agent/jobs/KPIMetrics/KPIMetrics.conf'):
        if args.mode == "client":
            calculate_client_metrics(final_log_directory)
        elif args.mode == "server":
            calculate_server_fairness(final_log_directory)


if __name__ == "__main__":
    main()


