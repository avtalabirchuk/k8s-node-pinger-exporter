#!/usr/bin/env python3

# Copyright 2021 Flant JSC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import argparse
import subprocess
import prometheus_client
import re
import statistics
import os, sys
import json
import glob
from sys import platform

FPING_REGEX = re.compile(r"^(\S*)\s*: (.*)$", re.MULTILINE)
CONFIG_PATH = os.getenv("CONFIG_PATH", default="config/targets.json")

registry = prometheus_client.CollectorRegistry()

prometheus_exceptions_counter = \
    prometheus_client.Counter('kube_node_ping_exceptions', 'Total number of exceptions', [], registry=registry)

prom_metrics_cluster = {"sent": prometheus_client.Counter('kube_node_ping_packets_sent_total',
                                                          'ICMP packets sent',
                                                          ['destination_node', 'destination_node_ip_address'],
                                                          registry=registry),
                        "received": prometheus_client.Counter('kube_node_ping_packets_received_total',
                                                              'ICMP packets received',
                                                              ['destination_node', 'destination_node_ip_address'],
                                                              registry=registry),
                        "rtt": prometheus_client.Counter('kube_node_ping_rtt_milliseconds_total',
                                                         'round-trip time',
                                                         ['destination_node', 'destination_node_ip_address'],
                                                         registry=registry),
                        "min": prometheus_client.Gauge('kube_node_ping_rtt_min', 'minimum round-trip time',
                                                       ['destination_node', 'destination_node_ip_address'],
                                                       registry=registry),
                        "max": prometheus_client.Gauge('kube_node_ping_rtt_max', 'maximum round-trip time',
                                                       ['destination_node', 'destination_node_ip_address'],
                                                       registry=registry),
                        "mdev": prometheus_client.Gauge('kube_node_ping_rtt_mdev',
                                                        'mean deviation of round-trip times',
                                                        ['destination_node', 'destination_node_ip_address'],
                                                        registry=registry)}


prom_metrics_external = {"sent": prometheus_client.Counter('external_ping_packets_sent_total',
                                                           'ICMP packets sent',
                                                           ['destination_name', 'destination_host'],
                                                           registry=registry),
                        "received": prometheus_client.Counter('external_ping_packets_received_total',
                                                              'ICMP packets received',
                                                              ['destination_name', 'destination_host'],
                                                              registry=registry),
                        "rtt": prometheus_client.Counter('external_ping_rtt_milliseconds_total',
                                                         'round-trip time',
                                                         ['destination_name', 'destination_host'],
                                                         registry=registry),
                        "min": prometheus_client.Gauge('external_ping_rtt_min', 'minimum round-trip time',
                                                       ['destination_name', 'destination_host'],
                                                       registry=registry),
                        "max": prometheus_client.Gauge('external_ping_rtt_max', 'maximum round-trip time',
                                                       ['destination_name', 'destination_host'],
                                                       registry=registry),
                        "mdev": prometheus_client.Gauge('external_ping_rtt_mdev',
                                                        'mean deviation of round-trip times',
                                                        ['destination_name', 'destination_host'],
                                                        registry=registry)}


def validate_envs():
    envs = {"MY_NODE_NAME": os.getenv("MY_NODE_NAME", default="test_node"),
            "PROMETHEUS_TEXTFILE_DIR": os.getenv("PROMETHEUS_TEXTFILE_DIR", default="test/"),
            "PROMETHEUS_TEXTFILE_PREFIX": os.getenv("PROMETHEUS_TEXTFILE_PREFIX", default="monitoring-ping_")}

    for key, value in envs.items():
        if not value:
            raise ValueError("{} environment variable is empty".format(key))

    return envs


@prometheus_exceptions_counter.count_exceptions()
def compute_results(results):
    computed = {}

    matches = FPING_REGEX.finditer(results)
    for match in matches:
        host = match.group(1)
        ping_results = match.group(2)
        if "duplicate" in ping_results:
            continue
        splitted = ping_results.split(" ")
        if len(splitted) != 30:
            raise ValueError("ping returned wrong number of results: \"{}\"".format(splitted))

        positive_results = [float(x) for x in splitted if x != "-"]
        if len(positive_results) > 0:
            computed[host] = {"sent": 30, "received": len(positive_results),
                            "rtt": sum(positive_results),
                            "max": max(positive_results), "min": min(positive_results),
                            "mdev": statistics.pstdev(positive_results)}
        else:
            computed[host] = {"sent": 30, "received": len(positive_results), "rtt": 0,
                            "max": 0, "min": 0, "mdev": 0}
    if not len(computed):
        raise ValueError("regex match\"{}\" found nothing in fping output \"{}\"".format(FPING_REGEX, results))
    return computed


@prometheus_exceptions_counter.count_exceptions()
def call_fping(ips, args, fping_binary):
    fping_cmdline = f'{fping_binary} ' \
                    f'-p {args.period} ' \
                    f'-C {args.vcount} ' \
                    f'-B {args.backoff} ' \
                    f'-q ' \
                    f'-r {args.retry} ' \
                    f'-b {args.size}'.split(" ")
    cmdline = fping_cmdline + ips
    process = subprocess.run(cmdline, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True)
    if process.returncode == 3:
        raise ValueError("invalid arguments: {}".format(cmdline))
    if process.returncode == 4:
        raise OSError("fping reported syscall error: {}".format(process.stderr))

    return process.stdout


def get_param_cli():
    parser = argparse.ArgumentParser(description="add arguments for utils fping")

    parser.add_argument("-p", "--period",
                        help="default: 1000. MSEC: interval between ping packets to one target (in ms)",
                        default="1000"
                        )
    parser.add_argument("-C", "--vcount",
                        help="default: 30. COUNT mode: send N pings to each target",
                        default="30"
                        )
    parser.add_argument("-B", "--backoff",
                        help="default: 1 COUNT: set exponential backoff factor to N",
                        default="1"
                        )
    parser.add_argument("-r", "--retry",
                        help="default: 1, number of retries",
                        default="1"
                        )
    parser.add_argument("-b", "--size",
                        help="default: 100. BYTES: amount of ping data to send, in bytes",
                        default="100"
                        )
    args = parser.parse_args()

    print(f'{args}')
    return args


def get_fping_binary():
    if platform == "linux" or platform == "linux2":
        fping_binary = "/usr/sbin/fping"
    elif platform == "darwin":
        fping_binary = "/opt/homebrew/bin/fping"
    return fping_binary

if __name__ == '__main__':

    envs = validate_envs()

    files = glob.glob(envs["PROMETHEUS_TEXTFILE_DIR"] + "*")
    for f in files:
        os.remove(f)

    labeled_prom_metrics = {"cluster_targets": []}

    while True:
        with open(CONFIG_PATH, "r") as f:
            config = json.loads(f.read())
            # config["external_targets"] = [] if config["external_targets"] is None else config["external_targets"]
            # for target in config["external_targets"]:
            #     target["name"] = target["host"] if "name" not in target.keys() else target["name"]

        if labeled_prom_metrics["cluster_targets"]:
            for metric in labeled_prom_metrics["cluster_targets"]:
                # print(metric)
                metric_name, metric_ip = metric["node_name"], metric["ip"]
                if (metric_name, metric_ip) not in [(node_name, node_ip) for node_name, node_ip in config['cluster_targets'].items()]:
                    for k, v in prom_metrics_cluster.items():
                        v.remove(metric_name, metric_ip)

        # if labeled_prom_metrics["external_targets"]:
        #     for metric in labeled_prom_metrics["external_targets"]:
        #         if (metric["target_name"], metric["host"]) not in [(target["name"], target["host"]) for target in config['external_targets']]:
        #             for k, v in prom_metrics_external.items():
        #                 v.remove(metric["target_name"], metric["host"])


        labeled_prom_metrics = {"cluster_targets": []}

        # for node in config["cluster_targets"]:
        #     metrics = {"node_name": node["name"], "ip": node["ipAddress"], "prom_metrics": {}}

        #     for k, v in prom_metrics_cluster.items():
        #         metrics["prom_metrics"][k] = v.labels(node["name"], node["ipAddress"])

        #     labeled_prom_metrics["cluster_targets"].append(metrics)

        for node_name, node_ip in config["cluster_targets"].items():
            metrics = {"node_name": node_name, "ip": node_ip, "prom_metrics": {}}

            for k, v in prom_metrics_cluster.items():
                metrics["prom_metrics"][k] = v.labels(node_name, node_ip)

            labeled_prom_metrics["cluster_targets"].append(metrics)

        # for target in config["external_targets"]:
        #     metrics = {"target_name": target["name"], "host": target["host"], "prom_metrics": {}}

        #     for k, v in prom_metrics_external.items():
        #         metrics["prom_metrics"][k] = v.labels(target["name"], target["host"])

        #     labeled_prom_metrics["external_targets"].append(metrics)
        fping_binary = get_fping_binary()
        args = get_param_cli()
        out = call_fping([prom_metric["ip"]   for prom_metric in labeled_prom_metrics["cluster_targets"]],
                         args, fping_binary)
                         #[prom_metric["host"] for prom_metric in labeled_prom_metrics["external_targets"]])
        computed = compute_results(out)

        for dimension in labeled_prom_metrics["cluster_targets"]:
            result = computed[dimension["ip"]]
            dimension["prom_metrics"]["sent"].inc(result["sent"])
            dimension["prom_metrics"]["received"].inc(result["received"])
            dimension["prom_metrics"]["rtt"].inc(result["rtt"])
            dimension["prom_metrics"]["min"].set(result["min"])
            dimension["prom_metrics"]["max"].set(result["max"])
            dimension["prom_metrics"]["mdev"].set(result["mdev"])

        # for dimension in labeled_prom_metrics["external_targets"]:
        #     if dimension["host"] in computed:
        #       result = computed[dimension["host"]]
        #     else:
        #       sys.stderr.write("ERROR: fping hasn't reported results for host '" + dimension["host"] + "'. Possible DNS problems. Skipping host.\n")
        #       sys.stderr.flush()
        #       continue
        #     dimension["prom_metrics"]["sent"].inc(result["sent"])
        #     dimension["prom_metrics"]["received"].inc(result["received"])
        #     dimension["prom_metrics"]["rtt"].inc(result["rtt"])
        #     dimension["prom_metrics"]["min"].set(result["min"])
        #     dimension["prom_metrics"]["max"].set(result["max"])
        #     dimension["prom_metrics"]["mdev"].set(result["mdev"])

        prometheus_client.write_to_textfile(
            envs["PROMETHEUS_TEXTFILE_DIR"] + envs["PROMETHEUS_TEXTFILE_PREFIX"] + envs["MY_NODE_NAME"] + ".prom", registry)
