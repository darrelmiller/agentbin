# Spec — History

## 2026-03-21 — Initial onboarding

- Server hosts 3 agents: /spec (SpecAgent), /echo (EchoAgent), /spec03 (v0.3 compat)
- Uses A2A NuGet 1.0.0-preview packages from local nupkgs/ folder
- BASE_URL auto-detection fixed: checks builder.Configuration["urls"] and ASPNETCORE_URLS
- Agent cards serialize with v0.3-compatible shape despite using v1.0 SupportedInterfaces
- return-immediately (Blocking=false) not implemented on server
- subscribe-to-task has "internal error during streaming" bug
- Deployed to Azure Container Apps

## Learnings

### 2026-03-21: Deployment ownership established
- Deployment to Azure Container Apps is now my responsibility
- ACR: agentbinacr, Resource Group: agentbin-rg, Subscription: Visual Studio Enterprise
- Deploy: `az acr build` then `az containerapp update`
- Post-deploy: run smoke tests (`python tests/smoke-test.py`)
- Cost: ~$5-6/month (ACR Basic + scale-to-zero Container App)
