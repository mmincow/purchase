from dataclasses import dataclass, field
from datetime import date


@dataclass
class OrderItem:
    item_name: str
    specification: str
    quantity: int
    unit: str
    unit_price: int
    supply_price: int = 0
    vat: int = 0
    total_price: int = 0

    def __post_init__(self):
        self.supply_price = self.quantity * self.unit_price
        self.vat = int(self.supply_price * 0.1)
        self.total_price = self.supply_price + self.vat


@dataclass
class PurchaseOrder:
    supplier: str
    delivery_date: date
    project_code: str
    account_code: str
    items: list[OrderItem] = field(default_factory=list)
    requester: str = ""
    department: str = ""
    note: str = ""
