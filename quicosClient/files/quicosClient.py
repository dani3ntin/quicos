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
CERT = "/etc/ssl/certs/quicosClient.openbach.com.crt"
KEY = "/etc/ssl/private/quicosClient.openbach.com.pem"
HTDOCS = "/var/www/quicosClient.openbach.com/"
DOWNLOAD_DIR = tempfile.mkdtemp(prefix='openbach_job_quicosClient-')
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


def remove_resources(resources, download_dir):
    "Delete resources if already presents in *download_dir*"
    for r in resources.split(','):
        r_path = os.path.join(download_dir, r)
        if os.path.exists(r_path):
           os.remove(r_path)





def build_cmd(implementation, mode, server_port, log_file, server_ip=None, resources=None, download_dir=None, extra_args=None, congestion_control=None):
    cmd = []
    _, server_port = _command_build_helper(None, server_port)
    collect_agent.send_log(syslog.LOG_DEBUG, "quicos1: build_cmd: building command")

    if implementation == Implementations.NGTCP2.value:
        if mode == 'client':
            _, server_ip = _command_build_helper(None, server_ip)
            cmd.extend(['wave_client', server_ip, server_port])
            cmd.extend(['https://{}:{}/{}'.format(server_ip, server_port, res) for res in resources])
            cmd.extend(_command_build_helper('--download', download_dir))
            cmd.extend(['--exit-on-all-streams-close'])
            cmd.extend(['--no-http-dump'])
            cmd.extend(['--no-quic-dump'])
#            if congestion_control: cmd.extend(['--cc', congestion_control])
            cmd.extend(_command_build_helper('--qlog-file', log_file))
            if extra_args: cmd.extend(shlex.split(extra_args))
        if mode == 'server':
            cmd.extend(['wave_server', server_ip or '0.0.0.0', server_port])
            cmd.extend([KEY, CERT])
            cmd.extend(_command_build_helper('-d', HTDOCS))
            cmd.extend(_command_build_helper('--qlog-dir', os.path.split(log_file)[0]))
            if congestion_control: cmd.extend(['--cc', congestion_control])
            if extra_args: cmd.extend(shlex.split(extra_args))
        cmd.extend(['-q'])

    return cmd

def tail_file(file_path):
    last_update_time = time.time()
    timeout = 3

    with open(file_path, 'r') as file:
        while True:
            line = file.readline()
            if line:
                cleaned_line = line.strip()
                if cleaned_line:
                    try:
                        data = json.loads(cleaned_line)
                        if data.get("name") == "recovery:metrics_updated":
                            process_statistics(data)

                    except json.JSONDecodeError:
                        pass
                last_update_time = time.time()
            else:
                if time.time() - last_update_time > timeout:
                    break


def process_statistics(data):
    timestamp = data.get("time")
    stats = data.get("data", {})
    statistics = {
        'min_rtt': stats.get('min_rtt'),
        'smoothed_rtt': stats.get('smoothed_rtt'),
        'latest_rtt': stats.get('latest_rtt'),
        'rtt_variance': stats.get('rtt_variance'),
        'pto_count': stats.get('pto_count'),
        'congestion_window': stats.get('congestion_window'),
        'bytes_in_flight': stats.get('bytes_in_flight'),
    }
    #print(statistics)
    #collect_agent.send_stat(collect_agent.now(), **statistics)
    
    
def manage_log_client_directory(base_dir):
    """
    Crea una directory di log per un esperimento identificato da experiment_id
    """
    # Directory specifica per l'esperimento
    os.makedirs(base_dir, exist_ok=True)
    print(f"Usata o creata la directory per l'esperimento: {base_dir}")

    # Determina il nome univoco del file di log
    log_file_name = f"log_client.txt"
    log_file_path = os.path.join(base_dir, log_file_name)

    # Crea il file di log
    with open(log_file_path, "w") as log_file:
        log_file.write("Log inizializzato.\n")
    print(f"Creato file di log: {log_file_path}")

    return log_file_path
    
    
def client(implementation, server_port, log_dir, extra_args, server_ip, resources, download_dir, nb_runs):
    """
    Avvia il client utilizzando un experiment_id per i log.
    """
    ensure_directory_exists(download_dir)
    errors = []
    for run_number in range(nb_runs):
        # Usa experiment_id per creare la directory di log
        log_file_path = manage_log_client_directory(log_dir)

        with open(log_file_path, 'w') as log_file:
            cmd = build_cmd(
                implementation,
                'client',
                server_port,
                log_file.name,
                server_ip,
                resources.split(','),
                download_dir,
                extra_args=extra_args,
            )
            remove_resources(resources, download_dir)

            tail_thread = threading.Thread(target=tail_file, args=(log_file_path,))
            tail_thread.start()

            start_time = collect_agent.now()
            p = run_command(cmd, cwd=download_dir)
            end_time = collect_agent.now()
            
            file_path = os.path.join(download_dir, resources)
            file_size = os.path.getsize(file_path)
            
            time_taken = (end_time - start_time) / 1000
            
            throughput = round((file_size * 8 / time_taken) / 1_000_000, 2) if time_taken > 0 else 0
            
            collect_agent.send_stat(collect_agent.now(), throughput=throughput)

    if errors:
        message = '\n'.join('Error on run #{}: {}'.format(run, error) for run, error in errors)
        collect_agent.send_log(syslog.LOG_ERR, message)
        sys.exit(message)




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
	    'server_ip', type=ip_address, 
	    help='The IP address of the server'
	)
        parser.add_argument(
	    'resources', type=str, 
	    help='Comma-separated list of resources to fetch'
	)
        parser.add_argument(
	    '-d', '--download-dir', type=writable_dir, default=DOWNLOAD_DIR, 
	    help='The path to the directory to save downloaded resources'
	)
        parser.add_argument(
	    '-n', '--nb-runs', type=int, default=1,
	    help='The number of times resources will be downloaded'
	)

        parser.set_defaults(function=client)

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
