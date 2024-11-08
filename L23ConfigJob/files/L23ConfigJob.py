import subprocess
import syslog

def main():
    try:
        # Log di avvio del job
        syslog.syslog(syslog.LOG_INFO, "L23ConfigJob: Avvio dell'esecuzione dello script change_route.sh.")
        
        # Esegui lo script change_route.sh e cattura il risultato
        result = subprocess.run(
            ["/opt/openbach/scripts/change_route.sh"], 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        
        # Log di successo
        syslog.syslog(syslog.LOG_INFO, f"L23ConfigJob: Script eseguito correttamente. Output: {result.stdout.decode().strip()}")
    
    except subprocess.CalledProcessError as e:
        # Log dell'errore con il messaggio di errore e l'output stderr
        syslog.syslog(syslog.LOG_ERR, f"L23ConfigJob: Errore durante l'esecuzione dello script. "
                                      f"Codice di uscita: {e.returncode}. "
                                      f"Errore: {e.stderr.decode().strip()}")
        exit(1)

if __name__ == "__main__":
    main()

