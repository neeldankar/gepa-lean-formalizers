#!/bin/sh
# Install the secret scan as pre-commit (staged changes) and pre-push (whole history) hooks.
cd "$(dirname "$0")/.." || exit 1
printf '#!/bin/sh\nexec python3 scripts/secret_scan.py\n' > .git/hooks/pre-commit
printf '#!/bin/sh\nexec python3 scripts/secret_scan.py --history\n' > .git/hooks/pre-push
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
echo "installed pre-commit and pre-push secret scan hooks"
