#!/usr/bin/env bash
# Wait for whichever lands first: a new Greptile review, a CI failure, or green.
REPO=Morelitea/initiative
PR=1618
SEEN="${1:-0}"
START=$(date +%s)

seen_review() {
  gh api "repos/$REPO/pulls/$PR/reviews" \
    --jq '[.[] | select(.user.login|test("greptile";"i")) | .id] | max // 0'
}

while :; do
  FAILED=$(gh pr view "$PR" --json statusCheckRollup \
    -q '[.statusCheckRollup[] | select(.conclusion=="FAILURE" or .conclusion=="TIMED_OUT") | .name] | join(", ")')
  PENDING=$(gh pr view "$PR" --json statusCheckRollup \
    -q '[.statusCheckRollup[] | select(.status!="COMPLETED")] | length')
  NOW=$(seen_review)
  if [ "$NOW" != "$SEEN" ]; then echo "EVENT=greptile review=$NOW"; break; fi
  if [ -n "$FAILED" ]; then echo "EVENT=ci-failure jobs=$FAILED"; break; fi
  if [ "$PENDING" -eq 0 ]; then echo "EVENT=ci-green"; break; fi
  echo "waiting: $PENDING check(s) pending, $(($(date +%s) - START))s elapsed"
  sleep 30
done
