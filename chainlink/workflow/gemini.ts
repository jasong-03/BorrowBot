import {
  cre,
  ok,
  consensusIdenticalAggregation,
  type Runtime,
  type HTTPSendRequester,
} from "@chainlink/cre-sdk";
import type { Config } from "./config";

interface GeminiData {
  system_instruction: { parts: Array<{ text: string }> };
  contents: Array<{ parts: Array<{ text: string }> }>;
}

interface GeminiApiResponse {
  candidates?: Array<{
    content?: { parts?: Array<{ text?: string }> };
  }>;
  responseId?: string;
}

export interface GeminiResponse {
  statusCode: number;
  geminiResponse: string;
  responseId: string;
}

const RISK_SYSTEM_PROMPT = `
You are a DeFi risk assessment engine for an autonomous lending agent (BorrowBot).
BorrowBot borrows USDC against crypto collateral (WETH/cbBTC) via Morpho Blue and deposits into yield vaults.

Your task: Given position data and market prices, assess the risk level of the position.

INPUTS you will receive:
- currentLtvBps: current loan-to-value ratio in basis points (7500 = 75%)
- targetLtvBps: the agent's target LTV
- maxLtvBps: the protocol's maximum LTV before liquidation
- yieldSpreadBps: (vault APY - borrow APR) in basis points
- collateralPriceUsd: current collateral price
- priceChange1h: 1-hour price change percentage
- priceChange24h: 24-hour price change percentage

RISK LEVELS:
- 0 (SAFE): LTV well below target, positive yield spread, stable prices
- 1 (WARNING): LTV approaching target OR yield spread narrowing OR moderate price volatility
- 2 (DANGER): LTV above target OR negative yield spread OR high price volatility (>5% drop)
- 3 (CRITICAL): LTV within 5% of max (liquidation imminent) OR price crash (>10% drop in 1h)

OUTPUT FORMAT (CRITICAL):
You MUST respond with a SINGLE JSON object:
{"riskLevel": <0-3>, "confidence": <0-10000>, "action": "hold"|"repay"|"borrow"|"pause"|"close", "repayAmountBps": <0-10000>, "reasoning": "<brief explanation>"}

- repayAmountBps: percentage of outstanding debt to repay (in bps), only relevant if action is "repay"
- confidence: your confidence in this assessment (0-10000 scale)

STRICT RULES:
- Output MUST be valid JSON. No markdown, no backticks, no prose.
- Output MUST be MINIFIED (one line).
- If uncertain, default to higher risk level (be conservative).
- If you cannot produce valid JSON, output: {"riskLevel":3,"confidence":0,"action":"pause","repayAmountBps":0,"reasoning":"error"}
`;

const REBALANCE_SYSTEM_PROMPT = `
You are a DeFi rebalance strategy engine for BorrowBot, an autonomous lending agent.
A CRITICAL risk event has been detected. You must determine the optimal rebalance action.

Your task: Given position data, market conditions, and the agent's ENS constitution (governance rules),
determine the best rebalance strategy to protect the position from liquidation.

INPUTS:
- Position: collateral value, borrow amount, vault balance, current LTV, max LTV
- Constitution: max-ltv setting, min-spread setting, pause flag, allowed collateral
- Market: current prices, volatility

ACTION TYPES:
- 0 (REPAY): Withdraw from vault, repay debt to reduce LTV
- 1 (BORROW): Borrow more to optimize yield (only if safe)
- 2 (PAUSE): Stop all autonomous actions
- 3 (CLOSE): Full position unwind (extreme cases only)

OUTPUT FORMAT (CRITICAL):
{"actionType": <0-3>, "amountUsd": <number>, "targetLtvBps": <number>, "confidence": <0-10000>, "reasoning": "<brief>"}

STRICT RULES:
- Output MUST be valid JSON. No markdown, no backticks.
- MINIFIED (one line).
- Default to REPAY if uncertain. Never CLOSE unless LTV > 95% of max.
- amountUsd is in USD (will be converted to USDC 6-decimal base units)
`;

export function askGeminiRisk(
  runtime: Runtime<Config>,
  positionData: string
): GeminiResponse {
  runtime.log("[Gemini] Querying AI for risk assessment...");
  return queryGemini(runtime, RISK_SYSTEM_PROMPT, positionData);
}

export function askGeminiRebalance(
  runtime: Runtime<Config>,
  positionData: string
): GeminiResponse {
  runtime.log("[Gemini] Querying AI for rebalance strategy...");
  return queryGemini(runtime, REBALANCE_SYSTEM_PROMPT, positionData);
}

function queryGemini(
  runtime: Runtime<Config>,
  systemPrompt: string,
  userPrompt: string
): GeminiResponse {
  const geminiApiKey = runtime.getSecret({ id: "GEMINI_API_KEY" }).result();
  const httpClient = new cre.capabilities.HTTPClient();

  const result = httpClient
    .sendRequest(
      runtime,
      buildGeminiRequest(systemPrompt, userPrompt, geminiApiKey.value),
      consensusIdenticalAggregation<GeminiResponse>()
    )(runtime.config)
    .result();

  runtime.log(`[Gemini] Response: ${result.geminiResponse}`);
  return result;
}

const buildGeminiRequest =
  (systemPrompt: string, userPrompt: string, apiKey: string) =>
  (sendRequester: HTTPSendRequester, config: Config): GeminiResponse => {
    const requestData: GeminiData = {
      system_instruction: { parts: [{ text: systemPrompt }] },
      contents: [{ parts: [{ text: userPrompt }] }],
    };

    const bodyBytes = new TextEncoder().encode(JSON.stringify(requestData));
    const body = Buffer.from(bodyBytes).toString("base64");

    const resp = sendRequester
      .sendRequest({
        url: `https://generativelanguage.googleapis.com/v1beta/models/${config.geminiModel}:generateContent`,
        method: "POST" as const,
        body,
        headers: {
          "Content-Type": "application/json",
          "x-goog-api-key": apiKey,
        },
        cacheSettings: { store: true, maxAge: "60s" },
      })
      .result();

    const bodyText = new TextDecoder().decode(resp.body);

    if (!ok(resp)) {
      throw new Error(`Gemini API error: ${resp.statusCode} - ${bodyText}`);
    }

    const apiResponse = JSON.parse(bodyText) as GeminiApiResponse;
    const text = apiResponse?.candidates?.[0]?.content?.parts?.[0]?.text;

    if (!text) {
      throw new Error("Malformed Gemini response: missing text");
    }

    return {
      statusCode: resp.statusCode,
      geminiResponse: text,
      responseId: apiResponse.responseId || "",
    };
  };
