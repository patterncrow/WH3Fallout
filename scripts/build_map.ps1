param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$CaimeDirectory,
    [Parameter(Mandatory=$true)][string]$DatabaseDirectory,
    [Parameter(Mandatory=$true)][string]$ScenarioPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$destination = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath (Join-Path $destination 'map.hex')) {
    throw 'Refusing to overwrite an existing map.hex'
}
$null = New-Item -ItemType Directory -Path $destination -Force
Add-Type -AssemblyName WindowsBase, PresentationCore, PresentationFramework
$null = [Reflection.Assembly]::LoadFrom((Join-Path $CaimeDirectory 'Caime.exe'))

# 只调用现有编辑器的地图模型及序列化，不自行实现hex格式。
[object]$scenario = Get-Content -LiteralPath $ScenarioPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($scenario.map.width -ne 64 -or $scenario.map.height -ne 64) {
    throw 'This prototype terrain recipe only supports 64 x 64'
}
$map = [CAIME.MapHexFile]::CreateMapHex($destination, 'map', 'warhammer3',
    $scenario.map.id, 64, 64, 20)
$map.LandRegions.AddRange([string[]]@($scenario.map.regions | ForEach-Object { $_.key }))
# 固定迁移前实际地区色；重建不重新随机分配索引颜色。
for ($index = 0; $index -lt $scenario.map.regions.Count; $index++) {
    $region = $scenario.map.regions[$index]
    $map.ColoursLand.Colours[$index] = ([int]$region.r -shl 16) -bor ([int]$region.g -shl 8) -bor [int]$region.b
}
$database = [IO.Path]::GetFullPath($DatabaseDirectory)
[xml]$grounds = Get-Content -LiteralPath (Join-Path $database 'campaign_ground_types.xml') -Encoding UTF8
[xml]$climates = Get-Content -LiteralPath (Join-Path $database 'climates.xml') -Encoding UTF8
[xml]$attritions = Get-Content -LiteralPath (Join-Path $database 'campaign_map_attritions.xml') -Encoding UTF8
foreach ($row in $grounds.dataroot.campaign_ground_types) {
    if ($row.is_sea -eq '1') { $map.SeaGroundTypes.Add($row.type) }
    else { $map.LandGroundTypes.Add($row.type) }
}
foreach ($row in $climates.dataroot.climates) { $map.Climates.Add($row.climate_type) }
foreach ($row in $attritions.dataroot.campaign_map_attritions) {
    if ($row.type -in @('terrain_land', 'terrain_sea')) { $map.Attritions.Add($row.key) }
}
foreach ($hex in $map.HexData) {
    $x = $hex.Index % 64
    $y = [math]::Floor($hex.Index / 64)
    $hex.IsSea = $false
    $hex.RegionId = 2
    $hex.GroundTypeIndex = $map.LandGroundTypes.IndexOf('desert')
    $hex.ClimateIndex = $map.Climates.IndexOf('emp_lowlands')
    $hex.AttritionIndex = [CAIME.Hex]::INVALID_ATTRITION_INDEX
    $hex.InterestIndex = [CAIME.Hex]::INVALID_AREA_OF_INT_INDEX
    $hex.TownSlotIndex = [CAIME.Hex]::INVALID_SLOT_INDEX
    # 上半幅为相连的两派领地；下方小区通过厚实的不可通行带隔离。
    $mainland = $x -ge 3 -and $x -le 60 -and $y -ge 3 -and $y -le 36
    $enclave = $x -ge 22 -and $x -le 41 -and $y -ge 47 -and $y -le 59
    $hex.IsPassable = $mainland -or $enclave
    if ($mainland) {
        if ($x -lt 32) { $hex.RegionId = 0 } else { $hex.RegionId = 1 }
    }
}
foreach ($point in $scenario.map.settlements) {
    $interior = New-Object 'System.Collections.Generic.HashSet[int]'
    $null = $interior.Add($point[1] * 64 + $point[0])
    for ($radius = 0; $radius -lt 2; $radius++) {
        foreach ($index in @($interior)) {
            for ([uint16]$direction = 0; $direction -lt 6; $direction++) {
                $neighbor = $map.GetNeighbourIndex([int]$index, $direction)
                if ($neighbor -ge 0) { $null = $interior.Add($neighbor) }
            }
        }
    }
    foreach ($index in $interior) {
        $map.HexData[$index].TownSlotIndex = [CAIME.Hex]::MAIN_SLOT_INDEX
        $map.HexData[$index].IsTownSprawl = $true
    }
}
foreach ($hex in $map.HexData) {
    for ([uint16]$direction = 0; $direction -lt 6; $direction++) {
        $neighbor = $map.GetNeighbourIndex([int]$hex.Index, $direction)
        if ($neighbor -ge 0 -and $map.HexData[$neighbor].RegionId -ne $hex.RegionId) {
            $hex.IsBorder = $true
        }
    }
}
$map.CalculateRegionEdgeMasks()
if (-not $map.Save($destination, 'map', $null, $true)) { throw 'CAIME save failed' }

# 从实际落盘的文件重读，并用编辑器自身的邻接关系检查连通分量。
$loaded = New-Object CAIME.MapHexFile
if (-not $loaded.Load((Join-Path $destination 'map.hex'))) { throw 'CAIME reload failed' }
$seen = New-Object 'System.Collections.Generic.HashSet[int]'
$components = 0
foreach ($hex in $loaded.HexData) {
    if (-not $hex.IsPassable -or $seen.Contains($hex.Index)) { continue }
    $components++
    $queue = New-Object 'System.Collections.Generic.Queue[int]'
    $queue.Enqueue($hex.Index)
    $null = $seen.Add($hex.Index)
    while ($queue.Count -gt 0) {
        $index = $queue.Dequeue()
        for ([uint16]$direction = 0; $direction -lt 6; $direction++) {
            $neighbor = $loaded.GetNeighbourIndex([int]$index, $direction)
            if ($neighbor -ge 0 -and $loaded.HexData[$neighbor].IsPassable -and $seen.Add($neighbor)) {
                $queue.Enqueue($neighbor)
            }
        }
    }
}
$manifest = [ordered]@{
    map = $loaded.CampaignMapName
    width = $loaded.MapWidth
    height = $loaded.MapHeight
    region_count = $loaded.LandRegions.Count
    town_count = @($loaded.HexData | Where-Object { $_.TownSlotIndex -eq [CAIME.Hex]::MAIN_SLOT_INDEX } | Select-Object -ExpandProperty RegionId -Unique).Count
    passable_components = $components
    regions = @(for ($index = 0; $index -lt $loaded.LandRegions.Count; $index++) {
        $color = $loaded.ColoursLand.Colours[$index]
        @{key=$loaded.LandRegions[$index]; r=($color -shr 16) -band 255;
          g=($color -shr 8) -band 255; b=$color -band 255}
    })
}
$json = $manifest | ConvertTo-Json -Depth 4 -Compress
[IO.File]::WriteAllText((Join-Path $destination 'map_manifest.json'), $json, (New-Object Text.UTF8Encoding($false)))
$json
