import {
  AgentCoreApplication,
  AgentCoreMcp,
  type AgentCoreProjectSpec,
  type AgentCoreMcpSpec,
} from '@aws/agentcore-cdk';
import { CfnOutput, Stack, type StackProps } from 'aws-cdk-lib';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { Api } from './api';
import { ObservabilityDashboard } from './observability-dashboard';

export interface AgentCoreStackProps extends StackProps {
  /**
   * The AgentCore project specification containing agents, memories, and credentials.
   */
  spec: AgentCoreProjectSpec;
  /**
   * The MCP specification containing gateways and servers.
   */
  mcpSpec?: AgentCoreMcpSpec;
  /**
   * Credential provider ARNs from deployed state, keyed by credential name.
   */
  credentials?: Record<string, { credentialProviderArn: string; clientSecretArn?: string }>;
  /** Origins allowed to call the API — the local dev server's origin(s). */
  allowedOrigins?: string[];
}

/**
 * CDK Stack that deploys AgentCore infrastructure.
 *
 * This is a thin wrapper that instantiates L3 constructs.
 * All resource logic and outputs are contained within the L3 constructs.
 */
export class AgentCoreStack extends Stack {
  /** The AgentCore application containing all agent environments */
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { spec, mcpSpec, credentials } = props;

    // Create AgentCoreApplication with all agents
    this.application = new AgentCoreApplication(this, 'Application', {
      spec,
    });

    // Grant cloudwatch:PutMetricData permissions to the drugagent runtime execution role
    const drugAgentEnv = this.application.environments.get('drugagent');
    if (drugAgentEnv) {
      drugAgentEnv.runtime.addToPolicy(
        new PolicyStatement({
          actions: ['cloudwatch:PutMetricData'],
          resources: ['*'],
        })
      );

      // Allow the runtime to apply the guardrail named in its own env vars.
      //
      // The runtime's execution role does not get this by default: attaching a
      // guardrail to a Bedrock request requires bedrock:ApplyGuardrail on that
      // guardrail's ARN, and without it EVERY invocation fails with
      // AccessDeniedException -- a deploy that reports success and an agent
      // that answers nothing.
      //
      // The id is read from the spec rather than written here, so
      // agentcore.json stays the single place it appears.
      const guardrailId = spec.runtimes
        .find(r => r.name === 'drugagent')
        ?.envVars?.find(v => v.name === 'GUARDRAIL_ID')?.value;

      if (guardrailId) {
        drugAgentEnv.runtime.addToPolicy(
          new PolicyStatement({
            actions: ['bedrock:ApplyGuardrail'],
            resources: [`arn:aws:bedrock:${this.region}:${this.account}:guardrail/${guardrailId}`],
          })
        );
      }
    }

    // ----------------------------------------------------------------
    // The unauthenticated path: API Gateway -> proxy -> runtime
    //
    // No auth stack. The frontend runs locally; this is only the SigV4
    // signing proxy in front of the runtime. See api.ts for why.
    // ----------------------------------------------------------------
    if (drugAgentEnv) {
      new Api(this, 'Api', {
        projectName: spec.name,
        runtimeArn: drugAgentEnv.runtime.runtimeArn,
        allowedOrigins: props.allowedOrigins?.length
          ? props.allowedOrigins
          : ['http://localhost:8080'],
      });
    }

    // Instantiate custom observability dashboard
    new ObservabilityDashboard(this, 'ObservabilityDashboard', {
      projectName: spec.name,
    });

    // Create AgentCoreMcp if there are gateways configured
    if (mcpSpec?.agentCoreGateways && mcpSpec.agentCoreGateways.length > 0) {
      new AgentCoreMcp(this, 'Mcp', {
        projectName: spec.name,
        mcpSpec,
        agentCoreApplication: this.application,
        credentials,
        projectTags: spec.tags,
      });
    }

    // Stack-level output
    new CfnOutput(this, 'StackNameOutput', {
      description: 'Name of the CloudFormation Stack',
      value: this.stackName,
    });
  }
}
