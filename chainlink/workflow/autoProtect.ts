import {
  cre,
  type Runtime,
  type EVMLog,
  getNetwork,
  bytesToHex,
  hexToBase64,
  TxStatus,
  ConsensusAggregationByFields,
  median,
  type HTTPSendRequester,
} from "@chainlink/cre-sdk";
import {
  decodeEventLog,
  parseAbi,
  encodeAbiParameters,
  parseAbiParameters,
  parseUnits,
} from "viem";
import type { Config } from "./config";
import { askGeminiRebalance } from "./gemini";

// CriticalRisk(bytes32 indexed agentId, uint16 currentLtvBps, uint16 maxLtvBps)
const CRITICAL_RISK_ABI = parseAbi([
  "event CriticalRisk(bytes32 indexed agentId, uint16 currentLtvBps, uint16 maxLtvBps)",
]);

// ABI encoding for BorrowBotExecutor._processReport
// (bytes32 agentId, uint8 actionType, uint256 amount, uint16 targetLtvBps, uint16 confidence)
const EXECUTOR_REPORT_PARAMS = parseAbiParameters(
  "bytes32, uint8, uint256, uint16, uint16"
);

interface PositionData {
  agentId: string;
  collateralValueUsd: number;
  borrowValueUsd: number;
  vaultBalanceUsd: number;
  currentLtvBps: number;
  targetLtvBps: number;
  maxLtvBps: number;
  yieldApyBps: number;
  borrowAprBps: number;
}

interface RebalanceResult {
  actionType: number;
  amountUsd: number;
  targetLtvBps: number;
  confidence: number;
  reasoning: string;
}

const fetchPositionData = (
  sendRequester: HTTPSendRequester,
  config: Config
): PositionData => {
  const resp = sendRequester
    .sendRequest({
      method: "GET",
      url: `${config.borrowbotApiUrl}/v1/cre/position-data`,
    })
    .result();

  if (resp.statusCode !== 200) {
    throw new Error(`BorrowBot API error: ${resp.statusCode}`);
  }

  return JSON.parse(Buffer.from(resp.body).toString("utf-8")) as PositionData;
};

export function onCriticalRiskTrigger(
  runtime: Runtime<Config>,
  log: EVMLog
): string {
  runtime.log("=== CRE Workflow: Auto-Protect — Critical Risk Detected ===");

  try {
    // Step 1: Decode the CriticalRisk event
    const topics = log.topics.map((t: Uint8Array) => bytesToHex(t)) as [
      `0x${string}`,
      ...`0x${string}`[]
    ];
    const data = bytesToHex(log.data);

    const decoded = decodeEventLog({
      abi: CRITICAL_RISK_ABI,
      data,
      topics,
    });

    const agentId = decoded.args.agentId as `0x${string}`;
    const currentLtvBps = decoded.args.currentLtvBps as number;
    const maxLtvBps = decoded.args.maxLtvBps as number;

    runtime.log(`[Step 1] Agent: ${agentId}`);
    runtime.log(`[Step 1] Current LTV: ${currentLtvBps}bps, Max: ${maxLtvBps}bps`);

    // Step 2: Fetch latest position data
    runtime.log("[Step 2] Fetching current position data...");
    const httpClient = new cre.capabilities.HTTPClient();

    const position = httpClient
      .sendRequest(
        runtime,
        fetchPositionData,
        ConsensusAggregationByFields<PositionData>({
          agentId: median,
          collateralValueUsd: median,
          borrowValueUsd: median,
          vaultBalanceUsd: median,
          currentLtvBps: median,
          targetLtvBps: median,
          maxLtvBps: median,
          yieldApyBps: median,
          borrowAprBps: median,
        })
      )(runtime.config)
      .result();

    runtime.log(
      `[Step 2] Position: collateral=$${position.collateralValueUsd}, borrow=$${position.borrowValueUsd}, vault=$${position.vaultBalanceUsd}`
    );

    // Step 3: Ask Gemini for rebalance strategy
    runtime.log("[Step 3] Querying Gemini for rebalance strategy...");

    const geminiInput = JSON.stringify({
      agentId,
      currentLtvBps: position.currentLtvBps,
      targetLtvBps: position.targetLtvBps,
      maxLtvBps: position.maxLtvBps,
      collateralValueUsd: position.collateralValueUsd,
      borrowValueUsd: position.borrowValueUsd,
      vaultBalanceUsd: position.vaultBalanceUsd,
      yieldApyBps: position.yieldApyBps,
      borrowAprBps: position.borrowAprBps,
      yieldSpreadBps: position.yieldApyBps - position.borrowAprBps,
      severity: "CRITICAL",
      liquidationProximityPct: ((currentLtvBps / maxLtvBps) * 100).toFixed(1),
    });

    const geminiResult = askGeminiRebalance(runtime, geminiInput);

    const jsonMatch = geminiResult.geminiResponse.match(
      /\{[\s\S]*"actionType"[\s\S]*"confidence"[\s\S]*\}/
    );
    if (!jsonMatch) {
      throw new Error(
        `Could not parse Gemini rebalance response: ${geminiResult.geminiResponse}`
      );
    }

    const rebalance = JSON.parse(jsonMatch[0]) as RebalanceResult;

    if (rebalance.actionType < 0 || rebalance.actionType > 3) {
      throw new Error(`Invalid action type: ${rebalance.actionType}`);
    }

    const actionLabels = ["REPAY", "BORROW", "PAUSE", "CLOSE"];
    runtime.log(
      `[Step 3] Strategy: ${actionLabels[rebalance.actionType]}, amount=$${rebalance.amountUsd}, target=${rebalance.targetLtvBps}bps`
    );
    runtime.log(`[Step 3] Confidence: ${rebalance.confidence / 100}%`);
    runtime.log(`[Step 3] Reasoning: ${rebalance.reasoning}`);

    // Step 4: Write rebalance command to BorrowBotExecutor
    runtime.log("[Step 4] Writing rebalance command on-chain...");
    const evmConfig = runtime.config.evms[0];

    const network = getNetwork({
      chainFamily: "evm",
      chainSelectorName: evmConfig.chainSelectorName,
      isTestnet: true,
    });
    if (!network) {
      throw new Error(`Network not found: ${evmConfig.chainSelectorName}`);
    }

    // Convert USD amount to USDC base units (6 decimals)
    const amountUsdc = parseUnits(rebalance.amountUsd.toString(), 6);

    const reportData = encodeAbiParameters(EXECUTOR_REPORT_PARAMS, [
      agentId,
      rebalance.actionType,
      amountUsdc,
      rebalance.targetLtvBps,
      rebalance.confidence,
    ]);

    const reportResponse = runtime
      .report({
        encodedPayload: hexToBase64(reportData),
        encoderName: "evm",
        signingAlgo: "ecdsa",
        hashingAlgo: "keccak256",
      })
      .result();

    const evmClient = new cre.capabilities.EVMClient(
      network.chainSelector.selector
    );

    const writeResult = evmClient
      .writeReport(runtime, {
        receiver: evmConfig.executorAddress,
        report: reportResponse,
        gasConfig: { gasLimit: evmConfig.gasLimit },
      })
      .result();

    if (writeResult.txStatus !== TxStatus.SUCCESS) {
      throw new Error(`Failed to write executor command: ${writeResult.txStatus}`);
    }

    const txHash = bytesToHex(writeResult.txHash || new Uint8Array(32));
    runtime.log(`[Step 4] Rebalance command written on-chain: ${txHash}`);
    runtime.log("=== Auto-Protect Complete ===");

    return txHash;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    runtime.log(`[ERROR] Auto-protect failed: ${msg}`);
    throw err;
  }
}
