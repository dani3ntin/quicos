#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# OpenBACH is a generic testbed able to control/configure multiple
# network/physical entities (under test) and collect data from them. It is
# composed of an Auditorium (HMIs), a Controller, a Collector and multiple
# Agents (one for each network entity that wants to be tested).
#
#
# Copyright © 2016-2023 CNES
#
#
# This file is part of the OpenBACH testbed.
#
#
# OpenBACH is a free software : you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY, without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see http://www.gnu.org/licenses/.


"""Sources of the Job quic"""

__author__ = 'Viveris Technologies'
__credits__ = '''Contributors:
 * Francklin SIMO <armelfrancklin.simotegueu@viveris.fr>
'''

import os
import time
import json
import threading
import sys
import string
import random
import shlex
import syslog
import argparse
import tempfile
import subprocess
from enum import Enum
from ipaddress import ip_address
from watchdog.events import FileSystemEventHandler
from datetime import datetime, timedelta
from threading import Thread
from watchdog.observers import Observer
import multiprocessing

import collect_agent


DESCRIPTION = (
        "This job runs a client or a server QUIC. Supported QUIC implementations are: "
        "ngtcp2 \n"
        "By default, for any implemenation, the installed version is the HEAD of the master branch. "
        "If you wish to install another version, you need to modify global variables related to the implementation "
        "at the begining of the install file of the job by speficying the address of the git repository as well as "
        "the version to install"
)

DEFAULT_SERVER_PORT = 4433
DEFAULT_CC = "wave"
CERT = "/etc/ssl/certs/quicosWAVE.openbach.com.crt"
KEY = "/etc/ssl/private/quicosWAVE.openbach.com.pem"
HTDOCS = "/var/www/quicosWAVE.openbach.com/"
DOWNLOAD_DIR = tempfile.mkdtemp(prefix='openbach_job_quicosWAVE-')
LOG_DIR = tempfile.mkdtemp(dir=DOWNLOAD_DIR, prefix='logs-')


class Implementations(Enum):
    NGTCP2='ngtcp2'


class CongestionControls(Enum):
    CUBIC='cubic'
    RENO='reno'
    BBR='bbr'
    WAVE='wave'


class DownloadError(RuntimeError):
    def __init__(self, resource, p):
        self.message = (
                "Error downloading resource '{}'."
                "\n {} \n {}".format(resource, p.stdout.decode(), p.stderr.decode())
                )
        super().__init__(self.message)
        
        
def ensure_directory_exists(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"Directory '{directory_path}' created.")
    elif not os.path.isdir(directory_path):
        raise NotADirectoryError(f"Path '{directory_path}' exists but is not a directory.")
    else:
        print(f"Directory '{directory_path}' already exists.")
    return directory_path
    

class LogFileHandler(FileSystemEventHandler):
    def __init__(self, collect_agent):
        self.collect_agent = collect_agent
        self.file_positions = {}
        self.file_indices = {}
        self.file_start_times = {}
        self.current_index = 1
        self.processes = {}

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".sqlog"):
            print(f"Nuovo file di log creato: {event.src_path}")
            
            if event.src_path not in self.file_indices:
                self.file_indices[event.src_path] = self.current_index
                self.file_start_times[event.src_path] = self.collect_agent.now()
                print(f"Assegnato indice {self.current_index} al file {event.src_path}")
                self.current_index += 1
            else:
                print(f"File {event.src_path} già monitorato con indice {self.file_indices[event.src_path]}")
            
            process = multiprocessing.Process(target=self._read_new_lines, args=(event.src_path,))
            process.start()
            self.processes[event.src_path] = process
            
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".sqlog"):
            # Se il file è già monitorato, ignora
            if event.src_path in self.processes:
                return
            
            # Se un nuovo file viene modificato, avvia un processo
            process = multiprocessing.Process(target=self._read_new_lines, args=(event.src_path,))
            process.start()
            self.processes[event.src_path] = process

    def _read_new_lines(self, file_path):
        """ Legge nuove righe dal file senza bloccare gli altri processi """
        try:
            with open(file_path, "r") as file:
                if file_path in self.file_positions:
                    file.seek(self.file_positions[file_path])
                else:
                    self.file_positions[file_path] = 0

                while True:
                    line = file.readline()
                    if not line:
                        time.sleep(0.5)  # Attendi senza consumare CPU inutilmente
                        continue
                    cleaned_line = line.strip()
                    file_index = self.file_indices.get(file_path, 0)
                    self._process_line(cleaned_line, file_index, file_path)
                    self.file_positions[file_path] = file.tell()
        except Exception as e:
            print(f"Errore durante la lettura del file {file_path}: {e}")

    def _process_line(self, line, file_index, file_path):
        """ Elabora e invia i dati letti dal file """
        try:
            data = json.loads(line)
            timestamp = data.get("time")
            stats = data.get("data", {})

            required_keys = {'min_rtt', 'smoothed_rtt', 'latest_rtt', 'rtt_variance', 'pto_count', 'congestion_window', 'bytes_in_flight'}
            if not all(key in stats for key in required_keys):
                print(f"Riga scartata perché manca almeno una chiave: {stats}")
                return
            
            if any(value is None for value in stats.values()):
                print(f"Riga scartata perché contiene valori None: {stats}")
                return

            statistics = {
                f'min_rtt_{file_index}': stats.get('min_rtt'),
                f'smoothed_rtt_{file_index}': stats.get('smoothed_rtt'),
                f'latest_rtt_{file_index}': stats.get('latest_rtt'),
                f'rtt_variance_{file_index}': stats.get('rtt_variance'),
                f'pto_count_{file_index}': stats.get('pto_count'),
                f'congestion_window_{file_index}': stats.get('congestion_window'),
                f'bytes_in_flight_{file_index}': stats.get('bytes_in_flight'),
            }

            print(f"Nuove statistiche dal file {file_index}: {statistics}")
            MAX_C_LONG = 2**63 - 1  
            congestion_key = f'congestion_window_{file_index}'
            statistics[congestion_key] = min(statistics[congestion_key], MAX_C_LONG)

            file_start_time = self.file_start_times.get(file_path, self.collect_agent.now())
            adjusted_timestamp = int(timestamp) + file_start_time

            self.collect_agent.send_stat(adjusted_timestamp, **statistics)
        except json.JSONDecodeError:
            print(f"Riga non valida (non JSON): {line}")
        except Exception as e:
            print(f"Errore durante il processamento della riga: {e}")

            

def start_watchdog(collect_agent, log_dir):
    event_handler = LogFileHandler(collect_agent)
    observer = Observer()
    observer.schedule(event_handler, path=log_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def run_command(cmd, cwd=None):
    "Run cmd and wait for command to complete then return a CompletedProcessess instance"
    try:
        #p = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd, check=False) #.Popen shell=True

        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE)
        grep = subprocess.Popen(["grep", "python"], stdin=p.stdout, stdout=subprocess.PIPE)
        for line in grep.stdout:
            print(line.decode("utf-8").strip())
        collect_agent.send_log(syslog.LOG_CRIT, "quicos1: run_command: started execution")

    except Exception as ex:
        message = "Error running command '{}': '{}'".format(' '.join(cmd), ex)
        collect_agent.send_log(syslog.LOG_ERR, message)
        collect_agent.send_log(syslog.LOG_CRIT, message)
        print(message)
        sys.exit(message)
    return p


def _command_build_helper(flag, value):
    if value is not None:
        yield flag
        yield str(value)


def build_cmd(implementation, mode, server_port, log_file, server_ip=None, resources=None, download_dir=None, extra_args=None, congestion_control=None):
    cmd = []
    _, server_port = _command_build_helper(None, server_port)
    collect_agent.send_log(syslog.LOG_DEBUG, "quicos1: build_cmd: building command")

    if implementation == Implementations.NGTCP2.value:
        cmd.extend(['wave_server', server_ip or '0.0.0.0', server_port])
        cmd.extend([KEY, CERT])
        cmd.extend(_command_build_helper('-d', HTDOCS))
        cmd.extend(_command_build_helper('--qlog-dir', os.path.split(log_file)[0]))
        if congestion_control: cmd.extend(['--cc', congestion_control])
        if extra_args: cmd.extend(shlex.split(extra_args))
        cmd.extend(['-q'])

    return cmd


def server(implementation, congestion_control, server_port, log_dir, extra_args, server_ip):
    ensure_directory_exists(log_dir)
    
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    output_dir = os.path.join(log_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)
    
    watchdog_thread = Thread(target=start_watchdog, args=(collect_agent, output_dir), daemon=True)
    watchdog_thread.start()
    with open(os.path.join(output_dir, 'log_server.txt'), 'w+') as log_file:
        cmd = build_cmd(implementation, 'server', server_port, log_file.name, server_ip=server_ip, extra_args=extra_args, congestion_control=congestion_control)
        collect_agent.send_log(syslog.LOG_DEBUG, "Command to be executed: " + " ".join(cmd))
        print("Command to be executed:", ' '.join(cmd))
        p = run_command(cmd, cwd=HTDOCS)
        print(f"Return code: {p.returncode}")



def writable_dir(path):
    ''' 
    Check if specified path is a path to an existing writable directory 
    Args:
        path: path to the directory to check
    Returns:
        abspath: absolute path to the directory to check
    Raises:
        ArgumentTypeError: if path does not exist 
                           if path does not a directory
                           if path does not a writable directory
    '''
    if (os.path.exists(path)):
        if not os.path.isdir(path):
            raise argparse.ArgumentTypeError("'{}' is not a path to a directory".format(path))
        if not os.access(path, os.W_OK):
           raise argparse.ArgumentTypeError("Directory is not writable: '{}'".format(path)) 
    else:
        ensure_directory_exists(path)
    return path



if __name__ == "__main__":
#    collect_agent.send_log(syslog.LOG_ERR, 'prova')
    with collect_agent.use_configuration('/opt/openbach/agent/jobs/quicos1/quicos1_rstats_filter.conf'):
        collect_agent.send_log(syslog.LOG_DEBUG, "quicos1: job started")

	# Argument parsing
        parser = argparse.ArgumentParser(
	    description=DESCRIPTION,
	    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            exit_on_error=False
	)

        parser.add_argument(
	    'implementation',
	    choices=[implem.value for implem in Implementations],
	    help='Choose a QUIC implementation (ngtcp only).'
	)

        parser.add_argument(
	    '-p', '--server-port', type=int, default=DEFAULT_SERVER_PORT,
	    help='The server port to connect to/listen on'
	)

        parser.add_argument(
	    '-l', '--log-dir', type=writable_dir, default=LOG_DIR,
	    help='The Path to the directory to save log files'
        )


        parser.add_argument(
	    '-e', '--extra-args', type=str, default=None,
	    help='Allow to specify additional CLI arguments.'
	) 

        parser.add_argument(
            'congestion_control',
            choices=[cc.value for cc in CongestionControls],
            help='The congestion control algorithm to use.'
        )
        parser.add_argument(
	    'server_ip', type=str, 
	    help='The IP address for the server to listen on'
	)

        parser.set_defaults(function=server)

	# Get args and call the appropriate function
        try:
            args = vars(parser.parse_args())
        except argparse.ArgumentError:
            collect_agent.send_log(syslog.LOG_CRIT, "quicos1: main started - got arg exception ") #.join(argparse.ArgumentError.msg))
            collect_agent.send_log(syslog.LOG_DEBUG, "quicos1: main started - got arg exception ") #.join(argparse.ArgumentError.msg))
            collect_agent.send_log(syslog.LOG_ERR, "quicos1: main started - got arg exception ") #.join(argparse.ArgumentError.msg))
            exc = sys.exc_info()[1]
            print(exc)
            sys.exit(20)

        main = args.pop('function')
        main(**args)
