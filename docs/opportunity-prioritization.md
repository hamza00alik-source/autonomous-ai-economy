# Opportunity prioritization

The `economy prioritize-opportunities` command compares research dossiers using an explicit owner-supplied operational assessment. It is a relative operational-fit aid, not a demand, sales, profit, legal-compliance, or commercial-approval prediction.

## Input format

Provide a JSON array. Each entry contains a previously generated dossier and a separate assessment:

```json
[
  {
    "dossier": {
      "opportunity": { "title": "Example downloadable product" },
      "validation": {
        "status": "needs_research",
        "blockers": ["Independent buyer evidence is missing"]
      }
    },
    "assessment": {
      "currency": "USD",
      "startup_cost_minor": 0,
      "ongoing_cost_minor": 0,
      "hours_to_first_delivery": 4,
      "delivery_complexity": 1,
      "fulfillment_burden": 1,
      "legal_policy_status": "review_needed"
    }
  }
]
```

The dossier can be the full output of `economy source-dossier`; the abbreviated example above only shows the fields consumed by the report. Costs are integer minor currency units (for USD, cents). Startup cost must be explicitly supplied. Ongoing cost, delivery time, complexity and fulfillment burden may be omitted or set to `null`; they remain unknown and are not silently treated as zero.

Complexity and fulfillment burden use owner estimates from 1 (low) to 5 (high). Legal/policy status is an owner workflow label, not a legal conclusion:
- `not_assessed`
- `review_needed`
- `owner_reviewed_no_blocker`
- `concern_identified`

Cost and time comparisons are made only within the same currency. The score is calculated from available dimensions and the report separately exposes assessment completeness and missing fields. Scores are not comparable across separate runs or different input sets.

## Run

```bash
economy prioritize-opportunities opportunity_assessments.json
```

The command only reads local JSON and prints a report. It does not browse, contact buyers, publish listings, spend money, commit to customers, or move funds. All results keep `can_publish`, `can_spend`, `sales_verified`, and `profitability_verified` false. A high score does not override evidence blockers or owner approval.
