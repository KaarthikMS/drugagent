import * as path from 'path';
import { HttpApi, CorsHttpMethod, HttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Code, Function as LambdaFunction, Runtime } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { CfnOutput, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as fs from 'fs';

/**
 * Locate a Lambda source directory.
 *
 * cdk.json runs the COMPILED app (`dist/bin/cdk.js`), so __dirname is
 * dist/lib and the sources sit two levels up. Checked rather than
 * assumed, because the failure mode is a synth error that `cdk synth
 * --quiet` reports with exit code 0.
 */
function lambdaAsset(name: string): string {
  for (const base of ['..', '../..']) {
    const candidate = path.resolve(__dirname, base, 'lambda', name);
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(`Lambda source not found for '${name}'. Looked beside ${__dirname}.`);
}

export interface ApiProps {
  /** Project name, used for resource naming. */
  projectName: string;
  /** ARN of the AgentCore runtime the proxy invokes. */
  runtimeArn: string;
  /** Origins allowed to call the API — the local dev server's origin(s). */
  allowedOrigins: string[];
}

/**
 * The unauthenticated path to the agent.
 *
 *   Local UI -> API Gateway -> proxy Lambda (signs SigV4) -> AgentCore Runtime
 *
 * There is no Cognito, no Hosted UI, no hosted frontend. This replaced an
 * auth stack (Cognito User Pool + Hosted UI + S3/CloudFront) whose Hosted
 * UI would not complete the OAuth authorization-code flow — see CLAUDE.md
 * traps for the diagnostic trail. The frontend now runs locally; this
 * construct is only the signing proxy in front of the runtime.
 *
 * This is a POC-scope trade: anyone who can reach the API can invoke the
 * agent, and every caller shares undifferentiated access. Fine while the
 * only caller is a developer running the frontend locally; revisit before
 * this is reachable by anyone else — see CLAUDE.md "Still open".
 */
export class Api extends Construct {
  public readonly api: HttpApi;

  constructor(scope: Construct, id: string, props: ApiProps) {
    super(scope, id);

    const proxy = new LambdaFunction(this, 'ChatProxy', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(lambdaAsset('chat-proxy')),
      // Below API Gateway's 30s integration timeout, so a slow runtime
      // surfaces as a gateway timeout rather than as a Lambda billed
      // past the point anyone is still waiting.
      timeout: Duration.seconds(29),
      memorySize: 512,
      logGroup: new LogGroup(this, 'ChatProxyLogs', {
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
      environment: {
        AGENT_RUNTIME_ARN: props.runtimeArn,
        MAX_PROMPT_CHARS: '4000',
      },
    });

    proxy.addToRolePolicy(
      new PolicyStatement({
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        // Scoped to the one runtime. The wildcard suffix covers the
        // qualified endpoint ARN AgentCore appends.
        resources: [props.runtimeArn, `${props.runtimeArn}/*`],
      })
    );

    this.api = new HttpApi(this, 'Api', {
      apiName: `${props.projectName}-api`,
      corsPreflight: {
        allowOrigins: props.allowedOrigins,
        allowMethods: [CorsHttpMethod.POST, CorsHttpMethod.OPTIONS],
        allowHeaders: ['Content-Type'],
        maxAge: Duration.hours(1),
      },
    });

    this.api.addRoutes({
      path: '/chat',
      methods: [HttpMethod.POST],
      integration: new HttpLambdaIntegration('ChatIntegration', proxy),
    });

    // The default stage carries the throttle. Unauthenticated means
    // anyone who has the URL can call it -- this is the one guard against
    // a runaway script, not a substitute for the auth that used to be
    // here.
    const stage = this.api.defaultStage?.node.defaultChild as { defaultRouteSettings?: unknown } | undefined;
    if (stage) {
      (stage as { defaultRouteSettings: unknown }).defaultRouteSettings = {
        throttlingRateLimit: 10,
        throttlingBurstLimit: 20,
      };
    }

    new CfnOutput(this, 'ApiEndpoint', { value: this.api.apiEndpoint });
  }
}
