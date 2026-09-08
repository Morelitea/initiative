# Refuse a commit stamped with an identity other than the configured one.
#
# Git resolves the author and committer from GIT_AUTHOR_EMAIL /
# GIT_COMMITTER_EMAIL and from `git -c user.email=` ahead of any config file,
# so the identity a commit ends up with is not necessarily the configured one.
# The resolved identity is read back through `git var`.
#
# `git -c` reaches hooks as GIT_CONFIG_PARAMETERS, and GIT_CONFIG_COUNT carries
# the same kind of injected values, so the baseline is read with both cleared —
# otherwise it would shift in step with the identity it is meant to check.

configured_email=$(env -u GIT_CONFIG_PARAMETERS -u GIT_CONFIG_COUNT \
  git config --get user.email || true)

if [ -z "$configured_email" ]; then
  echo "" >&2
  echo "  Commit refused: no user.email is configured." >&2
  echo "" >&2
  echo "  Set the identity this machine commits under:" >&2
  echo "    git config --global user.email you@example.com" >&2
  echo "    git config --global user.name 'Your Name'" >&2
  echo "" >&2
  exit 1
fi

author_email=$(git var GIT_AUTHOR_IDENT | sed -e 's/.*<//' -e 's/>.*//')
committer_email=$(git var GIT_COMMITTER_IDENT | sed -e 's/.*<//' -e 's/>.*//')

for entry in "author:$author_email" "committer:$committer_email"; do
  role=${entry%%:*}
  found=${entry#*:}
  if [ "$found" != "$configured_email" ]; then
    echo "" >&2
    echo "  Commit refused: $role email is <$found>," >&2
    echo "  but the configured user.email is <$configured_email>." >&2
    echo "" >&2
    echo "  Something is overriding the git identity. Check for" >&2
    echo "  GIT_AUTHOR_EMAIL / GIT_COMMITTER_EMAIL in the environment," >&2
    echo "  or a 'git -c user.email=' on the command line." >&2
    echo "" >&2
    exit 1
  fi
done
