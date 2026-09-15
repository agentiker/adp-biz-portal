"""Fixed, fictional integration dataset. Never derived from user input."""

MOCK_RECORDS = (
    {
        "CustomerCode": "MOCK-ENT-A", "OrderNo": "MOCK-ORDER-A001",
        "BillNo": "MOCK-BL-A001", "ContainerNo": "MOCK-CONT-A001",
        "VesselVoyage": "模拟船 ALPHA / A001", "ETA": "2026-10-01T08:00:00+08:00",
        "CurrentMilestone": "模拟：已离港", "ATA": None,
    },
    {
        "CustomerCode": "MOCK-ENT-B", "OrderNo": "MOCK-ORDER-B001",
        "BillNo": "MOCK-BL-B001", "ContainerNo": "MOCK-CONT-B001",
        "VesselVoyage": "模拟船 BETA / B001", "ETA": None,
        "CurrentMilestone": None, "ATA": None,
    },
)
