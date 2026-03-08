# BorrowBot x Chainlink CRE Integration — Brainstorm Report

**Date**: 2026-03-07
**Category**: DeFi & Tokenization
**Hackathon Requirement**: CRE workflow integrating blockchain + external API/LLM/AI agent

---

## Problem Statement

BorrowBot is a production autonomous DeFi lending agent on Base. It needs a Chainlink CRE workflow that genuinely adds value to the existing system — not a bolted-on integration. The CRE workflow must integrate at least one blockchain with an external API/LLM/AI agent, and demonstrate simulation via CLI or live deployment.

---

## Hackathon Requirements Checklist

- [x] CRE workflow as orchestration layer
- [ ] Integrate blockchain + external API/LLM/AI agent
- [ ] Successful simulation (CRE CLI) or live deployment
- [ ] 3-5 min video showing workflow execution
- [ ] Public repo + README linking Chainlink files

---

## Approach Evaluation

### Approach A: "AI-Powered LTV Guardian" (CRE replaces Python worker)

**Concept**: CRE workflow runs on a cron schedule (every 5 min), reads on-chain position data from Morpho Blue, fetches external market data, asks Gemini LLM whether to rebalance, and writes the rebalance action on-chain — all with decentralized consensus.

**CRE Workflow**:
```
Cron Trigger (every 5 min)
  → EVM Read: Morpho position (collateral, borrow amounts) on Base
  → EVM Read: Vault balance (40acres ERC-4626) on Base
  → EVM Read: ENS constitution records on mainnet (max-ltv, min-spread, pause)
  → HTTP Fetch: Price data from Alchemy/CoinGecko (consensus-verified)
  → HTTP Fetch: Gemini LLM — "Given position X, constitution Y, prices Z: should agent rebalance? What action?" → returns {action: "repay"|"borrow"|"none", amount: bigint}
  → EVM Write: Execute rebalance on Base (via receiver contract that calls Morpho)
  → EVM Write: Update ENS status records on mainnet
```

**Pros**:
- Decentralized consensus on price data + LLM decision = trustless autonomous agent
- Replaces centralized Python worker with verifiable, tamper-proof CRE execution
- Multi-chain reads (Base + Ethereum mainnet for ENS) in single workflow
- LLM integration via Gemini (matches bootcamp pattern exactly)
- Aligns perfectly with "DeFi & Tokenization" track
- Strongest narrative: "autonomous DeFi agent governed by ENS, executed by Chainlink"

**Cons**:
- Complex: multi-chain reads + HTTP + LLM + chain writes in one workflow
- EVM Write to Morpho needs a receiver contract (CRE writes via `writeReport`)
- May need to simplify — CRE can't directly call arbitrary contracts, needs a `Receiver` contract pattern
- ENS writes on mainnet require gas (separate from Base execution)

**Effort**: HIGH (3-5 days) — new Solidity receiver contract + full CRE workflow + simulation

---

### Approach B: "Decentralized Position Health Oracle" (CRE as data feed)

**Concept**: CRE workflow acts as a decentralized oracle that monitors position health and publishes verified data on-chain. Simpler scope — reads position data, computes health metrics, pushes to a custom data feed contract.

**CRE Workflow**:
```
Cron Trigger (every 10 min)
  → EVM Read: Morpho position data on Base
  → EVM Read: Vault balance on Base
  → HTTP Fetch: ETH/BTC price from external API (consensus-verified)
  → Compute: LTV, health factor, yield spread
  → EVM Write: Publish health metrics to a PositionHealthFeed contract on Base
```

**Pros**:
- Follows custom-data-feed template closely — proven pattern
- Simpler than Approach A (no LLM, no multi-chain)
- Clean separation: CRE publishes data, Python worker reads and acts
- Decentralized price verification genuinely valuable for DeFi

**Cons**:
- Less impressive — just a data feed, not an autonomous agent
- Doesn't leverage LLM integration (misses the AI angle)
- Python worker still does all the interesting work
- Feels like CRE is an afterthought, not central

**Effort**: MEDIUM (2-3 days) — receiver contract + CRE workflow

---

### Approach C: "AI Risk Advisor + Auto-Liquidation Protector" (RECOMMENDED)

**Concept**: CRE workflow combines AI-driven risk assessment with automated protection. Two handlers:

1. **Cron Handler** (every 5 min): Reads position data, fetches prices, asks Gemini to assess risk level ("safe/warning/danger/critical" + reasoning), publishes risk assessment on-chain.

2. **Log Trigger Handler**: When the risk assessment contract emits `CriticalRisk(agentId)`, a second handler fires that reads the ENS constitution, asks Gemini for the optimal rebalance strategy given current conditions, and executes the rebalance on-chain.

**CRE Workflow**:
```
Handler 1: Cron Trigger (every 5 min)
  → EVM Read: Morpho position (collateral USD, borrow USD) on Base
  → EVM Read: Vault shares + conversion rate on Base
  → HTTP Fetch: Price data (ETH, BTC) from CoinGecko — consensus verified
  → HTTP Fetch: Gemini LLM — risk assessment prompt with position data
    → Returns: {riskLevel: "safe"|"warning"|"critical", ltv: number, action: string, reasoning: string}
  → EVM Write: Publish risk assessment to BorrowBotRiskOracle contract on Base
    → If riskLevel == "critical", contract emits CriticalRisk event

Handler 2: Log Trigger (CriticalRisk event)
  → EVM Read: ENS constitution on mainnet (max-ltv, pause flag)
  → EVM Read: Current Morpho position on Base
  → HTTP Fetch: Gemini LLM — rebalance strategy prompt
    → Returns: {action: "repay", amount: bigint, reason: string}
  → EVM Write: Execute rebalance via BorrowBotExecutor receiver contract on Base
```

**Pros**:
- **Two handlers** = demonstrates CRE capabilities thoroughly (cron + log trigger)
- **Multi-chain reads** = Base (DeFi) + Ethereum mainnet (ENS constitution)
- **LLM integration** = Gemini for risk assessment + rebalance strategy
- **Consensus-verified prices** = genuinely improves security vs single RPC
- **Event-driven architecture** = CRE's strong suit (log trigger → automated action)
- **Clean narrative**: "AI assesses risk every 5 min with decentralized consensus. When danger strikes, CRE automatically protects the position — no centralized server required."
- **Directly maps to bootcamp structure** (HTTP trigger → log trigger, just like prediction market)
- **Existing BorrowBot worker becomes optional** — CRE can fully replace it for monitoring

**Cons**:
- Still needs 2 Solidity contracts (RiskOracle + Executor)
- Multi-chain in single workflow may have simulation complexity
- CRE's `writeReport` pattern requires Receiver interface on contracts

**Effort**: HIGH (3-5 days) but modular — can demo Handler 1 alone if time is short

---

## RECOMMENDED: Approach C — "AI Risk Advisor + Auto-Liquidation Protector"

### Why This Wins

1. **Genuine value-add**: Decentralized consensus on price data + LLM reasoning removes single points of failure from BorrowBot's risk engine
2. **Two CRE handlers**: Demonstrates both cron and event-driven patterns
3. **Multi-chain**: Reads ENS constitution from mainnet, reads/writes DeFi position on Base
4. **AI integration**: Gemini LLM for risk assessment (matches bootcamp exactly)
5. **Strong DeFi narrative**: "Autonomous agent protected by decentralized oracle network"
6. **Builds on existing architecture**: ENS constitution is already production — CRE now reads it as part of the decentralized decision loop

### Simplification Option (if time is tight)

Drop Handler 2 (log trigger). Just do Handler 1 (cron → read position → fetch prices → ask Gemini → publish risk on-chain). This alone satisfies all hackathon requirements and can be simulated via CLI in isolation.

---

## Implementation Plan

### New Components Needed

#### 1. Solidity Contracts (Foundry)

**`BorrowBotRiskOracle.sol`** — Receives CRE risk assessments
```
- Implements IReceiver (CRE pattern)
- Stores latest risk assessment per agent
- Emits CriticalRisk(bytes32 agentId) when riskLevel == CRITICAL
- Public view: getRiskAssessment(agentId) → (riskLevel, ltv, timestamp, reasoning)
```

**`BorrowBotExecutor.sol`** — Receives CRE rebalance commands (Handler 2)
```
- Implements IReceiver
- Whitelisted to call Morpho Blue on behalf of agent wallet
- Executes: withdraw from vault → repay on Morpho
- Only callable via CRE writeReport (verified DON signatures)
```

#### 2. CRE Workflow (TypeScript)

```
chainlink/
├── workflow/
│   ├── main.ts              # Runner + initWorkflow (cron + log handlers)
│   ├── riskAssessment.ts     # Handler 1: cron → read → price → Gemini → write
│   ├── autoProtect.ts        # Handler 2: log → ENS read → Gemini → execute
│   ├── gemini.ts             # Gemini LLM helper (adapted from bootcamp)
│   ├── workflow.yaml         # CRE workflow settings
│   ├── config.staging.json   # Sepolia config
│   ├── config.production.json # Base config
│   └── package.json
├── contracts/
│   ├── src/
│   │   ├── BorrowBotRiskOracle.sol
│   │   └── BorrowBotExecutor.sol
│   ├── abi/                  # Generated TypeScript ABI bindings
│   └── foundry.toml
└── README.md                 # Links to all Chainlink files
```

#### 3. Integration Points with Existing BorrowBot

- Python worker reads `BorrowBotRiskOracle` on-chain for latest risk assessment
- Frontend displays CRE-verified risk level on dashboard
- ENS constitution records consumed by CRE workflow (read-only)
- Telegram notifications triggered by on-chain events from CRE

### Phases

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Scaffold CRE project (from custom-data-feed template) | 2h |
| 2 | Write `BorrowBotRiskOracle.sol` with IReceiver | 3h |
| 3 | Implement Handler 1: cron → Morpho read → price fetch → Gemini → write | 4h |
| 4 | Deploy contract to Sepolia, simulate Handler 1 via CRE CLI | 2h |
| 5 | Write `BorrowBotExecutor.sol` with IReceiver | 3h |
| 6 | Implement Handler 2: log trigger → ENS read → Gemini → execute | 4h |
| 7 | End-to-end simulation of both handlers | 2h |
| 8 | Integrate frontend (show CRE risk on dashboard) | 2h |
| 9 | Record 3-5 min demo video | 2h |
| 10 | README + documentation | 1h |
| **Total** | | **~25h** |

### Minimum Viable Submission (if time-constrained)

Phases 1-4 + 9-10 = **~11h**. Just Handler 1 (cron-based risk assessment) with simulation demo. Still satisfies all hackathon requirements.

---

## Technical Risks

| Risk | Mitigation |
|------|-----------|
| CRE can't read Base chain (only testnets?) | Use Sepolia for demo; check supported networks list |
| Morpho not on Sepolia | Deploy mock Morpho-like contract on Sepolia for simulation |
| ENS mainnet reads from CRE | May need to mock or use Sepolia ENS; check CRE multi-chain support |
| `writeReport` receiver pattern unfamiliar | Follow custom-data-feed template's `ReserveManager` pattern exactly |
| Gemini consensus may differ across nodes | Use `consensusIdenticalAggregation` with structured JSON output (bootcamp pattern) |
| CRE Early Access for deployment | Simulation via CLI is explicitly accepted per hackathon rules |

---

## Key Question to Resolve Before Starting

**Chain support**: CRE may only support testnets (Sepolia) for simulation. This means:
- Option A: Deploy mock contracts on Sepolia that mirror Morpho position data → simulate there
- Option B: Use CRE's HTTP capability to read Base via RPC (not chain read, but HTTP fetch to a Base RPC endpoint) → works on any chain but loses typed contract bindings

**Recommendation**: Start with Sepolia + mock contracts. This is the standard hackathon pattern and avoids chain-support blockers.

---

## Success Metrics

1. `cre workflow simulate` runs successfully end-to-end
2. Handler 1 reads position data, fetches prices, gets Gemini assessment, writes to contract
3. Handler 2 fires on CriticalRisk event and executes rebalance
4. Demo video clearly shows workflow execution and on-chain state changes
5. README documents all Chainlink integration points

---

## Next Steps

1. Confirm CRE supported chains (does it support Base? or Sepolia only?)
2. Scaffold project from `custom-data-feed` template
3. Design and deploy `BorrowBotRiskOracle` on Sepolia
4. Implement Handler 1 and verify simulation
5. If time permits, implement Handler 2 with log trigger
