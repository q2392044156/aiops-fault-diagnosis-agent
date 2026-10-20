$ErrorActionPreference = "Stop"

$base = "deployment/compose.yaml"
$framework = "deployment/compose.framework-rc2.yaml"
$legacy = "deployment/compose.legacy-rollback-verified.yaml"
$mounts = "deployment/compose.rc2-runtime-mounts.yaml"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Backup-RunningStack([string[]]$ComposeArgs, [string]$BackupName) {
  $container = & docker compose @ComposeArgs ps -q api 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $container) { return $false }
  & docker compose @ComposeArgs exec -T api python -c `
    "import pathlib,sqlite3; p=pathlib.Path('/app/runtime/backups/$BackupName'); p.parent.mkdir(parents=True,exist_ok=True); s=sqlite3.connect('/app/runtime/service.sqlite3'); d=sqlite3.connect(p); s.backup(d); assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; d.close(); s.close()"
  if ($LASTEXITCODE -ne 0) { throw "SQLite backup failed" }
  return $true
}

$frameworkArgs = @("--env-file", ".env", "-f", $base, "-f", $framework, "-f", $mounts)
$legacyArgs = @("--env-file", ".env", "-f", $base, "-f", $legacy, "-f", $mounts)
$baseArgs = @("-f", $base)
$backupName = "pre-legacy-rollback-$stamp.sqlite3"
$backedUp = (Backup-RunningStack $frameworkArgs $backupName) -or `
  (Backup-RunningStack $legacyArgs $backupName) -or `
  (Backup-RunningStack $baseArgs $backupName)
if (-not $backedUp) { throw "No running API container was found; rollback stopped before changing services." }

& docker compose @frameworkArgs down
& docker compose @baseArgs down
& docker compose @legacyArgs down
& docker compose @legacyArgs up -d --no-build
& docker compose @legacyArgs ps
