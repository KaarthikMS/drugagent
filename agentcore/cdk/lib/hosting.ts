import {
  AllowedMethods,
  Distribution,
  HeadersFrameOption,
  HeadersReferrerPolicy,
  ResponseHeadersPolicy,
  ViewerProtocolPolicy,
} from 'aws-cdk-lib/aws-cloudfront';
import { S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import { BlockPublicAccess, Bucket, BucketEncryption } from 'aws-cdk-lib/aws-s3';
import { CfnOutput, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface HostingProps {
  projectName: string;
}

/**
 * Static hosting for the dashboard.
 *
 * S3 behind CloudFront with origin access control: the bucket blocks all
 * public access and only the distribution can read it. That matters less
 * for correctness than for the fact that a directly-readable bucket is
 * the most common way a "static site" leaks its config.
 *
 * Nothing sensitive is served here -- the page, its script, and a Cognito
 * client id. The security headers below are what make it safe to keep
 * that true: a content policy narrow enough that an injected script has
 * nowhere to send anything.
 */
export class Hosting extends Construct {
  public readonly bucket: Bucket;
  public readonly distribution: Distribution;

  constructor(scope: Construct, id: string, props: HostingProps) {
    super(scope, id);

    this.bucket = new Bucket(this, 'SiteBucket', {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      // The bucket holds only build output. Deleting the stack should
      // not leave one behind for someone to rediscover later.
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // connect-src is the line that matters. An injected script can run,
    // but it can only talk to Cognito and this account's API -- not to
    // an attacker's collection endpoint. Health questions never leave
    // the two hosts that are supposed to see them.
    const headers = new ResponseHeadersPolicy(this, 'SecurityHeaders', {
      securityHeadersBehavior: {
        contentSecurityPolicy: {
          override: true,
          contentSecurityPolicy: [
            "default-src 'none'",
            "script-src 'self'",
            // The page's styles are inline in index.html.
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self' https://*.amazoncognito.com https://*.execute-api.*.amazonaws.com",
            // Citations open on nlm.nih.gov and fda.gov.
            "form-action 'self' https://*.amazoncognito.com",
            "frame-ancestors 'none'",
            "base-uri 'none'",
          ].join('; '),
        },
        strictTransportSecurity: {
          override: true,
          accessControlMaxAge: Duration.days(365),
          includeSubdomains: true,
        },
        contentTypeOptions: { override: true },
        frameOptions: { override: true, frameOption: HeadersFrameOption.DENY },
        referrerPolicy: {
          override: true,
          // A citation link must not carry the assistant's URL to
          // nlm.nih.gov, and an auth redirect must not carry a code.
          referrerPolicy: HeadersReferrerPolicy.NO_REFERRER,
        },
      },
    });

    this.distribution = new Distribution(this, 'Distribution', {
      defaultBehavior: {
        origin: S3BucketOrigin.withOriginAccessControl(this.bucket),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: AllowedMethods.ALLOW_GET_HEAD,
        responseHeadersPolicy: headers,
      },
      defaultRootObject: 'index.html',
      comment: `${props.projectName} dashboard`,
    });

    new CfnOutput(this, 'SiteBucketName', { value: this.bucket.bucketName });
    new CfnOutput(this, 'SiteUrl', {
      value: `https://${this.distribution.distributionDomainName}`,
    });
  }
}
