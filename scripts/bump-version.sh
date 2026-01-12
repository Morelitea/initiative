#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get current version
if [ ! -f VERSION ]; then
    echo -e "${RED}ERROR: VERSION file not found${NC}"
    exit 1
fi

CURRENT=$(cat VERSION)
echo -e "${GREEN}Current version: ${CURRENT}${NC}"

# Parse current version
IFS='.' read -r -a VERSION_PARTS <<< "$CURRENT"
MAJOR="${VERSION_PARTS[0]}"
MINOR="${VERSION_PARTS[1]}"
PATCH="${VERSION_PARTS[2]}"

# Show bump options
echo ""
echo "Select version bump type:"
echo "  1) Patch  (${MAJOR}.${MINOR}.$((PATCH + 1))) - Bug fixes"
echo "  2) Minor  (${MAJOR}.$((MINOR + 1)).0) - New features, backward-compatible"
echo "  3) Major  ($((MAJOR + 1)).0.0) - Breaking changes"
echo "  4) Custom - Enter version manually"
echo ""
read -p "Choice [1-4]: " CHOICE

case $CHOICE in
    1)
        NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
        ;;
    2)
        NEW_VERSION="${MAJOR}.$((MINOR + 1)).0"
        ;;
    3)
        NEW_VERSION="$((MAJOR + 1)).0.0"
        ;;
    4)
        read -p "Enter new version (e.g., 1.2.3): " NEW_VERSION
        # Validate format
        if ! [[ $NEW_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo -e "${RED}ERROR: Invalid version format. Use X.Y.Z${NC}"
            exit 1
        fi
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${YELLOW}Bumping version: ${CURRENT} → ${NEW_VERSION}${NC}"
read -p "Continue? [y/N]: " CONFIRM

if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    echo "Aborted"
    exit 0
fi

# Update VERSION file
echo "$NEW_VERSION" > VERSION

# Check if CHANGELOG.md has been updated
CHANGELOG_UPDATED=false
if [ -f CHANGELOG.md ]; then
    if git diff --quiet CHANGELOG.md; then
        echo -e "${YELLOW}Warning: CHANGELOG.md has no changes${NC}"
        read -p "Continue without changelog update? [y/N]: " SKIP_CHANGELOG
        if [[ ! $SKIP_CHANGELOG =~ ^[Yy]$ ]]; then
            echo "Aborted. Please update CHANGELOG.md first."
            git checkout VERSION
            exit 1
        fi
    else
        CHANGELOG_UPDATED=true
    fi
fi

# Commit and tag
git add VERSION
if [ "$CHANGELOG_UPDATED" = true ]; then
    git add CHANGELOG.md
fi
git commit -m "bump version to ${NEW_VERSION}"
git tag "v${NEW_VERSION}"

echo ""
echo -e "${GREEN}✓ Version bumped to ${NEW_VERSION}${NC}"
if [ "$CHANGELOG_UPDATED" = true ]; then
    echo -e "${GREEN}✓ Commit created (VERSION + CHANGELOG.md)${NC}"
else
    echo -e "${GREEN}✓ Commit created (VERSION only)${NC}"
fi
echo -e "${GREEN}✓ Tag v${NEW_VERSION} created${NC}"
echo ""
echo "Push changes with:"
echo -e "  ${YELLOW}git push && git push --tags${NC}"
