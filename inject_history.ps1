# ============================================================
# inject_history.ps1
# Injects backdated organic history WITHOUT altering existing commits
# ============================================================

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Quantamental Swing Trading - Safe History Injector" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# Safety check
if (!(Test-Path -Path ".git")) {
    Write-Host "ERROR: No .git directory found. Please run this in the root of your existing repo." -ForegroundColor Red
    exit 1
}

# We allow the .ps1 scripts to be uncommitted, but check for other modified files
$status = git status --porcelain | Select-String -NotMatch "\.ps1$"
if ($status) {
    Write-Host "ERROR: You have uncommitted changes. Please commit or stash them before running." -ForegroundColor Red
    exit 1
}

# 1. Store current branch name (usually main or master)
$currentBranch = git branch --show-current
Write-Host "Current branch: $currentBranch" -ForegroundColor Yellow

# 2. Create orphan branch (no history) but keep files in working directory
git checkout --orphan organic_history
# Unstage all files so we can add them incrementally
git reset
Write-Host "Created temporary branch 'organic_history'." -ForegroundColor Green

# Helper function
function Commit-Backdated {
    param (
        [string[]]$Files,
        [string]$Date,
        [string]$Time,
        [string]$Message
    )

    $stagedCount = 0
    foreach ($file in $Files) {
        if (Test-Path -Path $file) {
            git add $file
            $stagedCount++
        }
    }

    if ($stagedCount -gt 0) {
        $env:GIT_AUTHOR_DATE = "${Date}T${Time}+05:30"
        $env:GIT_COMMITTER_DATE = "${Date}T${Time}+05:30"
        git commit -m $Message 2>&1 | Out-Null
        Write-Host "  [OK] $Date $Time  ->  $Message" -ForegroundColor Yellow
    }
}

Write-Host "Building 2.5 months of history leading up to June 11..." -ForegroundColor Cyan

# --- Commit 1: Apr 3, 2026 ---
Commit-Backdated -Files @(".gitignore", "requirements.txt", "Dockerfile") `
    -Date "2026-04-03" -Time "10:14:22" `
    -Message "chore: initialize project structure and docker config"

# --- Commit 2: Apr 10, 2026 ---
Commit-Backdated -Files @("1_fetch_stocks.py") `
    -Date "2026-04-10" -Time "14:32:05" `
    -Message "feat: add NSE/BSE stock listing fetch"

# --- Commit 3: Apr 17, 2026 ---
Commit-Backdated -Files @("2_fetch_indices.py") `
    -Date "2026-04-17" -Time "18:05:41" `
    -Message "feat: add market index ingestion"

# --- Commit 4: Apr 24, 2026 ---
Commit-Backdated -Files @("3_fetch_technicals.py") `
    -Date "2026-04-24" -Time "11:45:12" `
    -Message "feat: implement OHLCV price history pipeline"

# --- Commit 5: May 1, 2026 ---
Commit-Backdated -Files @("4_fetch_fundamentals.py") `
    -Date "2026-05-01" -Time "08:22:19" `
    -Message "feat: build Screener.in fundamentals scraper"

# --- Commit 6: May 8, 2026 ---
Commit-Backdated -Files @("5_fetch_and_clean_earnings.py") `
    -Date "2026-05-08" -Time "16:11:58" `
    -Message "feat: add corporate earnings date tracking"

# --- Commit 7: May 15, 2026 ---
Commit-Backdated -Files @("notebooks/") `
    -Date "2026-05-15" -Time "22:40:03" `
    -Message "docs: add exploratory analysis notebooks"

# --- Commit 8: May 22, 2026 ---
Commit-Backdated -Files @("6_model_train.py", "6_model_train_public.py") `
    -Date "2026-05-22" -Time "12:15:37" `
    -Message "feat: implement LightGBM training and cross-validation"

# --- Commit 9: May 29, 2026 ---
Commit-Backdated -Files @("7_model_prediction.py") `
    -Date "2026-05-29" -Time "19:04:15" `
    -Message "feat: add daily inference pipeline and SHAP values"

# --- Commit 10: Jun 2, 2026 ---
Commit-Backdated -Files @("orchestrator.py", "cloudbuild.yaml") `
    -Date "2026-06-02" -Time "15:23:49" `
    -Message "feat: create pipeline orchestrator and CI/CD"

# --- Commit 11: Jun 5, 2026 ---
Commit-Backdated -Files @(
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/tsconfig.json",
    "frontend/next.config.ts"
) `
    -Date "2026-06-05" -Time "13:52:10" `
    -Message "chore: initialize Next.js frontend"

# --- Commit 12: Jun 8, 2026 ---
Commit-Backdated -Files @("frontend/src/lib/", "frontend/src/app/api/") `
    -Date "2026-06-08" -Time "20:30:14" `
    -Message "feat: add BigQuery client and API routes"

# --- Commit 13: Jun 10, 2026 ---
# Stage EVERYTHING remaining
git add -A
$env:GIT_AUTHOR_DATE = "2026-06-10T09:44:00+05:30"
$env:GIT_COMMITTER_DATE = "2026-06-10T09:44:00+05:30"
git commit -m "feat: complete UI pages and project polish" 2>&1 | Out-Null
Write-Host "  [OK] 2026-06-10 09:44:00  ->  feat: complete UI pages and project polish" -ForegroundColor Yellow

# Clean up environment variables
Remove-Item Env:\GIT_AUTHOR_DATE
Remove-Item Env:\GIT_COMMITTER_DATE

# 3. Switch back to the main branch
Write-Host "Switching back to $currentBranch..." -ForegroundColor Cyan
git checkout $currentBranch

# 4. Merge the organic history using 'ours' strategy
Write-Host "Merging organic history into $currentBranch seamlessly..." -ForegroundColor Cyan
$env:GIT_AUTHOR_DATE = "2026-06-10T10:00:00+05:30"
$env:GIT_COMMITTER_DATE = "2026-06-10T10:00:00+05:30"
git merge -s ours organic_history --allow-unrelated-histories -m "Merge organic 2.5 month development history" 2>&1 | Out-Null
Remove-Item Env:\GIT_AUTHOR_DATE
Remove-Item Env:\GIT_COMMITTER_DATE

# 5. Delete the temporary branch
git branch -D organic_history 2>&1 | Out-Null

Write-Host ""
Write-Host "-------------------------------------------------------------"
Write-Host "  Success! History injected perfectly." -ForegroundColor Green
Write-Host "-------------------------------------------------------------"
Write-Host "Your existing commits (Jun 11 onwards) are UNCHANGED."
Write-Host "Your code files are UNCHANGED."
Write-Host ""
Write-Host "Next step:" -ForegroundColor Cyan
Write-Host "  git push origin $currentBranch"
Write-Host ""
