param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,

    [Parameter(Mandatory = $false)]
    [string]$ChangelogFile = "changelog.md"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -Path $ChangelogFile -PathType Leaf)) {
    Write-Error "Changelog file not found: $ChangelogFile"
    exit 1
}

$lines = Get-Content -Path $ChangelogFile -Raw -ErrorAction Stop -Encoding UTF8
$pattern = "^##\s+" + [regex]::Escape($Tag) + "(?:\s|$)"
$linesArray = $lines -split "\r?\n"
$startIndex = -1
for ($i = 0; $i -lt $linesArray.Length; $i++) {
    if ($linesArray[$i] -match $pattern) {
        $startIndex = $i
        break
    }
}

if ($startIndex -lt 0) {
    Write-Error "No changelog entry found for tag: $Tag"
    exit 1
}

$releaseLines = @()
for ($i = $startIndex; $i -lt $linesArray.Length; $i++) {
    $line = $linesArray[$i]
    if ($i -gt $startIndex -and $line -match '^##\s+') {
        break
    }
    $releaseLines += $line
}

$releaseBody = ($releaseLines -join "`n").Trim()
if ([string]::IsNullOrWhiteSpace($releaseBody)) {
    Write-Error "Extracted release notes are empty for tag: $Tag"
    exit 1
}

if ($env:GITHUB_REPOSITORY) {
    $repo = $env:GITHUB_REPOSITORY
} else {
    $repoJson = gh repo view --json name,owner
    $repoData = $repoJson | ConvertFrom-Json
    $repo = "$($repoData.owner.login)/$($repoData.name)"
}

$releaseId = $null
try {
    $releaseId = gh api "/repos/$repo/releases/tags/$Tag" --jq '.id' 2>$null
} catch {
    # Release may not exist yet.
}

$isPrerelease = $Tag -like '*-*'

if ([string]::IsNullOrWhiteSpace($releaseId)) {
    Write-Host "Creating release for $Tag"
    gh api --method POST "/repos/$repo/releases" --field "tag_name=$Tag" --field "name=$Tag" --field "body=$releaseBody" --field "draft=false" --field "prerelease=$isPrerelease"
} else {
    Write-Host "Updating release for $Tag (release id $releaseId)"
    gh api --method PATCH "/repos/$repo/releases/$releaseId" --field "body=$releaseBody"
}

Write-Host "Release notes extracted from $ChangelogFile and applied to GitHub release $Tag."
