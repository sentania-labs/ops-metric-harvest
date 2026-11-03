"""Deterministic Operations transport for live workflow tests and visual evidence."""
import re
from ops_metric_harvest.client import OpsClient, OpsClientError


class LiveClient(OpsClient):
    def __init__(self):
        super().__init__("ops.example.test")
        self.calls = []
        self.inventory = [self.resource(f"vm-{i:03}", f"production-{i:03}") for i in range(125)]
        self.inventory += [self.resource("duplicate-a", "duplicate"), self.resource("duplicate-b", "duplicate")]
        self.inventory += [self.resource("host-01", "compute-01", "HostSystem")]
        self.inventory += [self.resource("other-01", "production-000", adapter="OTHER")]
        self.property_error = None

    @staticmethod
    def resource(rid, name, kind="VirtualMachine", adapter="VMWARE"):
        return {"identifier": rid, "resourceKey": {"name": name, "adapterKindKey": adapter, "resourceKindKey": kind}}

    def _request(self, method, path, params=None, body=None):
        self.calls.append((method, path, params, body))
        self.api_call_count += 1
        params = params or {}
        if path == "/versions":
            return {"releaseVersion": "fixture"}
        if path == "/adapterkinds":
            return {"adapter-kind": [{"key": "VMWARE"}, {"key": "OTHER"}]}
        if path.endswith("/resourcekinds"):
            return {"resourceKind": [{"key": "VirtualMachine"}, {"key": "HostSystem"}]}
        if path.endswith("/statkeys"):
            return {"resourceTypeAttributes": [
                {"key": "cpu|usage", "name": "CPU usage", "unit": "%", "description": "Average CPU utilization"},
                {"key": "mem|usage", "name": "Memory usage", "unit": "%", "description": "Memory utilization"}]}
        if path.startswith("/adapterkinds") and path.endswith("/properties"):
            if self.property_error:
                raise OpsClientError(self.property_error)
            return {"resourceTypeAttributes": [
                {"key": "config|os", "name": "Operating system", "description": "Guest operating system", "dataType": "STRING"},
                {"key": "config|owner", "name": "Owner", "description": "Service owner", "dataType": "STRING"}]}
        if path.endswith("/properties"):
            return {"property": [{"name": "config|os", "value": "Linux"},
                                 {"name": "config|owner", "value": "Platform team"}]}
        if path == "/resources" or path.endswith("/relationships"):
            if path.endswith("/relationships"):
                rows = [self.inventory[-2]] if params["relationshipType"] == "PARENT" else self.inventory[:2]
            else:
                rows = [r for r in self.inventory if r["resourceKey"]["adapterKindKey"] == params["adapterKind"]
                        and r["resourceKey"]["resourceKindKey"] == params["resourceKind"]]
                if params.get("regex"):
                    rows = [r for r in rows if re.fullmatch(params["regex"], r["resourceKey"]["name"])]
                if params.get("resourceId"):
                    rows = [r for r in rows if r["identifier"] in params["resourceId"]]
            page, size = params["page"], params["pageSize"]
            return {"resourceList": rows[page * size:(page + 1) * size],
                    "pageInfo": {"page": page, "pageSize": size, "totalCount": len(rows)}}
        if path.startswith("/resources/stats"):
            return {"values": [{"resourceId": rid, "stat-list": {"stat": [
                {"statKey": {"key": key}, "timestamps": [1793635200000], "data": [23.5]}
                for key in params["statKey"] if not (rid == "vm-001" and key == "mem|usage")]}}
                for rid in params["resourceId"]]}
        raise AssertionError(f"Unexpected fixture request: {method} {path}")
