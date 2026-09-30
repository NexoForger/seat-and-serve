# Interactive local Docker setup for S&S (Seat & Serve).
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BenchDir = (Resolve-Path (Join-Path $AppDir '../..')).Path
$ProjectDir = (Resolve-Path (Join-Path $AppDir '../../../..')).Path
$ContainerBench = '/workspace/development/frappe-bench'
$ContainerApp = "$ContainerBench/apps/table_remote_till"

function Read-Choice([string]$Prompt, [string]$Default) {
    $answer = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Read-Yes([string]$Prompt, [string]$Default = 'Y') {
    $answer = (Read-Choice $Prompt $Default).ToLowerInvariant()
    if ($answer -in @('y', 'yes')) { return $true }
    if ($answer -in @('n', 'no')) { return $false }
    throw 'Please answer yes or no.'
}

function Invoke-Compose([string[]]$CommandArgs) {
    & docker compose -p $Project -f (Join-Path $ProjectDir 'devcontainer-example/docker-compose.yml') -f (Join-Path $ProjectDir 'compose.local.yaml') @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE." }
}

function Read-Secret([string]$Prompt) {
    $secret = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

if (-not (Test-Path (Join-Path $ProjectDir 'devcontainer-example/docker-compose.yml')) -or
    -not (Test-Path (Join-Path $ProjectDir 'compose.local.yaml'))) {
    throw "This script needs the project Docker Compose files in $ProjectDir."
}
if (-not (Test-Path (Join-Path $BenchDir 'apps/frappe/frappe/hooks.py')) -or
    -not (Test-Path (Join-Path $BenchDir 'apps/erpnext/erpnext/hooks.py')) -or
    -not (Test-Path (Join-Path $BenchDir 'apps/hrms/hrms/hooks.py'))) {
    throw "Frappe, ERPNext and HRMS must already be present in $BenchDir/apps."
}

$DefaultSite = 'development.localhost'
$SitesDir = Join-Path $BenchDir 'sites'
if (Test-Path $SitesDir) {
    $firstSite = Get-ChildItem $SitesDir -Directory | Where-Object {
        Test-Path (Join-Path $_.FullName 'site_config.json')
    } | Select-Object -First 1
    if ($firstSite) { $DefaultSite = $firstSite.Name }
}
$DefaultProject = ((Split-Path $ProjectDir -Leaf).ToLowerInvariant() -replace '[^a-z0-9_-]', '')

Write-Host "`nS&S (Seat & Serve) setup`n======================="
$Project = Read-Choice 'Docker Compose project' $DefaultProject
$Site = Read-Choice 'Frappe site hostname' $DefaultSite
if ($Project -cnotmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Use a lowercase Docker project name.' }
if ($Site -cnotmatch '^[a-z0-9][a-z0-9.-]{2,120}$' -or $Site.Contains('..')) {
    throw 'Use a lowercase DNS hostname for the site.'
}

$Mode = if (Test-Path (Join-Path $SitesDir "$Site/site_config.json")) { 'existing' } else { 'new' }
if ($Mode -eq 'new') {
    Write-Host "Site $Site does not exist. It will be created with ERPNext, HRMS and S&S (Seat & Serve)."
}
$InstallJs = Read-Yes 'Install/update frontend dependencies?'
$BuildJs = Read-Yes 'Build register, kitchen, kiosk and menu assets?'
Write-Host "`nPlan: start Docker, $Mode site $Site, install missing apps, migrate."
if ($InstallJs) { Write-Host 'Frontend dependencies will be installed.' }
if ($BuildJs) { Write-Host 'Frontend assets will be built.' }
if ($DryRun) {
    Write-Host 'Dry run only. No containers, site data or files were changed.'
    return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop/Engine with Compose must be installed and running.'
}
& docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop/Engine is not running.' }
if (-not (Read-Yes 'Run this setup now?')) {
    Write-Host 'Setup cancelled.'
    return
}

$DbPassword = $null
$AdminPassword = $null
if ($Mode -eq 'new') {
    $DbPassword = Read-Secret 'MariaDB root password'
    $AdminPassword = Read-Secret 'New site Administrator password'
    if ([string]::IsNullOrEmpty($DbPassword) -or [string]::IsNullOrEmpty($AdminPassword)) {
        throw 'Both passwords are required to create a site.'
    }
}

Invoke-Compose -CommandArgs @('up', '-d')
Invoke-Compose -CommandArgs @('exec', '-T', 'frappe', 'test', '-f', "$ContainerApp/table_remote_till/hooks.py")
if ($Mode -eq 'new') {
    # The provisioner refuses to overwrite an existing site; do not print the password arguments.
    Invoke-Compose -CommandArgs @('exec', '-T', '-w', $ContainerApp,
        '-e', "TRT_DB_ROOT_PASSWORD=$DbPassword", '-e', "TRT_SITE_ADMIN_PASSWORD=$AdminPassword",
        '-e', 'TRT_DB_HOST=mariadb', 'frappe', 'python', 'tools/provision_site.py', $Site,
        '--db-host', 'mariadb')
} else {
    $installed = (Invoke-Compose -CommandArgs @('exec', '-T', '-w', $ContainerBench,
        'frappe', 'bench', '--site', $Site, 'list-apps') | Out-String)
    foreach ($app in @('erpnext', 'hrms', 'table_remote_till')) {
        if ($installed -notmatch "(?m)^s*$apps") {
            Invoke-Compose -CommandArgs @('exec', '-T', '-w', $ContainerBench,
                'frappe', 'bench', '--site', $Site, 'install-app', $app)
        }
    }
}
$DbPassword = $null
$AdminPassword = $null

if ($InstallJs) {
    foreach ($frontend in @('till', 'kitchen', 'kiosk', 'menu')) {
        Invoke-Compose -CommandArgs @('exec', '-T', '-w', "$ContainerApp/$frontend",
            'frappe', 'yarn', 'install', '--force', '--frozen-lockfile')
    }
}
if ($BuildJs) {
    Invoke-Compose -CommandArgs @('exec', '-T', '-w', $ContainerApp, 'frappe', 'yarn', 'build')
    Invoke-Compose -CommandArgs @('exec', '-T', '-w', $ContainerBench,
        'frappe', 'bench', 'build', '--app', 'table_remote_till')
}
Invoke-Compose -CommandArgs @('exec', '-T', '-w', $ContainerBench, 'frappe', 'bench', '--site', $Site, 'migrate')

Write-Host "`nSetup complete. Open http://${Site}:8000/onboarding, then /till, /kitchen or /reservations."
