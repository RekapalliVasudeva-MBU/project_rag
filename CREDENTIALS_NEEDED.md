# =============================================================================
# Azure Deployment Credentials Required for GitHub Actions
# =============================================================================
# Add these as **Repository Secrets** in GitHub:
# Settings → Secrets and variables → Actions → New repository secret
# =============================================================================

# ---- REQUIRED (Azure authentication via OIDC / federated identity) ----
# Create an App Registration in Azure AD, then configure federated credential
# for GitHub Actions (repo:branch:main). See: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure

AZURE_CLIENT_ID:           # Application (client) ID of the Azure AD App Registration
AZURE_TENANT_ID:           # Directory (tenant) ID of your Azure AD tenant
AZURE_SUBSCRIPTION_ID:     # Azure Subscription ID (where resources will be created)

# ---- REQUIRED (Application secrets) ----
OPENROUTER_API_KEY:        # Your OpenRouter API key (for LLM calls)
RAG_GITHUB_REPO:           # GitHub repo with PDFs (e.g., "owner/repo")
RAG_GITHUB_PATH:           # Path in repo to PDFs (e.g., "pdfs")
RAG_GITHUB_REF:            # Branch/tag/SHA to ingest from (e.g., "main")

# ---- OPTIONAL (PostgreSQL for visitor logging / waitlist) ----
RAG_PG_DSN:                # PostgreSQL connection string
                           # Format: postgresql://user:pass@host:5432/dbname
                           # If not provided, visitor logging is disabled (app still works)

# ---- OPTIONAL (Azure Monitor / Log Analytics for container logs) ----
AZURE_LOG_ANALYTICS_WORKSPACE_ID:    # Log Analytics workspace ID
AZURE_LOG_ANALYTICS_WORKSPACE_KEY:   # Log Analytics workspace primary key

# =============================================================================
# QUICK SETUP COMMANDS (run in Azure Cloud Shell or local az CLI)
# =============================================================================

# 1. Create resource group (one-time)
# az group create --name aethermind-rg --location eastus

# 2. Create Azure AD App Registration for GitHub OIDC
# az ad app create --display-name "github-actions-aethermind" --web-redirect-uris "https://github.com"
# Note the APP_ID (client-id) from output

# 3. Create Service Principal for the app
# az ad sp create --id <APP_ID>

# 4. Assign Contributor role on resource group (or subscription)
# az role assignment create --assignee <APP_ID> --role Contributor --scope /subscriptions/<SUB_ID>/resourceGroups/aethermind-rg

# 5. Configure Federated Identity Credential for GitHub Actions
# az ad app federated-credential create --id <APP_ID> --parameters '{
#   "name": "github-main",
#   "issuer": "https://token.actions.githubusercontent.com",
#   "subject": "repo:RekapalliVasudeva-MBU/project_rag:ref:refs/heads/main",
#   "audiences": ["api://AzureADTokenExchange"]
# }'

# 6. Get Tenant ID and Subscription ID
# az account show --query "{tenantId: tenantId, id: id}" -o tsv

# 7. (Optional) Create Log Analytics Workspace for container logs
# az monitor log-analytics workspace create --resource-group aethermind-rg --workspace-name aethermind-logs --location eastus
# az monitor log-analytics workspace get-shared-keys --resource-group aethermind-rg --workspace-name aethermind-logs

# =============================================================================
# COST OPTIMIZATION NOTES (per your request)
# =============================================================================
# - Container Apps: min-replicas=0 (scales to zero when idle = $0)
# - CPU: 1.0, Memory: 2Gi (enough for docling + ChromaDB, adjust if needed)
# - Max replicas: 3 (limits max concurrent cost)
# - Scale rule: 10 concurrent requests per replica
# - No GPU - uses CPU-only docling (slower ingestion, cheaper)
# - ChromaDB on ephemeral storage (free tier) - re-ingests on cold start
#   For persistent vector store: add Azure Files volume mount (extra cost)
# - Estimated monthly cost (low traffic): ~$5-15/month vs $50+ for App Service

# =============================================================================
# CUSTOM DOMAIN SETUP (for your existing GitHub Pages frontend)
# =============================================================================
# After deployment, the workflow outputs DEPLOYMENT_URL (e.g., https://aethermind-rag.xxx.eastus.azurecontainerapps.io)
# 
# In your GitHub Pages frontend (index.html), update the API base:
#   const apiBase = 'https://your-container-app-fqdn';
# 
# Or use CNAME: api.yourdomain.com → your-container-app-fqdn
# Then in Container Apps: az containerapp hostname bind --hostname api.yourdomain.com ...
# 
# CORS: server.py already allows all origins (*) - update for production if needed