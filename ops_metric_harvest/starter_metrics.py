"""Built-in starter metric sets and resource kinds."""

from typing import Dict, List

DEFAULT_RESOURCE_KINDS = [
    "VirtualMachine",
    "HostSystem",
    "ClusterComputeResource",
    "Datastore",
]

STARTER_METRIC_SETS: Dict[str, List[Dict[str, str]]] = {
    "HostSystem": [
        {"key": "cpu|capacity_usagepct_average", "name": "CPU Usage (%)", "unit": "%"},
        {"key": "cpu|coreUtilization_average", "name": "CPU Core Utilization (%)", "unit": "%"},
        {"key": "mem|active_average", "name": "Memory Active (KB)", "unit": "KB"},
        {"key": "mem|consumed_average", "name": "Memory Consumed (KB)", "unit": "KB"},
        {"key": "cpu|mhz_per_core", "name": "CPU MHz Per Core", "unit": "MHz"},
        {"key": "power|energy_summation_sum", "name": "Energy Summation (Joules)", "unit": "Joules"},
    ],
    "VirtualMachine": [
        {"key": "cpu|usage_average", "name": "CPU Usage (%)", "unit": "%"},
        {"key": "cpu|usagemhz_average", "name": "CPU Usage (MHz)", "unit": "MHz"},
        {"key": "cpu|readyPct", "name": "CPU Ready (%)", "unit": "%"},
        {"key": "mem|usage_average", "name": "Memory Usage (%)", "unit": "%"},
        {"key": "mem|consumed_average", "name": "Memory Consumed (KB)", "unit": "KB"},
        {"key": "mem|active_average", "name": "Memory Active (KB)", "unit": "KB"},
        {"key": "net:aggregate of all instances|usage_average", "name": "Network Usage (KBps)", "unit": "KBps"},
        {"key": "disk:aggregate of all instances|totalLatency_average", "name": "Disk Total Latency (ms)", "unit": "ms"},
    ],
    "ClusterComputeResource": [
        {"key": "cpu|usage_average", "name": "Cluster CPU Usage (%)", "unit": "%"},
        {"key": "mem|usage_average", "name": "Cluster Memory Usage (%)", "unit": "%"},
        {"key": "cpu|totalCapacity_average", "name": "Total CPU Capacity (MHz)", "unit": "MHz"},
        {"key": "mem|totalCapacity_average", "name": "Total Memory Capacity (KB)", "unit": "KB"},
    ],
    "Datastore": [
        {"key": "diskspace|total_usage", "name": "Disk Space Total Usage (GB)", "unit": "GB"},
        {"key": "diskspace|total_capacity", "name": "Disk Space Total Capacity (GB)", "unit": "GB"},
        {"key": "diskspace|capacity_usagepct", "name": "Disk Space Usage (%)", "unit": "%"},
        {"key": "disk|totalLatency_average", "name": "Datastore Total Latency (ms)", "unit": "ms"},
    ],
}
