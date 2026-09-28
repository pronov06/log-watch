#!/usr/bin/env bash
set -euo pipefail

REGION=${AWS_REGION:-ap-south-1}
LG=/hackathon/log-anomaly-detector
ALERT_EMAIL=${ALERT_EMAIL:-"alerts@example.com"}

echo "Configuring AWS resources in region: $REGION"

# Create CloudWatch log group
aws logs create-log-group --log-group-name "$LG" --region "$REGION" || true
aws logs put-retention-policy --log-group-name "$LG" --retention-in-days 7 --region "$REGION"

# Create CloudWatch log stream
aws logs create-log-stream --log-group-name "$LG" --log-stream-name alerts --region "$REGION" || true
echo "CloudWatch Log Stream ready: $LG/alerts"

# Create SNS Topic
ARN=$(aws sns create-topic --name log-anomaly-alerts --region "$REGION" --query TopicArn --output text)
echo "SNS_TOPIC_ARN=$ARN"

# Create Email Subscription
aws sns subscribe --topic-arn "$ARN" --protocol email --notification-endpoint "$ALERT_EMAIL" --region "$REGION"
echo "Subscription created for: $ALERT_EMAIL (please confirm email via verification link)"
