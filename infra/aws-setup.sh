#!/usr/bin/env bash
# Deploys infra/cloudformation.yaml (log group + stream, SNS topic + email subscription,
# ErrorRate and detector-silent alarms, least-privilege IAM policy) and prints the .env values.
#
#   ALERT_EMAIL=you@example.com AWS_REGION=ap-south-1 bash infra/aws-setup.sh
#
# Cost: CloudWatch Logs ingestion/storage (a few KB/day of alerts), 2 standard alarms
# (~$0.10/alarm/month), custom metrics (4 metrics, ~$0.30/metric/month), SNS email (free tier).
set -euo pipefail

REGION=${AWS_REGION:-ap-south-1}
STACK=${STACK_NAME:-accentra-log-anomaly}
: "${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should receive alerts}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Deploying stack $STACK to $REGION ..."
aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK" \
  --template-file "$HERE/cloudformation.yaml" \
  --parameter-overrides "AlertEmail=$ALERT_EMAIL" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset

out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo
echo "Add these to .env (or export them) and set PUBLISH_MODE=aws:"
echo "  AWS_REGION=$REGION"
echo "  CW_LOG_GROUP=$(out LogGroupName)"
echo "  CW_LOG_STREAM=$(out LogStreamName)"
echo "  SNS_TOPIC_ARN=$(out SnsTopicArn)"
echo
echo "Attach this policy to the identity running the detector: $(out DetectorPolicyArn)"
echo "Then confirm the SNS subscription from the email sent to $ALERT_EMAIL."
