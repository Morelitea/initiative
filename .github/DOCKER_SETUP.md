# Docker Hub Setup Instructions

This document explains how to configure Docker Hub deployment for the Initiative project.

## Prerequisites

1. A Docker Hub account
2. Repository admin access on GitHub
3. The project must have semantic version tags (e.g., `v0.1.0`)

## Step 1: Create Docker Hub Access Token

1. Log in to [Docker Hub](https://hub.docker.com)
2. Go to **Account Settings** → **Security** → **New Access Token**
3. Create a token with name: `github-actions`
4. Set permissions: **Read & Write**
5. Copy the token (you won't be able to see it again)

## Step 2: Configure GitHub Secrets

**IMPORTANT**: These secrets are required for the workflow to run. The build will fail with a clear error if they are not configured.

1. Go to your GitHub repository
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add the following secrets:

   | Name | Value | Description |
   |------|-------|-------------|
   | `DOCKERHUB_USERNAME` | Your Docker Hub username | Used to log in to Docker Hub |
   | `DOCKERHUB_TOKEN` | The access token from Step 1 | Used for authentication |

**Note**: Until these secrets are configured, version tags will trigger the workflow but it will fail early with an error message directing you to this documentation.

## Step 3: Verify Setup

The workflow will automatically trigger when you push a version tag:

```bash
# Bump version (creates tag)
./scripts/bump-version.sh

# Push tag to trigger workflow
git push && git push --tags
```

You can monitor the build progress at:
- GitHub: **Actions** tab in your repository
- Docker Hub: Your repository's **Tags** page

## Docker Image Tags

The workflow creates multiple tags for each release:

- `latest` - Always points to the most recent release
- `1` - Major version (e.g., all v1.x.x releases)
- `1.2` - Major + minor version (e.g., all v1.2.x releases)
- `1.2.3` - Exact version (e.g., v1.2.3 only)

Example:
```bash
# After pushing v1.2.3, these tags are created:
docker pull username/initiative:latest
docker pull username/initiative:1
docker pull username/initiative:1.2
docker pull username/initiative:1.2.3
```

## Manual Trigger

You can also manually trigger a build without creating a tag:

1. Go to **Actions** → **Build and Push Docker Image**
2. Click **Run workflow**
3. Optionally specify a custom tag (default: `latest`)

## Multi-Architecture Support

The workflow builds images for both:
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM, Apple Silicon)

This ensures compatibility across different platforms.

## Using the Docker Image

Once published, pull and run the image:

```bash
# Pull the latest version
docker pull morelitea/initiative:latest

# Or pull a specific version
docker pull morelitea/initiative:0.1.1
```

### Quick Start with Docker Compose

The easiest way to run Initiative is using the provided docker-compose configuration:

```bash
# Copy the example compose file
cp docker-compose.example.yml docker-compose.yml

# Start the application
docker-compose up -d

# View logs
docker-compose logs -f initiative
```

The example configuration includes:
- PostgreSQL 17 database
- Initiative application (latest version from Docker Hub)
- Automatic health checks and restart policies
- Volume mounting for persistent uploads
- Sensible defaults for quick setup

**Important**: Update the `SECRET_KEY` in docker-compose.yml for production use!

### Custom Configuration

Edit docker-compose.yml to customize:
- Database credentials
- Port mappings
- OIDC authentication settings
- API token expiration
- Application URL

## Troubleshooting

### Build Fails: "failed to solve: failed to compute cache key"

This usually means the Dockerfile references files that don't exist. Ensure all `COPY` commands point to valid paths.

### Build Fails: "Error: buildx failed"

Check the GitHub Actions logs for specific error messages. Common issues:
- Missing secrets (DOCKERHUB_USERNAME or DOCKERHUB_TOKEN)
- Invalid Dockerfile syntax
- Network issues (retry the workflow)

### Image Not Appearing on Docker Hub

1. Verify secrets are set correctly
2. Check that your Docker Hub username matches the secret
3. Ensure the repository exists on Docker Hub (it will be created automatically on first push)

### Permission Denied

Ensure your Docker Hub token has **Read & Write** permissions, not just **Read**.

## Security Notes

- Never commit Docker Hub tokens to the repository
- Rotate access tokens regularly (recommended: every 90 days)
- Use repository-specific secrets, not organization-wide secrets
- Consider using Docker Hub's team/organization features for better access control
