param(
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$MapFile,
    [Parameter(Mandatory=$true)][string]$CaimeDirectory
)
$ErrorActionPreference = 'Stop'
trap { [Console]::Error.WriteLine($_.Exception.ToString()); exit 1 }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName WindowsBase, PresentationCore, PresentationFramework
$assembly = [Reflection.Assembly]::LoadFrom((Join-Path $CaimeDirectory 'Caime.exe'))

# 设置仅限本进程内存；不调用Save，不改用户GUI偏好与原始AK。
$preferences = [CAIME.PreferencesViewModel]::Instance
$preferences.SelectedGameIndex = [int][CAIME.GameTemplate]::Warhammer3
$preferences.SetAssKitPath([CAIME.GameTemplate]::Warhammer3, [IO.Path]::GetFullPath($Workspace))
$preferences.DatabaseSource = [CAIME.DatabaseSource]::AssemblyKit
$cli = $assembly.GetType('CAIME.CliRunner')
$cli.GetField('<IsActive>k__BackingField', [Reflection.BindingFlags]'NonPublic,Static').SetValue($null, $true)
[CAIME.LoggerViewModel]::ConsoleSink = [Action[string,CAIME.LogLevel]]{ param($message, $level) [Console]::WriteLine($level.ToString() + ': ' + $message) }
$manager = New-Object CAIME.ProjectManager
$toolsProperty = $manager.GetType().GetProperty('ToolsPath')
$toolsProperty.GetSetMethod($true).Invoke($manager, [object[]]@([string](Join-Path $CaimeDirectory 'Tools\'))) | Out-Null
$project = $manager.Open([IO.Path]::GetFullPath($MapFile))
if ($null -eq $project) { throw 'CAIME failed to open isolated map' }
try {
    # GUI通常负责初始化边界导出选项，独立调用时在本进程补齐。
    $borderType = $assembly.GetType('CAIME.BorderExportOptionsViewModel')
    $borderOptions = $borderType.GetConstructors()[0].Invoke([object[]]@($project.PSObject.BaseObject))
    foreach ($name in @('Rivers','TownSlots','Roads','Bridges','Beaches','Regions','Attritions','Climates','GroundTypes','Impassable','Sprawl')) {
        $validator = $assembly.GetType('CAIME.Validators.' + $name + 'Validator')
        if (-not $validator.GetMethod('Validate').Invoke($null, @($project))) {
            throw ('CAIME validation failed: ' + $name)
        }
        Write-Output ('Validated: ' + $name)
    }
    if (-not $manager.ExportProcessedPathfindingData()) { throw 'Pathfinding processing failed' }
    if (-not $manager.ExportProcessedBordersData()) { throw 'Border processing failed' }
    if (-not $project.MapHexFile.Save($project.ProjectPath, 'map', $null, $true)) { throw 'Save before native export failed' }
    if (-not $manager.ProcessMapDataEsf()) { throw 'Map data processing failed' }
    if (-not $manager.GenerateLookupImage()) { throw 'Lookup bitmap generation failed' }
    Write-Output 'Map processing completed'
} finally {
    $manager.CloseProject()
}
