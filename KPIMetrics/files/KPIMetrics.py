import json
import os
import collect_agent

def main():
    with collect_agent.use_configuration('/opt/openbach/agent/jobs/quicos1/quicos1_rstats_filter.conf'):
        log_dir = "/home/vagrant/logs"
        output_file = os.path.join(log_dir, "KPIMetrics_results.txt")

        # Cerca il file di log
        log_file = None
        if os.path.exists(os.path.join(log_dir, "log_client_1.txt")):
            log_file = os.path.join(log_dir, "log_client_1.txt")
        elif os.path.exists(os.path.join(log_dir, "log_server.txt")):
            log_file = os.path.join(log_dir, "log_server.txt")
    
        if not log_file:
            print("Log file not found in /home/vagrant/logs.")
            return

        total_rtt = 0
        total_bytes_in_flight = 0
        count = 0
        start_time = None
        end_time = None

        # Read the log file
        with open(log_file, "r") as f:
            for line in f:
                try:
                    log_entry = json.loads(line.strip())
                    if log_entry.get("name") == "recovery:metrics_updated":
                        data = log_entry.get("data", {})
                        total_rtt += data.get("smoothed_rtt", 0)
                        total_bytes_in_flight += data.get("bytes_in_flight", 0)
                        count += 1

                        # Gestione del tempo di inizio e fine
                        current_time = log_entry.get("time")
                        if start_time is None:
                            start_time = current_time
                        end_time = current_time
                except json.JSONDecodeError:
                    continue  # Ignora righe non valide

        # Calcola RTT e throughput medi
        if count > 0 and start_time is not None and end_time is not None and end_time > start_time:
            average_rtt = total_rtt / count
            average_throughput = total_bytes_in_flight / (end_time - start_time)
        else:
            average_rtt = 0
            average_throughput = 0

        # Scrivi i risultati
        with open(output_file, "w") as f:
            f.write(f"Average RTT: {average_rtt}ms\n")
            f.write(f"Average Throughput: {average_throughput}bytes/sec\n")

        collect_agent.send_stat(
                collect_agent.now(),
                average_rtt=average_rtt,
                average_throughput=average_throughput)
if __name__ == "__main__":
    main()

