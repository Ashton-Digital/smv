function Select-ReleaseVersion {
    param([string]$RepoRoot, [string]$Version)

    $CMakePath = Join-Path $RepoRoot "CMakeLists.txt"
    $GuidePath = Join-Path $RepoRoot "Build/ASHTON_INTERNAL_RELEASE.md"
    $CMakeContents = Get-Content -LiteralPath $CMakePath -Raw
    $GuideContents = Get-Content -LiteralPath $GuidePath -Raw
    $UpstreamVersion = [regex]::Match($CMakeContents, 'project\(smv .*VERSION ([0-9]+\.[0-9]+\.[0-9]+)').Groups[1].Value
    $ReleaseMatch = [regex]::Match($CMakeContents, 'set\(ASHTON_RELEASE\s+"([^"]+)"\)')
    $GuideMatch = [regex]::Match($GuideContents, 'The current build is `([^`]+)`;')
    if (-not $UpstreamVersion -or -not $ReleaseMatch.Success -or -not $GuideMatch.Success) {
        throw "Could not determine the current release from CMakeLists.txt and the release guide."
    }
    $OldRelease = $ReleaseMatch.Groups[1].Value
    $OldVersion = "$UpstreamVersion-$OldRelease"
    $DocumentedVersion = $GuideMatch.Groups[1].Value

    if (-not $Version) {
        $Parts = [regex]::Match($OldRelease, '^af(?<major>[0-9]+)(?:\.(?<minor>[0-9]+)\.(?<patch>[0-9]+))?(?:-rc(?<candidate>[0-9]+))?$')
        if (-not $Parts.Success) {
            throw "Cannot increment $OldRelease automatically. Pass -Version explicitly."
        }
        $Base = $OldRelease -replace '-rc[0-9]+$', ''
        if (-not $Parts.Groups['minor'].Success) {
            # Migrate the older afN / afN-rcN scheme to the chosen afN.1.0 line.
            $Base = "af$($Parts.Groups['major'].Value).1.0"
            $TestRelease = "$Base-rc1"
            $LiveRelease = $Base
        } elseif ($Parts.Groups['candidate'].Success) {
            $TestRelease = "$Base-rc$([int]::Parse($Parts.Groups['candidate'].Value) + 1)"
            $LiveRelease = $Base
        } else {
            $NextPatch = [int]::Parse($Parts.Groups['patch'].Value) + 1
            $TestRelease = "af$($Parts.Groups['major'].Value).$($Parts.Groups['minor'].Value).$NextPatch-rc1"
            $LiveRelease = "af$($Parts.Groups['major'].Value).$($Parts.Groups['minor'].Value).$NextPatch"
        }
        if ([Console]::IsInputRedirected) {
            throw "Pass -Version for a non-interactive build (for example, -Version $TestRelease)."
        }
        Write-Host "Current build: $OldVersion"
        $Choice = (Read-Host "Build type: [T]est ($UpstreamVersion-$TestRelease) or [L]ive ($UpstreamVersion-$LiveRelease) [T]").Trim().ToLowerInvariant()
        switch ($Choice) {
            { $_ -in @('', 't', 'test') } { $Version = $TestRelease; break }
            { $_ -in @('l', 'live') } { $Version = $LiveRelease; break }
            default { throw "Choose T for test or L for live." }
        }
    }

    $Version = $Version.Trim()
    if ($Version -match '^[0-9]+\.[0-9]+\.[0-9]+-' -and -not $Version.StartsWith("$UpstreamVersion-")) {
        throw "Version $Version does not match upstream Smokeview version $UpstreamVersion."
    }
    $NewRelease = if ($Version.StartsWith("$UpstreamVersion-")) {
        $Version.Substring($UpstreamVersion.Length + 1)
    } else { $Version }
    if ($NewRelease -notmatch '^af[0-9]+(?:\.[0-9]+\.[0-9]+)?(?:-rc[1-9][0-9]*)?$') {
        throw "Invalid Ashton release: $NewRelease. Use af2.1.0 or af2.1.0-rc1."
    }
    $SelectedVersion = "$UpstreamVersion-$NewRelease"
    $OldSetting = 'set(ASHTON_RELEASE "' + $OldRelease + '")'
    $NewSetting = 'set(ASHTON_RELEASE "' + $NewRelease + '")'
    if ($CMakeContents.Split(@($OldSetting), [StringSplitOptions]::None).Count -ne 2) {
        throw "Expected exactly one ASHTON_RELEASE setting in CMakeLists.txt."
    }
    if ($DocumentedVersion -ne $SelectedVersion) {
        $NewGuide = $GuideContents.Replace($DocumentedVersion, $SelectedVersion)
        $DocumentedUpstream = [regex]::Match($DocumentedVersion, '^[0-9]+\.[0-9]+\.[0-9]+').Value
        if ($DocumentedUpstream -and $DocumentedUpstream -ne $UpstreamVersion) {
            $NewGuide = $NewGuide.Replace("based on Smokeview $DocumentedUpstream.", "based on Smokeview $UpstreamVersion.")
        }
        [IO.File]::WriteAllText($GuidePath, $NewGuide)
    }
    if ($NewRelease -ne $OldRelease) {
        [IO.File]::WriteAllText($CMakePath, $CMakeContents.Replace($OldSetting, $NewSetting))
    }
    Write-Host "Selected release: $SelectedVersion"
    return $SelectedVersion
}
