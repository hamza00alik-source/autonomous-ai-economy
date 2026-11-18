# make.fun public bounty discovery

Added as a **read-only discovery adapter**. It reads the public
`GET https://make.fun/api/competitions?status=open` endpoint without an
account, API key, Solana keypair, or wallet.

## Safety boundary

- This adapter only discovers public open competitions.
- It does not register, authenticate, claim, enter, upload code, submit a
  repository, attach transcripts, sign messages, claim rewards, or transfer
  funds.
- `payment_verified` and `entry_allowed` are always false. A listing is not
  proof that an entry will be accepted or paid.
- A bounty's published metric, eligibility, deadline, paid places, entry fee,
  escrow, session-transcript requirements, licensing, and sanctions checks
  must be inspected from its official detail page before any participation.
- The platform requires a Solana keypair/API key to enter and claim rewards.
  Do not generate or connect a wallet automatically. Any such step requires
  explicit operator approval and a separate security/cost review.

Official references:
- https://make.fun/guide/ai-agent-bounties
- https://make.fun/guide/how-ai-agents-earn-money
- https://make.fun/terms
- https://make.fun/payouts

## Evidence limitations

The public API response may evolve. Unknown fields remain unknown; the adapter
never infers a verified escrow from an advertised reward. This integration
does not claim that a current competition exists, that the user is eligible,
or that the system can win.
