"""Mocked stats responses for testing historical collection and alignment."""

# Aligned stats response for 4 hosts over 3 timestamps
def create_mock_hosts_stats(resource_ids, stat_keys):
    timestamps = [1728000000000, 1728000300000, 1728000600000]
    values = []
    for rid in resource_ids:
        stat_entries = []
        for idx, sk in enumerate(stat_keys):
            # Deterministic distinct data values
            data = [round(float((idx + 1) * 10 + t_idx * 2.5), 2) for t_idx in range(len(timestamps))]
            stat_entries.append({
                "statKey": {"key": sk},
                "timestamps": timestamps,
                "data": data,
            })
        values.append({
            "resourceId": rid,
            "stat-list": {"stat": stat_entries},
        })
    return {"values": values}


# Uneven, misaligned timestamps for testing timestamp union and null alignment (AC7)
MOCK_MISALIGNED_STATS = {
    "values": [
        {
            "resourceId": "vm-uneven-01",
            "stat-list": {
                "stat": [
                    {
                        "statKey": {"key": "metric_a"},
                        "timestamps": [1728000000000, 1728000300000, 1728000600000],
                        "data": [10.5, 20.5, 30.5],
                    },
                    {
                        "statKey": {"key": "metric_b"},
                        # Starts later and has a later sample
                        "timestamps": [1728000300000, 1728000600000, 1728000900000],
                        "data": [200.0, 300.0, 400.0],
                    },
                ]
            },
        }
    ]
}
