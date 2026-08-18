param(
    [switch]$Purge
)

$ErrorActionPreference = "Stop"

if (-not $Purge) {
    throw "Use -Purge para confirmar a limpeza dos artefactos de compilacao."
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$rootPrefix = $root.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$targets = @(
    [System.IO.Path]::GetFullPath((Join-Path $root "build")),
    [System.IO.Path]::GetFullPath((Join-Path $root "dist"))
)

foreach ($target in $targets) {
    if (-not $target.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Destino fora do projeto: $target"
    }
    if ((Split-Path -Path $target -Leaf) -notin @("build", "dist")) {
        throw "Destino inesperado: $target"
    }
}

 $failures = [System.Collections.Generic.List[string]]::new()
foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target)) {
        continue
    }

    # Limpa cada artefacto de primeiro nivel individualmente. Assim um unico
    # ficheiro bloqueado nao impede remover os restantes pacotes antigos.
    foreach ($child in @(Get-ChildItem -LiteralPath $target -Force)) {
        try {
            Remove-Item -LiteralPath $child.FullName -Recurse -Force -ErrorAction Stop
        }
        catch {
            $failures.Add("$($child.FullName): $($_.Exception.Message)")
        }
    }

    if (-not (Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        try {
            Remove-Item -LiteralPath $target -Force -ErrorAction Stop
        }
        catch {
            $failures.Add("$($target): $($_.Exception.Message)")
        }
    }
    elseif ($failures.Count -eq 0) {
        $failures.Add("$($target): contem itens que nao puderam ser removidos.")
    }
}

foreach ($target in $targets) {
    if ((Test-Path -LiteralPath $target) -and -not ($failures | Where-Object { $_.StartsWith($target, [System.StringComparison]::OrdinalIgnoreCase) })) {
        $failures.Add("$($target): nao foi possivel limpar.")
    }
}

if ($failures.Count -gt 0) {
    throw ("Limpeza incompleta:`n - " + ($failures -join "`n - "))
}

Write-Host "Artefactos de build removidos: build e dist." -ForegroundColor Green
