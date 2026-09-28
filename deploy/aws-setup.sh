#!/usr/bin/env bash
# One-time AWS setup for the xue-study evidence backup.
#
# Run this WHERE YOU HAVE CREDENTIALS (your laptop / CloudShell / console CLI) --
# NOT on the instance, which has no IAM role and therefore no credentials at all
# (verified 2026-09-28: `aws sts get-caller-identity` -> NoCredentials).
#
# Facts this was written against:
#   account   459231717818
#   region    us-east-1
#   instance  i-0d8bd578ba734b444   (t3.large, AZ us-east-1d)
#   to back up: ~/xue-study/archive/multivariate-l12-v1/*.npz   112 MB  (frozen/)
#               ~/climatetensor-inputs/ncep-multivariate        2.4 GB  (inputs/)
#               ~/climatetensor-inputs/ncep-multivariate-ext-202602  246 MB (inputs/)
#
# WHY THE INPUTS MATTER MORE THAN THE FROZEN NPZ: PSL updates its NetCDF files IN PLACE.
# Once upstream replaces a vintage, that vintage is gone forever -- we kept only its
# source_sha256, which proves which vintage we used but cannot bring it back. The frozen
# npz, by contrast, can be recomputed from those inputs (E1b's G2 reproduced the
# projection array-for-array).
#
# Two ways to run this. Pick ONE.
#
#   (A) ROLE_PATH=1  ./aws-setup.sh     <- recommended: the instance gets an IAM role,
#                                           so NO long-lived key ever lands on the box.
#   (B) KEY_PATH=1   ./aws-setup.sh     <- fastest: prints a scoped access key you paste
#                                           into the instance. A long-lived secret then
#                                           lives on that disk (chmod 600).
#
# Both create: the bucket (versioned, encrypted, public access blocked, ACLs disabled),
# upload of this runbook's SHA256 manifest happens later from the instance.
#
# Nothing here is destructive. It creates, and never deletes, anything.
set -euo pipefail

ACCOUNT=459231717818
REGION=us-east-1
INSTANCE=i-0d8bd578ba734b444
BUCKET="${BUCKET:-xue-study-evidence-${ACCOUNT}-${REGION}}"
ROLE_NAME="${ROLE_NAME:-xue-study-evidence-backup}"
PROFILE_NAME="${PROFILE_NAME:-xue-study-evidence-backup}"
KEY_USER="${KEY_USER:-xue-study-backup}"

echo "bucket = $BUCKET   region = $REGION   instance = $INSTANCE"
echo

# ---------------------------------------------------------------- the bucket
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "[bucket] already exists, leaving it alone"
else
  echo "[bucket] creating"
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null

  # Versioning: an overwritten or deleted object stays recoverable. This is the
  # object-storage form of the project's append-only discipline for evidence.
  aws s3api put-bucket-versioning --bucket "$BUCKET" \
      --versioning-configuration Status=Enabled

  # Default encryption at rest, and no public access, ever.
  aws s3api put-bucket-encryption --bucket "$BUCKET" \
      --server-side-encryption-configuration \
      '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
  aws s3api put-public-access-block --bucket "$BUCKET" \
      --public-access-block-configuration \
      'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
  aws s3api put-bucket-ownership-controls --bucket "$BUCKET" \
      --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'
fi

cat > /tmp/xue-evidence-policy.json <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListThisBucketOnly",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"],
      "Resource": "arn:aws:s3:::${BUCKET}"
    },
    {
      "Sid": "ReadWriteObjectsUnderThisBucketOnly",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject", "s3:GetObject", "s3:DeleteObject",
        "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
      ],
      "Resource": "arn:aws:s3:::${BUCKET}/*"
    }
  ]
}
POLICY

if [ "${ROLE_PATH:-0}" = "1" ]; then
  echo
  echo "[role] creating $ROLE_NAME"
  cat > /tmp/xue-trust.json <<'TRUST'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
TRUST
  aws iam create-role --role-name "$ROLE_NAME" \
      --assume-role-policy-document file:///tmp/xue-trust.json >/dev/null 2>&1 \
    || echo "[role] already exists"
  aws iam put-role-policy --role-name "$ROLE_NAME" \
      --policy-name xue-evidence-backup --policy-document file:///tmp/xue-evidence-policy.json
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1 \
    || echo "[profile] already exists"
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" \
      --role-name "$ROLE_NAME" >/dev/null 2>&1 || true
  echo "[profile] attaching to $INSTANCE (may need a few seconds after creation)"
  sleep 10
  aws ec2 associate-iam-instance-profile --instance-id "$INSTANCE" \
      --iam-instance-profile Name="$PROFILE_NAME" >/dev/null
  echo
  echo "DONE. On the instance, verify with:"
  echo "  ~/bin/aws sts get-caller-identity"
  echo "  ~/bin/aws s3 ls s3://$BUCKET/"
fi

if [ "${KEY_PATH:-0}" = "1" ]; then
  echo
  echo "[key] creating an IAM user scoped to this bucket only"
  aws iam create-user --user-name "$KEY_USER" >/dev/null 2>&1 || echo "[key] user exists"
  aws iam put-user-policy --user-name "$KEY_USER" \
      --policy-name xue-evidence-backup --policy-document file:///tmp/xue-evidence-policy.json
  echo
  echo "Access key (shown ONCE -- paste it on the instance):"
  aws iam create-access-key --user-name "$KEY_USER"
fi

echo
echo "bucket ready: s3://$BUCKET/frozen/  and  s3://$BUCKET/inputs/"
echo "next, on the instance:"
echo "  cd ~/xue-study && python3 scripts/backup_to_s3.py plan"
echo "  ~/bin/python-that-has-sha256 scripts/backup_to_s3.py sync --bucket $BUCKET"
