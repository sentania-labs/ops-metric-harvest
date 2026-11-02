"""Mocked inventory responses for testing."""

HOSTS_INVENTORY_PAGE_0 = {
    "pageInfo": {"totalCount": 4, "page": 0, "pageSize": 2},
    "resourceList": [
        {
            "identifier": "host-001-uuid",
            "resourceKey": {
                "name": "esx-prod-01.int.sentania.net",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "HostSystem",
            },
        },
        {
            "identifier": "host-002-uuid",
            "resourceKey": {
                "name": "esx-prod-02.int.sentania.net",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "HostSystem",
            },
        },
    ],
}

HOSTS_INVENTORY_PAGE_1 = {
    "pageInfo": {"totalCount": 4, "page": 1, "pageSize": 2},
    "resourceList": [
        {
            "identifier": "host-003-uuid",
            "resourceKey": {
                "name": "esx-prod-03.int.sentania.net",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "HostSystem",
            },
        },
        {
            "identifier": "host-004-uuid",
            "resourceKey": {
                "name": "esx-prod-04.int.sentania.net",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "HostSystem",
            },
        },
    ],
}

VMS_INVENTORY = {
    "pageInfo": {"totalCount": 5, "page": 0, "pageSize": 10},
    "resourceList": [
        {
            "identifier": "vm-001-uuid",
            "resourceKey": {
                "name": "app-vm-01",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
        {
            "identifier": "vm-002-uuid",
            "resourceKey": {
                "name": "app-vm-02",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
        {
            "identifier": "vm-003-uuid",
            "resourceKey": {
                "name": "shared-db-vm-03",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
        {
            "identifier": "vm-004-uuid",
            "resourceKey": {
                "name": "storage-vm-04",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
        {
            "identifier": "vm-005-uuid",
            "resourceKey": {
                "name": "storage-vm-05",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
        {
            "identifier": "vm-uneven-01",
            "resourceKey": {
                "name": "vm-uneven-01",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
    ],
}

DUPLICATE_NAME_INVENTORY = {
    "pageInfo": {"totalCount": 2, "page": 0, "pageSize": 10},
    "resourceList": [
        {
            "identifier": "vm-dup-1",
            "resourceKey": {
                "name": "duplicate-vm",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
        {
            "identifier": "vm-dup-2",
            "resourceKey": {
                "name": "duplicate-vm",
                "adapterKindKey": "VMWARE",
                "resourceKindKey": "VirtualMachine",
            },
        },
    ],
}
