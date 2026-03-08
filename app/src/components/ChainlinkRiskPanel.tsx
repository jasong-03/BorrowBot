import React from 'react';

import { Alignment, Box, Direction, PaddingSize, Spacing, Stack, Text } from '@kibalabs/ui-react';
import { createPublicClient, http, formatUnits } from 'viem';
import { sepolia } from 'viem/chains';

import './ChainlinkRiskPanel.scss';

const RISK_ORACLE_ADDRESS = '0x91051e8b35280D54Dbfa2e817E1edA4724572C14' as const;

const RISK_ORACLE_ABI = [
  {
    name: 'assessmentHistory',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: '', type: 'uint256' }],
    outputs: [
      { name: 'agentId', type: 'bytes32' },
      { name: 'riskLevel', type: 'uint8' },
      { name: 'currentLtvBps', type: 'uint16' },
      { name: 'targetLtvBps', type: 'uint16' },
      { name: 'maxLtvBps', type: 'uint16' },
      { name: 'yieldSpreadBps', type: 'int16' },
      { name: 'timestamp', type: 'uint48' },
      { name: 'confidence', type: 'uint16' },
      { name: 'actionHash', type: 'bytes32' },
    ],
  },
  {
    name: 'getAssessmentCount',
    type: 'function',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ name: '', type: 'uint256' }],
  },
] as const;

const RISK_LABELS = ['SAFE', 'WARNING', 'DANGER', 'CRITICAL'] as const;
const RISK_COLORS = ['#22c55e', '#f59e0b', '#ef4444', '#dc2626'] as const;

interface RiskAssessment {
  riskLevel: number;
  currentLtvBps: number;
  targetLtvBps: number;
  maxLtvBps: number;
  yieldSpreadBps: number;
  timestamp: number;
  confidence: number;
}

const sepoliaClient = createPublicClient({
  chain: sepolia,
  transport: http('https://ethereum-sepolia-rpc.publicnode.com'),
});

export function ChainlinkRiskPanel(): React.ReactElement {
  const [assessment, setAssessment] = React.useState<RiskAssessment | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    const fetchAssessment = async (): Promise<void> => {
      try {
        const count = await sepoliaClient.readContract({
          address: RISK_ORACLE_ADDRESS,
          abi: RISK_ORACLE_ABI,
          functionName: 'getAssessmentCount',
        });

        if (cancelled) return;

        if (count === 0n) {
          setAssessment(null);
          setIsLoading(false);
          return;
        }

        const result = await sepoliaClient.readContract({
          address: RISK_ORACLE_ADDRESS,
          abi: RISK_ORACLE_ABI,
          functionName: 'assessmentHistory',
          args: [count - 1n],
        });

        if (cancelled) return;

        setAssessment({
          riskLevel: result[1],
          currentLtvBps: result[2],
          targetLtvBps: result[3],
          maxLtvBps: result[4],
          yieldSpreadBps: result[5],
          timestamp: Number(result[6]),
          confidence: result[7],
        });
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError('Unable to fetch on-chain data');
        console.error('ChainlinkRiskPanel fetch failed:', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    fetchAssessment();
    const intervalId = setInterval(fetchAssessment, 30000);

    return (): void => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, []);

  const formatBps = (bps: number): string => `${(bps / 100).toFixed(2)}%`;

  const formatTimestamp = (ts: number): string => {
    if (ts === 0) return 'N/A';
    return new Date(ts * 1000).toLocaleString();
  };

  if (isLoading) {
    return (
      <Box className='chainlinkRiskPanel statCard' isFullWidth={true}>
        <Stack direction={Direction.Vertical} shouldAddGutters={true} childAlignment={Alignment.Center}>
          <Text variant='note'>Loading Chainlink CRE data...</Text>
        </Stack>
      </Box>
    );
  }

  return (
    <Box className='chainlinkRiskPanel statCard' isFullWidth={true}>
      <Stack direction={Direction.Vertical} shouldAddGutters={true}>
        <Stack direction={Direction.Horizontal} childAlignment={Alignment.Center} shouldAddGutters={true}>
          <img src='https://assets.coingecko.com/coins/images/877/small/chainlink-new-logo.png' alt='Chainlink' width='24' height='24' />
          <Text variant='bold'>Chainlink CRE Risk Oracle</Text>
          <Stack.Item growthFactor={1} shrinkFactor={1} />
          <span className='chainlinkBadge'>On-Chain</span>
        </Stack>

        <Spacing variant={PaddingSize.Narrow} />

        {error && (
          <Text variant='note' style={{ color: '#ef4444' }}>{error}</Text>
        )}

        {!assessment && !error && (
          <Stack direction={Direction.Vertical} shouldAddGutters={true} childAlignment={Alignment.Center}>
            <Text variant='note'>No risk assessments yet.</Text>
            <Text variant='note' style={{ color: '#6b7280' }}>
              Run CRE workflow simulation to publish on-chain data.
            </Text>
          </Stack>
        )}

        {assessment && (
          <React.Fragment>
            <div className='riskLevelDisplay'>
              <div className='riskIndicator' style={{ backgroundColor: RISK_COLORS[assessment.riskLevel] }}>
                <span className='riskLabel'>{RISK_LABELS[assessment.riskLevel]}</span>
              </div>
              <div className='confidenceBar'>
                <Text variant='note'>{`Confidence: ${formatBps(assessment.confidence)}`}</Text>
                <div className='confidenceTrack'>
                  <div className='confidenceFill' style={{ width: `${assessment.confidence / 100}%` }} />
                </div>
              </div>
            </div>

            <div className='riskMetrics'>
              <div className='metricRow'>
                <Text variant='note'>Current LTV</Text>
                <Text variant='bold'>{formatBps(assessment.currentLtvBps)}</Text>
              </div>
              <div className='metricRow'>
                <Text variant='note'>Target LTV</Text>
                <Text>{formatBps(assessment.targetLtvBps)}</Text>
              </div>
              <div className='metricRow'>
                <Text variant='note'>Max LTV</Text>
                <Text>{formatBps(assessment.maxLtvBps)}</Text>
              </div>
              <div className='metricRow'>
                <Text variant='note'>Yield Spread</Text>
                <Text style={{ color: assessment.yieldSpreadBps >= 0 ? '#22c55e' : '#ef4444' }}>
                  {assessment.yieldSpreadBps >= 0 ? '+' : ''}
                  {formatBps(assessment.yieldSpreadBps)}
                </Text>
              </div>
              <div className='metricRow lastAssessed'>
                <Text variant='note'>Last Assessed</Text>
                <Text variant='note'>{formatTimestamp(assessment.timestamp)}</Text>
              </div>
            </div>

            <Stack direction={Direction.Horizontal} shouldAddGutters={true} childAlignment={Alignment.Center}>
              <Text variant='note' style={{ color: '#6b7280', fontSize: '11px' }}>
                Verified by Chainlink DON on Sepolia
              </Text>
              <Stack.Item growthFactor={1} shrinkFactor={1} />
              <a
                href={`https://sepolia.etherscan.io/address/${RISK_ORACLE_ADDRESS}`}
                target='_blank'
                rel='noopener noreferrer'
                style={{ color: '#375bd2', fontSize: '11px', textDecoration: 'underline' }}
              >
                View Contract
              </a>
            </Stack>
          </React.Fragment>
        )}
      </Stack>
    </Box>
  );
}
