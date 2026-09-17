import { Construct } from 'constructs';
import {
  Dashboard,
  GraphWidget,
  SingleValueWidget,
  TextWidget,
  Metric,
} from 'aws-cdk-lib/aws-cloudwatch';

export interface ObservabilityDashboardProps {
  projectName: string;
}

export class ObservabilityDashboard extends Construct {
  constructor(scope: Construct, id: string, props: ObservabilityDashboardProps) {
    super(scope, id);

    const { projectName } = props;

    // Define standard namespaces
    const cwNamespace = 'PharmaAgent';

    // Helper functions for metric definition
    const cwMetric = (metricName: string, statistic = 'Sum') => {
      return new Metric({
        namespace: cwNamespace,
        metricName,
        statistic,
      });
    };

    const cwToolMetric = (metricName: string, toolName: string, statistic = 'Sum') => {
      return new Metric({
        namespace: cwNamespace,
        metricName,
        dimensionsMap: { Tool: toolName },
        statistic,
      });
    };

    // Standard model identifiers found in CloudWatch list-metrics
    const bedrockModels = [
      'global.anthropic.claude-haiku-4-5-20251001-v1:0',
      'anthropic.claude-3-haiku-20240307-v1:0',
      'arn:aws:bedrock:ap-south-1:668426476778:application-inference-profile/upgxqq2kbtgi',
    ];

    // Helper functions to generate metrics for all model paths
    const getBedrockDurationMetrics = (metricName: string, statistic = 'Sum', labelPrefix: string) => {
      return bedrockModels.map(model => {
        const shortLabel = model.includes('inference-profile')
          ? 'Inference Profile'
          : model.split('.').pop() || model;
        return new Metric({
          namespace: 'bedrock-agentcore',
          metricName,
          dimensionsMap: {
            'gen_ai.system': 'aws.bedrock',
            'server.address': 'bedrock-runtime.ap-south-1.amazonaws.com',
            'server.port': '443',
            'gen_ai.request.model': model,
            'gen_ai.operation.name': 'chat',
          },
          statistic,
          label: `${labelPrefix} (${shortLabel})`,
        });
      });
    };

    const getBedrockTokenMetrics = (tokenType: 'input' | 'output', labelPrefix: string) => {
      return bedrockModels.map(model => {
        const shortLabel = model.includes('inference-profile')
          ? 'Inference Profile'
          : model.split('.').pop() || model;
        return new Metric({
          namespace: 'bedrock-agentcore',
          metricName: 'gen_ai.client.token.usage',
          dimensionsMap: {
            'gen_ai.system': 'aws.bedrock',
            'server.address': 'bedrock-runtime.ap-south-1.amazonaws.com',
            'server.port': '443',
            'gen_ai.request.model': model,
            'gen_ai.operation.name': 'chat',
            'gen_ai.token.type': tokenType,
          },
          statistic: 'Sum',
          label: `${labelPrefix} (${shortLabel})`,
        });
      });
    };

    // Create the dashboard
    const dashboard = new Dashboard(this, 'PharmaAgentDashboard', {
      dashboardName: `AgentCore-${projectName}-Observability`,
    });

    // 1. Title/Header Row
    dashboard.addWidgets(
      new TextWidget({
        markdown: `# PharmaAgent Observability Dashboard\nThis dashboard monitors agent health, latencies, resource consumption, and sub-system integrations using both native CloudWatch metrics and exported OpenTelemetry (OTel) metrics.`,
        width: 24,
        height: 2,
      })
    );

    // 2. Section: Agent Performance
    dashboard.addWidgets(
      new TextWidget({
        markdown: `## 1. Agent Requests & Performance`,
        width: 24,
        height: 1,
      })
    );

    dashboard.addWidgets(
      new SingleValueWidget({
        title: 'Incoming Agent Requests (Total)',
        metrics: [
          cwMetric('AgentRequests'),
        ],
        width: 8,
        height: 6,
      }),
      new SingleValueWidget({
        title: 'Success vs Failure Counts',
        metrics: [
          cwMetric('AgentSuccess'),
          cwMetric('AgentFailure'),
        ],
        width: 8,
        height: 6,
      }),
      new GraphWidget({
        title: 'Agent Processing Latency (ms)',
        left: [
          cwMetric('AgentLatency', 'Average'),
          cwMetric('AgentLatency', 'p99'),
        ],
        width: 8,
        height: 6,
      })
    );

    // 3. Section: Orchestrator, Sessions, LLM Invocations
    dashboard.addWidgets(
      new TextWidget({
        markdown: `## 2. Orchestrator & LLM Performance`,
        width: 24,
        height: 1,
      })
    );

    dashboard.addWidgets(
      new GraphWidget({
        title: 'Concurrent Active Sessions',
        left: [cwMetric('ActiveSessions', 'Maximum').with({ label: 'Active Sessions' })],
        width: 12,
        height: 6,
      }),
      new GraphWidget({
        title: 'Bedrock LLM Invocations & Latency',
        left: getBedrockDurationMetrics('gen_ai.client.operation.duration', 'SampleCount', 'Invocations'),
        right: getBedrockDurationMetrics('gen_ai.client.operation.duration', 'Average', 'Latency'),
        width: 12,
        height: 6,
      })
    );

    // 4. Section: Tools
    dashboard.addWidgets(
      new TextWidget({
        markdown: `## 3. Tool Executions & Integrations`,
        width: 24,
        height: 1,
      })
    );

    dashboard.addWidgets(
      new SingleValueWidget({
        title: 'Tool Executions Status',
        metrics: [
          cwMetric('ToolSuccess'),
          cwMetric('ToolFailure'),
        ],
        width: 6,
        height: 6,
      }),
      new GraphWidget({
        title: 'Tool Execution Latency (ms)',
        left: [cwMetric('ToolLatency', 'Average')],
        width: 9,
        height: 6,
      }),
      new GraphWidget({
        title: 'Tool Invocations by Type',
        left: [
          cwToolMetric('ToolInvocations', 'DrugLookup').with({ label: 'Drug Lookup' }),
          cwToolMetric('ToolInvocations', 'ToxicityLookup').with({ label: 'Toxicity Lookup' }),
          cwToolMetric('ToolInvocations', 'InteractionLookup').with({ label: 'Interaction Lookup' }),
        ],
        width: 9,
        height: 6,
      })
    );

    // 5. Section: External Services (DailyMed API)
    dashboard.addWidgets(
      new TextWidget({
        markdown: `## 4. External Services & DailyMed API Integration`,
        width: 24,
        height: 1,
      })
    );

    dashboard.addWidgets(
      new GraphWidget({
        title: 'DailyMed Requests & Failures',
        left: [
          cwMetric('DailyMedRequests'),
          cwMetric('DailyMedSuccess'),
          cwMetric('DailyMedFailure'),
        ],
        width: 12,
        height: 6,
      }),
      new GraphWidget({
        title: 'DailyMed Request Latency (ms)',
        left: [cwMetric('DailyMedLatency', 'Average')],
        width: 12,
        height: 6,
      })
    );

    // 6. Section: Business Metrics & Token Usage
    dashboard.addWidgets(
      new TextWidget({
        markdown: `## 5. Token Usage & Business Metrics`,
        width: 24,
        height: 1,
      })
    );

    dashboard.addWidgets(
      new GraphWidget({
        title: 'LLM Token Usage (Prompts vs Completion)',
        left: [
          ...getBedrockTokenMetrics('input', 'Prompt Tokens'),
          ...getBedrockTokenMetrics('output', 'Completion Tokens'),
        ],
        width: 12,
        height: 6,
      }),
      new GraphWidget({
        title: 'Business Metric: Drug Search Outcomes',
        left: [
          cwMetric('DrugFound').with({ label: 'Drug Found' }),
          cwMetric('DrugNotFound').with({ label: 'Drug Not Found' }),
        ],
        width: 12,
        height: 6,
      })
    );
  }
}
