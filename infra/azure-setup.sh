#!/usr/bin/env bash
# One-time Azure setup for Float (Assignment 2 §7, the Blackboard setup guide, plan.md §11).
# After this, only the CD pipeline changes anything. Run in bash (zsh mangles "repo:$X:ref"),
# after `az login`. Passwords are read from the environment, never written in this file:
#   PERSONAL_DB_PASSWORD, HOUSEHOLDS_DB_PASSWORD, SQL_ADMIN_PASSWORD, REGION (one of your five allowed).
set -euo pipefail

PREFIX="sgealbilleh-ieu2024"
RG="rg-${PREFIX}"
UI_STORAGE="sgealbillehieu2024ui"
SQL_SERVER="${PREFIX}-sql"
ENV_NAME="${PREFIX}-env"
IDENTITY="${PREFIX}-github"
GH_REPO="Sanad-AlBilleh/Float"
: "${REGION:?set REGION to one of your allowed regions (see step 1)}"

# 1. Subscription and the regions this subscription allows.
az account set --subscription "Azure for Students"
az policy assignment list --query "[?displayName=='Allowed resource deployment regions'].parameters" -o json

# 2. Providers and the resource group.
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register --namespace "${ns}" --wait
done
az group create --name "${RG}" --location "${REGION}"

# 3. The UI: a Storage static website. Its web endpoint is the public URL and the only CORS origin.
az storage account create --name "${UI_STORAGE}" --resource-group "${RG}" --location "${REGION}" \
  --kind StorageV2 --sku Standard_LRS --allow-blob-public-access false
az storage blob service-properties update --account-name "${UI_STORAGE}" --static-website \
  --index-document index.html --auth-mode login
az storage account show --name "${UI_STORAGE}" --resource-group "${RG}" --query "primaryEndpoints.web" -o tsv

# 4. One SQL server, two serverless databases on the free offer (no --auto-pause-delay / --max-size).
az sql server create --name "${SQL_SERVER}" --resource-group "${RG}" --location "${REGION}" \
  --admin-user floatadmin --admin-password "${SQL_ADMIN_PASSWORD:?}"
az sql server firewall-rule create --server "${SQL_SERVER}" --resource-group "${RG}" \
  --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
for svc in personal households; do
  az sql db create --server "${SQL_SERVER}" --resource-group "${RG}" --name "${PREFIX}-${svc}-db" \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --min-capacity 0.5 --capacity 1 \
    --backup-storage-redundancy Local --use-free-limit true --free-limit-exhaustion-behavior AutoPause
done
# Contained users, one per database, only in their own database (open the firewall to your IP first,
# and delete that rule afterwards):
#   sqlcmd -S "${SQL_SERVER}.database.windows.net" -d "${PREFIX}-personal-db" -U floatadmin -C -Q \
#     "CREATE USER personal_svc WITH PASSWORD = '<PERSONAL_DB_PASSWORD>';
#      ALTER ROLE db_ddladmin ADD MEMBER personal_svc; ALTER ROLE db_datareader ADD MEMBER personal_svc;
#      ALTER ROLE db_datawriter ADD MEMBER personal_svc;"
#   (the same for households_svc in "${PREFIX}-households-db")

# 5. Container Apps: one environment, one app per service, 0..1 replicas, placeholder image.
#    CORS is done in the services' code, not with `az containerapp ingress cors`.
az containerapp env create --name "${ENV_NAME}" --resource-group "${RG}" --location "${REGION}"
for svc in personal households; do
  az containerapp create --name "${PREFIX}-${svc}" --resource-group "${RG}" --environment "${ENV_NAME}" \
    --image mcr.microsoft.com/k8se/quickstart:latest --ingress external --target-port 8000 \
    --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi
done

# 6. The pipeline's identity: Contributor on this resource group only, trusted only for main via OIDC.
az identity create --name "${IDENTITY}" --resource-group "${RG}" --location "${REGION}"
PRINCIPAL_ID="$(az identity show --name "${IDENTITY}" --resource-group "${RG}" --query principalId -o tsv)"
RG_ID="$(az group show --name "${RG}" --query id -o tsv)"
az role assignment create --assignee-object-id "${PRINCIPAL_ID}" --assignee-principal-type ServicePrincipal \
  --role Contributor --scope "${RG_ID}"
az identity federated-credential create --name github-main --identity-name "${IDENTITY}" --resource-group "${RG}" \
  --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange \
  --subject "repo:${GH_REPO}:ref:refs/heads/main"

# 7. GitHub secrets and variables (values from the commands above; passwords from the environment).
gh secret set AZURE_CLIENT_ID --repo "${GH_REPO}" --body "$(az identity show --name "${IDENTITY}" --resource-group "${RG}" --query clientId -o tsv)"
gh secret set AZURE_TENANT_ID --repo "${GH_REPO}" --body "$(az account show --query tenantId -o tsv)"
gh secret set AZURE_SUBSCRIPTION_ID --repo "${GH_REPO}" --body "$(az account show --query id -o tsv)"
gh secret set PERSONAL_DB_PASSWORD --repo "${GH_REPO}" --body "${PERSONAL_DB_PASSWORD:?}"
gh secret set HOUSEHOLDS_DB_PASSWORD --repo "${GH_REPO}" --body "${HOUSEHOLDS_DB_PASSWORD:?}"
gh secret set TOKEN_SECRET --repo "${GH_REPO}" --body "$(openssl rand -hex 32)"
gh secret set INTERNAL_API_KEY --repo "${GH_REPO}" --body "$(openssl rand -hex 32)"
gh variable set PREFIX --repo "${GH_REPO}" --body "${PREFIX}"
gh variable set RESOURCE_GROUP --repo "${GH_REPO}" --body "${RG}"
gh variable set UI_STORAGE --repo "${GH_REPO}" --body "${UI_STORAGE}"
gh variable set SQL_SERVER --repo "${GH_REPO}" --body "${SQL_SERVER}"

# 8. Reader for the professors (run only after confirming):
#   az role assignment create --assignee amartini@faculty.ie.edu --role Reader --scope "${RG_ID}"
#   az role assignment create --assignee bserra@faculty.ie.edu --role Reader --scope "${RG_ID}"
