# Private owner dashboard

The Worker serves a mobile-first operational dashboard at `/owner`. The page itself contains no owner data and may be loaded without a token; every data endpoint requires the existing owner bearer token (`AAE_QUEUE_TOKEN`).

## Access

1. Open the Worker URL followed by `/owner` on a phone or desktop browser.
2. Enter the existing owner bearer token in the password field and connect.
3. Use Refresh to reload the read-only overview, or Disconnect to clear the token from that browser tab.

The dashboard stores the token in `sessionStorage` for the current tab only. It is never placed in a URL, cookie, or persistent local storage. Do not share the token or use the dashboard on a shared device. The token currently authorizes other private Worker endpoints too; this dashboard does not introduce a narrower token scope.

## Read-only data

- Worker model identifier, UTC day, estimated daily AI neuron reservation and task counts.
- Aggregate agent revenue attribution from Cloudflare D1, distinguishing gross receipts awaiting reconciliation from net proceeds and agent credits that have been reconciled.
- The 25 most recent AI task identifiers, types, statuses and timestamps.

The dashboard exposes no payment, publishing, identity bootstrap, task approval, budget allocation, policy signing or transfer action. Its APIs use GET only.

## Important source-of-truth boundary

The Python financial autonomy subsystem stores its signed policies, double-entry journal, agent budget reservations and recurring expense schedules in local SQLite files. Those files are not synchronized to Cloudflare D1. The dashboard explicitly labels those controls as unavailable rather than presenting Cloudflare payment rows as the local simulated ledger. A later integration must define a secure, authenticated synchronization or shared-storage design before those controls can be displayed or operated remotely.

The Worker static dashboard shell is not itself sensitive. Data endpoints are protected by the existing bearer-token check. The route adds no public checkout or payout capability. No production deployment is included in this change.
