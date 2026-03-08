import { cre, Runner, getNetwork } from "@chainlink/cre-sdk";
import { keccak256, toHex } from "viem";
import { configSchema, type Config } from "./config";
import { onCronTrigger } from "./riskAssessment";
import { onCriticalRiskTrigger } from "./autoProtect";

// CriticalRisk(bytes32 indexed agentId, uint16 currentLtvBps, uint16 maxLtvBps)
const CRITICAL_RISK_SIGNATURE = "CriticalRisk(bytes32,uint16,uint16)";

const initWorkflow = (config: Config) => {
  // Handler 1: Cron-based risk assessment (every 5 minutes)
  const cronCapability = new cre.capabilities.CronCapability();

  // Handler 2: Event-driven auto-protection on CriticalRisk
  const evmConfig = config.evms[0];
  const network = getNetwork({
    chainFamily: "evm",
    chainSelectorName: evmConfig.chainSelectorName,
    isTestnet: true,
  });

  if (!network) {
    throw new Error(`Network not found: ${evmConfig.chainSelectorName}`);
  }

  const evmClient = new cre.capabilities.EVMClient(
    network.chainSelector.selector
  );
  const criticalRiskEventHash = keccak256(toHex(CRITICAL_RISK_SIGNATURE));

  return [
    // Handler 1: Periodic risk assessment
    cre.handler(
      cronCapability.trigger({ schedule: config.schedule }),
      onCronTrigger
    ),

    // Handler 2: Auto-protect on CriticalRisk event from RiskOracle
    cre.handler(
      evmClient.logTrigger({
        addresses: [evmConfig.riskOracleAddress],
        topics: [{ values: [criticalRiskEventHash] }],
        confidence: "CONFIDENCE_LEVEL_FINALIZED",
      }),
      onCriticalRiskTrigger
    ),
  ];
};

export async function main() {
  const runner = await Runner.newRunner({ configSchema });
  await runner.run(initWorkflow);
}

main();
