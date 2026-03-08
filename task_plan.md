# Task Plan: Chainlink CRE Integration — End-to-End Production Build

## Goal
Build a production-grade CRE workflow ("AI Risk Oracle") that monitors BorrowBot positions, uses Gemini LLM for risk assessment with consensus-verified price data, and publishes risk assessments on-chain via a Receiver contract on Sepolia. Includes auto-protection via log trigger.

## Phases

- [x] Phase 1: Scaffold CRE project structure
- [x] Phase 2: Solidity contracts (10/10 tests passing)
- [x] Phase 3: CRE Workflow — Handler 1 (Cron Risk Assessment)
- [x] Phase 4: CRE Workflow — Handler 2 (Log Trigger Auto-Protect)
- [x] Phase 5: Public API endpoint for CRE
- [x] Phase 6: Simulation & testing
  - Workflow compiles to WASM successfully
  - 10/10 Forge tests passing
  - Needs `GEMINI_API_KEY_VALUE` env var for full simulation
  - Contracts not yet deployed to Sepolia (needs funded wallet)
- [x] Phase 7: Documentation

## Key Decisions
- Deploy contracts on Sepolia (CRE simulation chain)
- Use BorrowBot's live API as the external data source (HTTP fetch from CRE)
- Forwarder address on Sepolia: 0x15fc6ae953e024d975e77382eeec56a9101f9f88
- Follow ReceiverTemplate pattern from CRE bootcamp/templates
- TypeScript workflow (not Go)

## Errors Encountered
- Hex literal `0xF0RWARD` invalid in Solidity — fixed to `0xF00F00`
- `forge install` needs `--no-git` flag when not in standalone git repo

## Status
**All phases complete.** Remaining: deploy contracts to Sepolia (needs funded wallet + `DEPLOYER_PRIVATE_KEY`), set `GEMINI_API_KEY_VALUE` env var for full simulation.
