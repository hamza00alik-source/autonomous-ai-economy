import argparse
from pathlib import Path
from .agents import AgentRegistry, RuleBasedAgent
from .controller import EconomyController
from .ledger import AppendOnlyLedger
from .models import LedgerEntry

def demo(data_dir: Path) -> None:
    registry = AgentRegistry()
    registry.register(RuleBasedAgent("opportunity-researcher", "opportunity research"))
    registry.register(RuleBasedAgent("verification-auditor", "verification"))
    controller = EconomyController(registry)
    task = controller.submit("First opportunity scan", "Identify one low-cost digital product idea and define evidence needed to validate demand.", "opportunity-researcher")
    result = controller.execute(task.task_id)
    ledger = AppendOnlyLedger(data_dir / "ledger.jsonl")
    ledger.append(LedgerEntry.create("income", 100, "USD", "Demo-only simulated revenue entry", result.task_id))
    print("DEMO ONLY — no external research, customer, payment, or real revenue was generated.")
    print(f"Task: {result.status.value} | {result.task_id}")
    print(result.result)
    print(f"Simulated ledger balance: ${ledger.balance_minor() / 100:.2f}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous AI Economy prototype")
    sub = parser.add_subparsers(dest="command", required=True)
    demo_parser = sub.add_parser("demo", help="run a safe local simulation")
    demo_parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    args = parser.parse_args()
    if args.command == "demo":
        demo(args.data_dir)

if __name__ == "__main__":
    main()
