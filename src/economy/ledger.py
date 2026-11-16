import json
from pathlib import Path
from .models import LedgerEntry

class AppendOnlyLedger:
    """Local JSONL ledger for simulated accounting; not a financial account."""
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, entry: LedgerEntry) -> None:
        if not entry.simulated:
            raise ValueError("real-money entries are disabled in this prototype")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.__dict__, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict]:
        rows = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def balance_minor(self, currency: str = "USD") -> int:
        total = 0
        for row in self.entries():
            if row["currency"] != currency.upper():
                continue
            total += row["amount_minor"] if row["entry_type"] == "income" else -row["amount_minor"]
        return total
