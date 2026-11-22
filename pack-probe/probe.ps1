# ============================================================
#  探路脚本（在你这台 Windows 11 上跑一次就够）
#
#  它只干五件事：
#    1. 看看这台电脑的情况（系统版本、C盘还剩多少、杀毒软件有没有动静）
#    2. 找打包用的 Python（没有就用系统自带的 winget 装一个，只在这台电脑上装）
#    3. 联网下载打包要用的东西（只下载这一次）
#    4. 把这套分析程序打成一个文件夹，里面直接有个能双击的 exe
#    5. 拿项目自带的样例账单跑一遍，看这个 exe 单独拿出来能不能干活
#
#  它不会改项目里任何分析代码，也不会把任何东西传到网上。
#  全过程都写进同文件夹的 探路报告.txt —— 把那个文件发回来就行。
# ============================================================

$ErrorActionPreference = 'Continue'
$Here  = $PSScriptRoot
$Proj  = Split-Path -Parent $Here
$Report = Join-Path $Here '探路报告.txt'
$Venv  = Join-Path $Here '探路-env'
$Dist  = Join-Path $Here '探路成品'
$Build = Join-Path $Here '探路-临时'
$Req   = Join-Path $Here 'requirements-officer.txt'
$Sample = Join-Path $Proj 'agent\deliverables\smoke_fixtures'
$Mirror = 'https://mirrors.aliyun.com/pypi/simple/'
$Exe   = Join-Path $Dist 'fundflow\fundflow.exe'
$Utf8  = New-Object System.Text.UTF8Encoding($false)
$TStart = Get-Date

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Log($m) {
    $line = '[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $m
    Write-Host $line
    [System.IO.File]::AppendAllText($Report, $line + "`r`n", $Utf8)
}
function Raw($m) {
    $s = '' + $m
    Write-Host $s
    [System.IO.File]::AppendAllText($Report, $s + "`r`n", $Utf8)
}
function Mb($b) { return ('{0:N1} MB' -f ($b / 1MB)) }
function Step($n, $m) {
    Log ''
    Log ('---------- 第 ' + $n + ' 步：' + $m + ' ----------')
}
function Run($cmd, [array]$argList = @()) {
    # 执行一条命令：屏幕上看得见，同时全部写进报告文件，最后返回它的退出码
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $cmd @argList 2>&1 | ForEach-Object { Raw $_ }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    return $code
}

[System.IO.File]::WriteAllText($Report, '', $Utf8)
Log '========== 开始探路 =========='
Log ('开始时间：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Log ('这个工具放在：' + $Here)
Log ('项目放在：' + $Proj)
Log ''
Log '先说清楚：第 2、3 步要联网下载东西，那是为了在这台电脑上造软件。'
Log '造出来的软件装上之后不用联网，办案内容不出这台电脑。'

try {
    # ---------- 第 1 步：这台电脑的情况 ----------
    Step 1 '看电脑情况'
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        Log ('系统：' + $os.Caption + ' 版本 ' + $os.Version + ' 内部号 ' + $os.BuildNumber + ' ' + $os.OSArchitecture)
    } catch { Log '读系统版本失败（不影响后面）' }
    try {
        $c = Get-PSDrive C
        Log ('C盘剩余：' + (Mb $c.Free) + '　总共：' + (Mb ($c.Free + $c.Used)))
    } catch { Log '读磁盘空间失败（不影响后面）' }
    try {
        $mp = Get-MpComputerStatus
        $on = '没开'
        if ($mp.RealTimeProtectionEnabled) { $on = '开着' }
        Log ('Windows 自带杀毒：实时防护' + $on + ' 版本 ' + $mp.AntivirusVersion)
        $hit = Get-MpThreatDetection | Sort-Object -Property InitialDetectionTime -Descending | Select-Object -First 3
        foreach ($h in $hit) { Log ('  杀毒最近报过：' + $h.Resources) }
        if (-not $hit) { Log '  杀毒软件最近没报过东西' }
    } catch { Log '读不到自带杀毒的状态（可能装了360或火绒，不影响后面）' }

    $need = @('agent\officer_pack.py', 'gambling_analysis.py', 'agent\mcp_server\common.py', 'agent\mcp_server\tools\__init__.py')
    $miss = @()
    foreach ($f in $need) { if (-not (Test-Path -LiteralPath (Join-Path $Proj $f))) { $miss = $miss + $f } }
    if ($miss.Count -gt 0) {
        Log '出问题了：这个工具必须放在项目文件夹里面，旁边还缺这些文件：'
        foreach ($f in $miss) { Log ('  缺 ' + $f) }
        Log '把整个项目文件夹（里面有 Windows探路 这个子文件夹）一起拷过来再跑。'
        throw '项目文件不全'
    }
    if (-not (Test-Path -LiteralPath $Sample)) {
        Log ('没有样例账单：' + $Sample + '　第 5 步试跑会跳过')
    }
    Log '项目文件齐了'

    # ---------- 第 2 步：找打包用的 Python ----------
    Step 2 '找打包用的 Python（只为了造软件，民警版不用装）'
    $PyCmd = ''
    $PyPre = @()
    $PyVer = ''
    foreach ($v in @('-3.12', '-3.13', '-3.11', '-3')) {
        try {
            $out = (& py $v '-V' 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $out -match '3\.(\d+)') {
                if ([int]$Matches[1] -ge 11) {
                    $PyCmd = 'py'; $PyPre = @($v); $PyVer = $out
                    break
                }
            }
        } catch { }
    }
    if (-not $PyCmd) {
        foreach ($p in @(($env:LOCALAPPDATA + '\Programs\Python\Python312\python.exe'), 'C:\Program Files\Python312\python.exe', 'C:\Python312\python.exe')) {
            if (Test-Path -LiteralPath $p) {
                $PyCmd = $p; $PyPre = @(); $PyVer = ((& $p '-V' 2>&1 | Out-String).Trim() + '（按位置找到的）')
                break
            }
        }
    }
    if (-not $PyCmd) {
        Log '这台电脑上没有可用的 Python（要 3.11 以上）。现在用 Windows 自带的 winget 装一个 Python 3.12。'
        Log '屏幕会跳出来一个安装过程，如果弹窗口问你要不要允许，点「是」或者「接受」。'
        $wa = @('install', '-e', '--id', 'Python.Python.3.12', '--source', 'winget', '--accept-package-agreements', '--accept-source-agreements')
        $code = Run 'winget' $wa
        Log ('winget 退出码：' + $code)
        foreach ($p in @(($env:LOCALAPPDATA + '\Programs\Python\Python312\python.exe'), 'C:\Program Files\Python312\python.exe')) {
            if (Test-Path -LiteralPath $p) {
                $PyCmd = $p; $PyPre = @(); $PyVer = ((& $p '-V' 2>&1 | Out-String).Trim() + '（刚装好的）')
                break
            }
        }
        if (-not $PyCmd) {
            try {
                $o2 = (& py -3.12 '-V' 2>&1 | Out-String).Trim()
                if ($LASTEXITCODE -eq 0 -and $o2) { $PyCmd = 'py'; $PyPre = @('-3.12'); $PyVer = ($o2 + '（刚装好的）') }
            } catch { }
        }
    }
    if (-not $PyCmd) {
        Log '还是没找到 Python。手动装一下（就这一次）：'
        Log '  1) 浏览器打开 python.org/downloads/windows 下载 Python 3.12 安装包'
        Log '  2) 双击安装，第一个画面最下面那个 Add python.exe to PATH 一定要打勾'
        Log '  3) 装完关掉这个黑窗口，重新双击run.bat'
        throw '没有可用的 Python'
    }
    Log ('打包用这个 Python：' + $PyVer)

    # ---------- 第 3 步：备料 ----------
    Step 3 '准备打包要用的东西（联网下载，大概两三分钟）'
    if (-not (Test-Path -LiteralPath $Venv)) {
        $va = @($PyPre) + @('-m', 'venv', $Venv)
        $code = Run $PyCmd $va
        if ($code -ne 0 -or -not (Test-Path -LiteralPath $Venv)) { Log '建工作文件夹失败'; throw '建工作文件夹失败' }
    } else {
        Log '上次建过了，这次接着用（快一点）'
    }
    $VPY = Join-Path $Venv 'Scripts\python.exe'
    $ua = @('-m', 'pip', 'install', '--upgrade', 'pip', '-i', $Mirror, '--trusted-host', 'mirrors.aliyun.com')
    Run $VPY $ua | Out-Null
    Log '正在下载数据分析、画图的库和打包工具，屏幕会哗哗刷字，等一下。'
    $ia = @('-m', 'pip', 'install', '-r', $Req, '-i', $Mirror, '--trusted-host', 'mirrors.aliyun.com')
    $code = Run $VPY $ia
    if ($code -ne 0) {
        Log '阿里云镜像没下动，改用官方源再试一次（要多等一些）'
        $ib = @('-m', 'pip', 'install', '-r', $Req)
        $code = Run $VPY $ib
        if ($code -ne 0) {
            Log '还是失败。多半是这台电脑连不上外网，或者单位网管挡了。把报告发回来我看。'
            throw '下载依赖失败'
        }
    }
    $ver = (& $VPY -c 'import pandas,numpy,matplotlib,plotly,networkx,PyInstaller;print("pandas",pandas.__version__,"numpy",numpy.__version__,"matplotlib",matplotlib.__version__,"plotly",plotly.__version__,"pyinstaller",PyInstaller.__version__)' 2>&1 | Out-String).Trim()
    Log ('版本核对：' + $ver)

    # ---------- 第 4 步：打成一个文件夹 ----------
    Step 4 '打成一个能双击的软件（最慢的一步，5到15分钟，屏幕可能好久不动，别关窗口）'
    if (Test-Path -LiteralPath $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction SilentlyContinue }
    $entry = Join-Path $Proj 'agent\officer_pack.py'
    $pa = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console', '--name', 'fundflow',
            '--distpath', $Dist, '--workpath', $Build, '--specpath', $Build,
            '--paths', $Proj, '--paths', (Join-Path $Proj 'agent'), '--paths', (Join-Path $Proj 'agent\mcp_server'),
            '--hidden-import', 'common', '--hidden-import', 'tools', '--hidden-import', 'adapter',
            '--hidden-import', 'gambling_analysis', '--hidden-import', 'tools_anonymize',
            '--hidden-import', 'range.generator', '--collect-data', 'plotly', $entry)
    $t0 = Get-Date
    $code = Run $VPY $pa
    $buildSec = [int]((Get-Date) - $t0).TotalSeconds
    Log ('打包工具退出码：' + $code + '　用时：' + $buildSec + ' 秒')

    if (-not (Test-Path -LiteralPath $Exe)) {
        Log '打完了，可在文件夹里找不到那个 exe。'
        Log '两种可能：① 打包本身没成功（往上翻报告能看到最后错在哪一行）② 杀毒软件刚把它当病毒删了'
        try {
            $hit2 = Get-MpThreatDetection | Sort-Object -Property InitialDetectionTime -Descending | Select-Object -First 5
            foreach ($h in $hit2) { Log ('  杀毒软件最近报过：' + $h.Resources) }
        } catch { }
        throw '没打出 exe'
    }
    $outDir = Split-Path -Parent $Exe
    $fs = @(Get-ChildItem -LiteralPath $outDir -Recurse -File)
    $bytes = 0
    foreach ($f in $fs) { $bytes = $bytes + $f.Length }
    Log ''
    Log ('★ 打出来了：' + $Exe)
    Log ('★ 整个软件大小：' + (Mb $bytes) + '　里面 ' + $fs.Count + ' 个文件')
    Log ('★ 打包用时：' + $buildSec + ' 秒')

    # ---------- 第 5 步：只用打出来的 exe 试跑 ----------
    Step 5 '试跑：只用打出来的 exe，不靠源码'
    $t0 = Get-Date
    $null = (& $Exe 2>&1 | Out-String)
    $openSec = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    Log ('空跑一次（不带账单）花 ' + $openSec + ' 秒 —— 这差不多就是民警双击后要等的开屏时间')

    if (Test-Path -LiteralPath $Sample) {
        Log ('拿样例账单跑一遍：' + $Sample)
        $t0 = Get-Date
        & $Exe $Sample 2>&1 | ForEach-Object { Raw $_ }
        $runSec = [int]((Get-Date) - $t0).TotalSeconds
        Log ('跑完用了 ' + $runSec + ' 秒　退出码 ' + $LASTEXITCODE)
        $resRoot = Join-Path (Split-Path -Parent $Sample) '分析结果'
        if (Test-Path -LiteralPath $resRoot) {
            $latest = Get-ChildItem -LiteralPath $resRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latest) {
                Log ('民警会看到的文件夹：' + $latest.FullName)
                foreach ($f in (Get-ChildItem -LiteralPath $latest.FullName -File)) {
                    Log ('   ' + $f.Name + '　' + (Mb $f.Length))
                }
                Log '现在就帮你把这个文件夹打开，你自己点开看看图对不对、表能不能用。'
                Start-Process explorer.exe $latest.FullName
            }
        } else {
            Log '跑了但没找到结果文件夹，要看上面的报错。'
        }
    } else {
        Log '没有样例账单，跳过试跑'
    }

    # ---------- 第 6 步：桌面放个图标 ----------
    Step 6 '在桌面放一个图标，让你感受一下像不像普通软件'
    try {
        $desk = [Environment]::GetFolderPath('Desktop')
        $ws = New-Object -ComObject WScript.Shell
        $lnk = Join-Path $desk '资金流研判-探路版（把账单文件夹拖到图标上）.lnk'
        $sc = $ws.CreateShortcut($lnk)
        $sc.TargetPath = $Exe
        $sc.WorkingDirectory = $outDir
        $sc.IconLocation = $Exe + ',0'
        $sc.Description = '把装账单的文件夹拖到这个图标上松手，就跑分析'
        $sc.Save()
        Log ('桌面图标做好了：' + $lnk)
        Log '现在做个实验：在桌面上找到它，把一个装账单的文件夹用鼠标拖到图标上松手，看它会不会自己跑出结果。'
    } catch {
        Log ('桌面图标没做成（不影响前面的结论）：' + $_)
    }

    $total = [math]::Round(((Get-Date) - $TStart).TotalSeconds / 60, 1)
    Log ''
    Log '========== 探路跑完了 =========='
    Log ('一共花了 ' + $total + ' 分钟')
    Log '只要上面没有出现「失败」或者「没打出 exe」，就说明这条路走得通。'
    Log '把 探路报告.txt 发回来，我照着它定下一步怎么改。'
}
catch {
    Log ''
    Log ('这次中途停住了：' + $_)
    Log '不用管它，把 探路报告.txt 发回来我看就行，报错原文都在里面。'
}

Write-Host ''
Write-Host '报告在这个位置：' $Report
try { Start-Process notepad.exe $Report } catch { }
