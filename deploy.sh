#!/bin/bash
# deploy.sh — Deploy Smart Support to Azure App Service
# Usage: chmod +x deploy.sh && ./deploy.sh

set -e  # stop if any command fails

# ── Change these if you want ──────────────────────────────────────────────────
RESOURCE_GROUP="rg-smart-support"
LOCATION="uaenorth"
APP_NAME="smart-support-app"
ACR_NAME="smartsupportacr$RANDOM"
PLAN_NAME="smart-support-plan"
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "====================================="
echo "   Smart Support — Azure Deployment"
echo "====================================="
echo ""

# Step 1 — Check login
echo "Step 1/7 — Checking Azure login..."
az account show --query name -o tsv || { echo "Not logged in. Run: az login"; exit 1; }
echo "OK"

# Step 2 — Resource group
echo ""
echo "Step 2/7 — Creating resource group..."
az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION \
  --output none
echo "OK: $RESOURCE_GROUP"

# Step 3 — Container registry
echo ""
echo "Step 3/7 — Creating container registry..."
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Basic \
  --admin-enabled true \
  --output none
echo "OK: $ACR_NAME"

# Step 4 — Build and push Docker image
echo ""
echo "Step 4/7 — Building Docker image and pushing to registry..."
az acr build \
  --registry $ACR_NAME \
  --image smart-support:latest \
  . \
  --output none
echo "OK: image pushed"

# Step 5 — App Service plan
echo ""
echo "Step 5/7 — Creating App Service plan..."
az appservice plan create \
  --name $PLAN_NAME \
  --resource-group $RESOURCE_GROUP \
  --is-linux \
  --sku B2 \
  --output none
echo "OK: $PLAN_NAME"

# Step 6 — Web App
echo ""
echo "Step 6/7 — Creating Web App..."
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query "passwords[0].value" -o tsv)
az webapp create \
  --resource-group $RESOURCE_GROUP \
  --plan $PLAN_NAME \
  --name $APP_NAME \
  --deployment-container-image-name "${ACR_NAME}.azurecr.io/smart-support:latest" \
  --docker-registry-server-user $ACR_NAME \
  --docker-registry-server-password "$ACR_PASSWORD" \
  --output none
echo "OK: $APP_NAME"

# Step 7 — Environment variables
echo ""
echo "Step 7/7 — Setting environment variables..."
source .env
az webapp config appsettings set \
  --resource-group $RESOURCE_GROUP \
  --name $APP_NAME \
  --settings \
    AZURE_AI_PROJECT_ENDPOINT="$AZURE_AI_PROJECT_ENDPOINT" \
    MODEL_DEPLOYMENT_NAME="$MODEL_DEPLOYMENT_NAME" \
    WEBSITES_PORT=8000 \
  --output none
echo "OK: env vars set"

# Done
echo ""
echo "====================================="
echo "   Deployment Complete!"
echo "====================================="
echo ""
echo "   URL: https://${APP_NAME}.azurewebsites.net"
echo ""
echo "   Note: Wait 2-3 minutes for first boot."
echo "   Check logs: az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP"
echo ""