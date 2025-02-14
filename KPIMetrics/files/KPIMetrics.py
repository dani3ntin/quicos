import json
import os
import argparse
import collect_agent

def calculate_server_fairness(log_directory, n_servers):
    """Calcola la fairness tra i client leggendo i log dalle ultime n_servers cartelle più recenti."""
    
    all_folders = [
        os.path.join(log_directory, d) for d in os.listdir(log_directory) if os.path.isdir(os.path.join(log_directory, d))
    ]
    
    sorted_folders = sorted(all_folders, key=lambda d: os.path.basename(d), reverse=True)

    selected_folders = sorted_folders[:n_servers]

    if not selected_folders:
        print("Nessuna cartella valida trovata.")
        return

    print(f"Analisi delle seguenti cartelle: {selected_folders}")

    client_throughputs = []

    for folder in selected_folders:
        print(f"Files in directory {folder}: {os.listdir(folder)}")

        for file in os.listdir(folder):
            if not file.endswith(".sqlog") or "log_server" in file:
                continue

            total_bytes_in_flight = 0
            count = 0

            with open(os.path.join(folder, file), "r") as f:
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

    timestamp = collect_agent.now()
    collect_agent.send_stat(timestamp, fairness=fairness)
    print(f"Server Fairness: {fairness}")

def main():
    parser = argparse.ArgumentParser(description="KPIMetrics Job")
    parser.add_argument("log_directory", type=str, help="Percorso base della cartella contenente i file di log.")
    parser.add_argument("n_server", type=int, help="Numero di cartelle più recenti da analizzare.")
    args = parser.parse_args()
    
    with collect_agent.use_configuration('/opt/openbach/agent/jobs/KPIMetrics/KPIMetrics.conf'):
        calculate_server_fairness(args.log_directory, args.n_server)

if __name__ == "__main__":
    main()
