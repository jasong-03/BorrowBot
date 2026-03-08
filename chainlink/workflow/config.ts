import { z } from "zod";

export const configSchema = z.object({
  schedule: z.string(),
  geminiModel: z.string(),
  borrowbotApiUrl: z.string(),
  priceApiUrl: z.string(),
  evms: z.array(
    z.object({
      riskOracleAddress: z.string(),
      executorAddress: z.string(),
      chainSelectorName: z.string(),
      gasLimit: z.string(),
    })
  ),
});

export type Config = z.infer<typeof configSchema>;
