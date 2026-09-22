import * as path from 'path';
import { HttpApi, CorsHttpMethod, HttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import {
  AccountRecovery,
  AdvancedSecurityMode,
  Mfa,
  OAuthScope,
  UserPool,
  UserPoolClient,
  UserPoolDomain,
  UserPoolEmail,
} from 'aws-cdk-lib/aws-cognito';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Code, Function as LambdaFunction, Runtime } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
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

export interface AuthProps {
  /** Project name, used for resource naming. */
  projectName: string;
  /** ARN of the AgentCore runtime the proxy invokes. */
  runtimeArn: string;
  /** Email domains permitted to hold an account, e.g. ['company.com']. */
  allowedEmailDomains: string[];
  /** Origins allowed to call the API. The dashboard's origin. */
  allowedOrigins: string[];
}

/**
 * Authentication and the authenticated path to the agent.
 *
 *   Browser -> Cognito Hosted UI -> JWT
 *           -> API Gateway (JWT authorizer)
 *           -> proxy Lambda (signs SigV4)
 *           -> AgentCore Runtime
 *
 * This replaces the local FastAPI server, which signed the same call
 * with a developer's credentials and had no authentication in front of
 * it. The runtime has always been IAM-protected; what was missing was a
 * way for a person to reach it without being given AWS credentials.
 */
export class Auth extends Construct {
  public readonly userPool: UserPool;
  public readonly api: HttpApi;

  constructor(scope: Construct, id: string, props: AuthProps) {
    super(scope, id);

    const stack = Stack.of(this);

    if (props.allowedEmailDomains.length === 0) {
      throw new Error(
        'allowedEmailDomains is empty. Set the org email domain in agentcore/cdk/bin/cdk.ts ' +
          'or via `cdk deploy -c allowedEmailDomains=company.com`. Deploying without it ' +
          'would create a pool that rejects every sign-up.'
      );
    }

    // ----------------------------------------------------------------
    // Domain restriction
    //
    // A user pool has no attribute constraint for "only @company.com",
    // so the rule lives in a PreSignUp trigger. It is a second line:
    // self sign-up is disabled below, and this catches a future change
    // that re-enables it.
    // ----------------------------------------------------------------
    const preSignUp = new LambdaFunction(this, 'PreSignUp', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(lambdaAsset('pre-signup')),
      timeout: Duration.seconds(5),
      logGroup: new LogGroup(this, 'PreSignUpLogs', {
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
      environment: {
        ALLOWED_EMAIL_DOMAINS: props.allowedEmailDomains.join(','),
      },
    });

    this.userPool = new UserPool(this, 'UserPool', {
      userPoolName: `${props.projectName}-users`,
      // Admin-invite only. A hundred known employees, and self sign-up
      // plus a domain check still admits anyone holding a company
      // address -- including people who have left.
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: false },
        givenName: { required: false, mutable: true },
      },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
        tempPasswordValidity: Duration.days(7),
      },
      mfa: Mfa.OPTIONAL,
      mfaSecondFactor: { sms: false, otp: true },
      accountRecovery: AccountRecovery.EMAIL_ONLY,
      advancedSecurityMode: AdvancedSecurityMode.AUDIT,
      email: UserPoolEmail.withCognito(),
      lambdaTriggers: { preSignUp },
      // The pool holds the identities of every employee using a health
      // service. Losing it is worse than a failed `cdk destroy`.
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const domainPrefix = `${props.projectName}-${stack.account.slice(-6)}`;
    const userPoolDomain = new UserPoolDomain(this, 'Domain', {
      userPool: this.userPool,
      cognitoDomain: { domainPrefix },
    });

    const client = new UserPoolClient(this, 'WebClient', {
      userPool: this.userPool,
      generateSecret: false, // a browser cannot keep one
      authFlows: { userSrp: true },
      oAuth: {
        flows: {
          // Authorization code with PKCE. The implicit flow is off:
          // it returns the token in the URL fragment, where it lands in
          // browser history and any referrer.
          authorizationCodeGrant: true,
          implicitCodeGrant: false,
        },
        scopes: [OAuthScope.OPENID, OAuthScope.EMAIL, OAuthScope.PROFILE],
        callbackUrls: props.allowedOrigins,
        logoutUrls: props.allowedOrigins,
      },
      // Health questions are occasional, not all-day. A shorter token
      // limits what a stolen one is worth.
      idTokenValidity: Duration.hours(8),
      accessTokenValidity: Duration.hours(8),
      refreshTokenValidity: Duration.days(30),
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
    });

    // ----------------------------------------------------------------
    // The proxy
    // ----------------------------------------------------------------
    const proxy = new LambdaFunction(this, 'ChatProxy', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(lambdaAsset('chat-proxy')),
      // Below API Gateway's 30s integration timeout, so a slow runtime
      // surfaces as a gateway timeout rather than as a Lambda billed
      // past the point anyone is still waiting.
      timeout: Duration.seconds(29),
      memorySize: 512,
      // A month. Long enough to investigate an incident, short enough
      // that a log line which should never contain content cannot
      // accumulate for years if one ever does.
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

    // ----------------------------------------------------------------
    // The API
    // ----------------------------------------------------------------
    const authorizer = new HttpJwtAuthorizer('JwtAuthorizer', this.userPool.userPoolProviderUrl, {
      jwtAudience: [client.userPoolClientId],
      identitySource: ['$request.header.Authorization'],
    });

    this.api = new HttpApi(this, 'Api', {
      apiName: `${props.projectName}-api`,
      corsPreflight: {
        // Named origins only. A wildcard with credentials is refused by
        // browsers anyway, and a wildcard without them invites any page
        // on the internet to spend this account's tokens.
        allowOrigins: props.allowedOrigins,
        allowMethods: [CorsHttpMethod.POST, CorsHttpMethod.OPTIONS],
        allowHeaders: ['Authorization', 'Content-Type'],
        maxAge: Duration.hours(1),
      },
    });

    this.api.addRoutes({
      path: '/chat',
      methods: [HttpMethod.POST],
      integration: new HttpLambdaIntegration('ChatIntegration', proxy),
      authorizer,
    });

    // The default stage carries the throttle. ~100 users asking
    // occasional questions do not approach this; a runaway script does,
    // and until now the system had no rate limit at all.
    const stage = this.api.defaultStage?.node.defaultChild as { defaultRouteSettings?: unknown } | undefined;
    if (stage) {
      (stage as { defaultRouteSettings: unknown }).defaultRouteSettings = {
        throttlingRateLimit: 10,
        throttlingBurstLimit: 20,
      };
    }

    // ----------------------------------------------------------------
    // What the frontend needs to configure itself
    // ----------------------------------------------------------------
    new CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: client.userPoolClientId });
    new CfnOutput(this, 'HostedUiDomain', {
      value: `https://${userPoolDomain.domainName}.auth.${stack.region}.amazoncognito.com`,
    });
    new CfnOutput(this, 'ApiEndpoint', { value: this.api.apiEndpoint });
  }
}
