# Refuse a commit stamped with an identity other than the configured one.
#
# Environment variables (GIT_AUTHOR_EMAIL, GIT_COMMITTER_EMAIL) and `git -c`
# take precedence over every config file, so this reads the identity git has
# actually resolved for the commit rather than the config value.

configured_email=$(git config --get user.email || true)

if [ -n "$configured_email" ]; then
  author_email=$(git var GIT_AUTHOR_IDENT | sed -e 's/.*<//' -e 's/>.*//')
  committer_email=$(git var GIT_COMMITTER_IDENT | sed -e 's/.*<//' -e 's/>.*//')

  for entry in "author:$author_email" "committer:$committer_email"; do
    role=${entry%%:*}
    found=${entry#*:}
    if [ "$found" != "$configured_email" ]; then
      echo "" >&2
      echo "  Commit refused: $role email is <$found>," >&2
      echo "  but git config user.email is <$configured_email>." >&2
      echo "" >&2
      echo "  Something is overriding the git identity. Clear it with:" >&2
      echo "    unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL" >&2
      echo "" >&2
      exit 1
    fi
  done
fi
