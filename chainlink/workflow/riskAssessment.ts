import {
  cre,
  ok,
  type Runtime,
  type CronPayload,
  type HTTPSendRequester,
  ConsensusAggregationByFields,
  median,
  bytesToHex,
  hexToBase64,
  TxStatus,
  getNetwork,
} from "@chainlink/cre-sdk";
import { encodeAbiParameters, parseAbiParameters, keccak256, toHex } from "viem";
import type { Config } from "./config";
import { askGeminiRisk } from "./gemini";

// ABI encoding for the BorrowBotRiskOracle._processReport
// (bytes32 agentId, uint8 riskLevel, uint16 currentLtvBps, uint16 targetLtvBps,
//  uint16 maxLtvBps, int16 yieldSpreadBps, uint16 confidence, bytes32 actionHash)
const RISK_REPORT_PARAMS = parseAbiParameters(
  "bytes32, uint8, uint16, uint16, uint16, int16, uint16, bytes32"
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

interface PriceData {
  ethUsd: number;
  btcUsd: number;
  ethChange1h: number;
  ethChange24h: number;
  btcChange1h: number;
  btcChange24h: number;
}

interface RiskResult {
  riskLevel: number;
  confidence: number;
  action: string;
  repayAmountBps: number;
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

  const body = Buffer.from(resp.body).toString("utf-8");
  return JSON.parse(body) as PositionData;
};

const fetchPriceData = (
  sendRequester: HTTPSendRequester,
  config: Config
): PriceData => {
  const resp = sendRequester
    .sendRequest({
      method: "GET",
      url: `${config.priceApiUrl}?ids=ethereum,bitcoin&vs_currencies=usd&include_1hr_change=true&include_24hr_change=true`,
    })
    .result();

  if (resp.statusCode !== 200) {
    throw new Error(`Price API error: ${resp.statusCode}`);
  }

  const body = Buffer.from(resp.body).toString("utf-8");
  const data = JSON.parse(body) as Record<string, Record<string, number>>;

  return {
    ethUsd: data.ethereum?.usd ?? 0,
    btcUsd: data.bitcoin?.usd ?? 0,
    ethChange1h: data.ethereum?.usd_1h_change ?? 0,
    ethChange24h: data.ethereum?.usd_24h_change ?? 0,
    btcChange1h: data.bitcoin?.usd_1h_change ?? 0,
    btcChange24h: data.bitcoin?.usd_24h_change ?? 0,
  };
};

export function onCronTrigger(
  runtime: Runtime<Config>,
  payload: CronPayload
): string {
  if (!payload.scheduledExecutionTime) {
    throw new Error("Scheduled execution time is required");
  }

  runtime.log("=== CRE Workflow: BorrowBot Risk Assessment ===");
  runtime.log(`Triggered at: ${payload.scheduledExecutionTime}`);

  // Step 1: Fetch position data from BorrowBot API (consensus-verified)
  runtime.log("[Step 1] Fetching position data from BorrowBot API...");
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
    `[Step 1] Position: LTV=${position.currentLtvBps}bps, collateral=$${position.collateralValueUsd}, borrow=$${position.borrowValueUsd}`
  );

  // Step 2: Fetch consensus-verified prices
  runtime.log("[Step 2] Fetching market prices...");
  const prices = httpClient
    .sendRequest(
      runtime,
      fetchPriceData,
      ConsensusAggregationByFields<PriceData>({
        ethUsd: median,
        btcUsd: median,
        ethChange1h: median,
        ethChange24h: median,
        btcChange1h: median,
        btcChange24h: median,
      })
    )(runtime.config)
    .result();

  runtime.log(
    `[Step 2] Prices: ETH=$${prices.ethUsd} (1h: ${prices.ethChange1h}%, 24h: ${prices.ethChange24h}%), BTC=$${prices.btcUsd}`
  );

  // Step 3: Ask Gemini for risk assessment
  runtime.log("[Step 3] Querying Gemini AI for risk assessment...");
  const yieldSpreadBps = position.yieldApyBps - position.borrowAprBps;

  const geminiInput = JSON.stringify({
    currentLtvBps: position.currentLtvBps,
    targetLtvBps: position.targetLtvBps,
    maxLtvBps: position.maxLtvBps,
    yieldSpreadBps,
    collateralPriceUsd: prices.ethUsd,
    priceChange1h: prices.ethChange1h,
    priceChange24h: prices.ethChange24h,
    collateralValueUsd: position.collateralValueUsd,
    borrowValueUsd: position.borrowValueUsd,
    vaultBalanceUsd: position.vaultBalanceUsd,
  });

  const geminiResult = askGeminiRisk(runtime, geminiInput);

  // Parse Gemini response
  const jsonMatch = geminiResult.geminiResponse.match(
    /\{[\s\S]*"riskLevel"[\s\S]*"confidence"[\s\S]*\}/
  );
  if (!jsonMatch) {
    throw new Error(
      `Could not parse Gemini response: ${geminiResult.geminiResponse}`
    );
  }
  const risk = JSON.parse(jsonMatch[0]) as RiskResult;

  if (risk.riskLevel < 0 || risk.riskLevel > 3) {
    throw new Error(`Invalid risk level: ${risk.riskLevel}`);
  }
  if (risk.confidence < 0 || risk.confidence > 10000) {
    throw new Error(`Invalid confidence: ${risk.confidence}`);
  }

  const riskLabels = ["SAFE", "WARNING", "DANGER", "CRITICAL"];
  runtime.log(
    `[Step 3] Risk: ${riskLabels[risk.riskLevel]} (confidence: ${risk.confidence / 100}%), action: ${risk.action}`
  );
  runtime.log(`[Step 3] Reasoning: ${risk.reasoning}`);

  // Step 4: Write risk assessment to BorrowBotRiskOracle on-chain
  runtime.log("[Step 4] Writing risk assessment to on-chain oracle...");
  const evmConfig = runtime.config.evms[0];

  const network = getNetwork({
    chainFamily: "evm",
    chainSelectorName: evmConfig.chainSelectorName,
    isTestnet: true,
  });
  if (!network) {
    throw new Error(`Network not found: ${evmConfig.chainSelectorName}`);
  }

  const agentIdBytes = keccak256(toHex(position.agentId));
  const actionHash = keccak256(toHex(risk.action));

  const reportData = encodeAbiParameters(RISK_REPORT_PARAMS, [
    agentIdBytes,
    risk.riskLevel,
    position.currentLtvBps,
    position.targetLtvBps,
    position.maxLtvBps,
    yieldSpreadBps,
    risk.confidence,
    actionHash,
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
      receiver: evmConfig.riskOracleAddress,
      report: reportResponse,
      gasConfig: { gasLimit: evmConfig.gasLimit },
    })
    .result();

  if (writeResult.txStatus !== TxStatus.SUCCESS) {
    throw new Error(
      `Failed to write risk report: ${writeResult.txStatus}`
    );
  }

  const txHash = bytesToHex(writeResult.txHash || new Uint8Array(32));
  runtime.log(`[Step 4] Risk assessment written on-chain: ${txHash}`);
  runtime.log("=== Risk Assessment Complete ===");

  return txHash;
}
