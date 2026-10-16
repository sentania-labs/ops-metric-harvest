"""Mocked metric catalogue responses for testing."""

HOST_STAT_KEYS_CATALOGUE = {
    "resourceTypeAttributes": [
        {
            "key": "cpu|capacity_usagepct_average",
            "name": "CPU Usage (%)",
            "unit": "%",
            "description": "Average CPU usage percentage",
        },
        {
            "key": "cpu|coreUtilization_average",
            "name": "CPU Core Utilization (%)",
            "unit": "%",
            "description": "CPU Core Utilization percentage",
        },
        {
            "key": "mem|active_average",
            "name": "Memory Active (KB)",
            "unit": "KB",
            "description": "Average active memory",
        },
    ]
}

VM_STAT_KEYS_CATALOGUE = {
    "resourceTypeAttributes": [
        {"key": "cpu|usage_average", "name": "CPU Usage (%)", "unit": "%", "description": "CPU Usage"},
        {"key": "mem|usage_average", "name": "Memory Usage (%)", "unit": "%", "description": "Memory Usage"},
        {"key": "cpu|readyPct", "name": "CPU Ready (%)", "unit": "%", "description": "CPU Ready percentage"},
        {"key": "net:aggregate of all instances|usage_average", "name": "Network Usage (KBps)", "unit": "KBps", "description": "Net usage"},
        {"key": "disk:aggregate of all instances|totalLatency_average", "name": "Disk Latency (ms)", "unit": "ms", "description": "Disk latency"},
        {"key": "mem|consumed_average", "name": "Memory Consumed (KB)", "unit": "KB", "description": "Memory consumed"},
    ]
}
