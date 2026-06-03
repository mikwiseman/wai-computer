# Azure Trusted Signing — bring-up guide

Microsoft's managed code-signing service. Replaces EV USB tokens for
~$10/month and signs `WaiComputer-Setup.exe` so Windows SmartScreen shows
"Verified publisher: WaiWai" on first run.

## One-time setup (~3–5 business days for cert issuance)

### 1. Azure subscription + tenant

You need an Azure subscription. If WaiWai already has one, use it. Otherwise
create a free trial at <https://azure.microsoft.com>.

Capture for later:
- **Tenant ID** (Entra → Properties → Tenant ID)
- **Subscription ID** (Subscriptions → your subscription)

### 2. Create a Trusted Signing account

Azure portal → **Trusted Signing Accounts** → **+ Create**:

| Field | Value |
|---|---|
| Subscription | (your sub) |
| Resource group | `rg-waicomputer-signing` (create new) |
| Region | Choose the closest supported region |
| Account name | Choose a private account name |
| SKU | **Basic** (~$9.99/mo, includes 5,000 signatures) |

Wait for deployment (~2 min).

### 3. Identity validation

Inside the Trusted Signing account → **Identity Validation** → **+ New**:

| Field | Value |
|---|---|
| Type | Private (your organisation) |
| Organisation name | Your publisher organisation name |
| Address | Your business address |
| Website | https://wai.computer |
| Email | hi@mikwiseman.com |

Submit → wait **3–5 business days** for Microsoft to verify. You'll get an
email when approved. Until then, signing won't work — but the unsigned
build path in `windows-release.yml` still produces a usable artifact for
internal testing.

### 4. Create a certificate profile

After identity validation completes, Trusted Signing account → **Certificate
Profiles** → **+ Create**:

| Field | Value |
|---|---|
| Profile name | Choose a private profile name |
| Type | Public Trust |
| Identity validation | (the one you created in step 3) |

Capture:
- **Endpoint** (top of profile page, looks like `https://weu.codesigning.azure.net/`)
- **Account name**
- **Profile name**

### 5. Federated identity for GitHub Actions

So the CI workflow can sign without storing long-lived secrets:

Azure portal → **App registrations** → **+ New registration**:
- Name: choose a private app registration name
- Supported account types: Single tenant
- Redirect URI: (leave blank)

After creation → the app → **Certificates & secrets** → **Federated
credentials** → **+ Add**:
- Federated credential scenario: GitHub Actions deploying Azure resources
- Organization: your GitHub owner
- Repository: your repository
- Entity type: Branch
- Branch name: `main` (and add a second for `windows-*` tags if you tag-trigger)
- Audience: `api://AzureADTokenExchange` (default)

Now grant the app the **Trusted Signing Certificate Profile Signer** role:
Trusted Signing account → **Access control (IAM)** → **+ Add role
assignment** → role `Trusted Signing Certificate Profile Signer` →
assign to the GitHub signing service principal.

Capture:
- **Application (client) ID** of the app registration

## Set GitHub secrets

```
gh secret set AZURE_TENANT_ID --body "<tenant-id>"
gh secret set AZURE_CLIENT_ID --body "<application-client-id>"
gh secret set AZURE_TRUSTED_SIGNING_ENDPOINT --body "<trusted-signing-endpoint>"
gh secret set AZURE_TRUSTED_SIGNING_ACCOUNT --body "<trusted-signing-account>"
gh secret set AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE --body "<certificate-profile>"

# Release upload
gh secret set VPS_SSH_PRIVATE_KEY < /path/to/release-upload-key
gh secret set VPS_HOST --body "<release-host>"
gh secret set VPS_USER --body "<release-user>"
gh secret set WINDOWS_RELEASE_REMOTE_ROOT --body "<remote-release-directory>"
```

## Make a signed release

GitHub UI → Actions → `windows-release` → **Run workflow**:
- Version: e.g. `1.0.0`
- Channel: `beta` first (validate end-to-end), then `stable`

The workflow:
1. Builds + tests + publishes
2. Signs with Trusted Signing via federated OIDC (no stored cert keys)
3. Runs `signtool verify /pa` to assert the signature is valid
4. Packs Velopack `WaiComputer-Setup.exe` + delta `.nupkg`
5. Uploads to `wai.computer/releases/windows/` over SSH
6. Tags the commit `windows-<version>-<channel>`

Once the file is at `/releases/windows/WaiComputer-Setup.exe`, flip
`WINDOWS_AVAILABLE` to `true` in `web/src/app/page.tsx` and the homepage
button activates on next deploy.

## Local fallback

If you need a quick beta build before Azure approves identity validation,
run `.\scripts\release-windows.ps1 beta` from a Win VM. With no
`WAI_AZURE_TRUSTED_SIGNING_*` env vars set, it builds **unsigned** and
uploads anyway — useful for internal testers (they'll see the SmartScreen
"unknown publisher" warning, but the binary works).

## Verifying a signed build

```powershell
signtool verify /pa "Releases\WaiComputer-1.0.0-win-Setup.exe"
```

Expected output:
```
File: Releases\WaiComputer-1.0.0-win-Setup.exe
Index  Algorithm  Timestamp
========================================
0      sha256     RFC3161
Successfully verified: Releases\WaiComputer-1.0.0-win-Setup.exe
```

The certificate chain must show `Microsoft ID Verified CS EOC CA 01` →
`Microsoft Identity Verification Root Certificate Authority 2020` and the
publisher CN must be `WaiWai`.
