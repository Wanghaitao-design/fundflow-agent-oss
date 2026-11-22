# ============================================================
#  一键打包：把这套分析程序打成"双击就能用"的 Windows 软件
#
#  用法：把这个 build-exe 文件夹放在项目根目录里，双击 1-build.bat
#
#  它只干六件事：
#    1  看这台电脑的情况（系统、磁盘、杀毒）
#    2  检查项目文件齐不齐
#    3  找打包用的 Python（没有就下载一个装进这个文件夹，不改系统设置）
#    4  联网下载打包要用的库（只有这一步联网）
#    5  打成一个能双击的 exe
#    6  自己造两份假账单试跑一遍，跑通才算成
#
#  全过程都写进同文件夹的 build-report.txt —— 出问题把这个文件发回来。
#  分析代码一行都没改，也不会把任何东西传到网上。
# ============================================================

$ErrorActionPreference = 'Continue'
$Here = $PSScriptRoot
$Proj = Split-Path -Parent $Here
$Report = Join-Path $Here 'build-report.txt'
$Venv = Join-Path $Here 'work-env'
$Dist = Join-Path $Here 'dist'
$Work = Join-Path $Here 'work-tmp'
$Req = Join-Path $Here 'requirements-build.txt'
$PyDir = Join-Path $Here 'python-portable'
$HowTo = Join-Path $Here 'howto-officer.txt'

$AppName = '网赌资金研判'
$AppDir = Join-Path $Dist 'fundflow'
$Exe = Join-Path $AppDir 'fundflow.exe'
$SelfFile = Join-Path $AppDir 'selftest-result.txt'
$Zip = Join-Path $Here ('officer-kit-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.zip')

$Utf8 = New-Object System.Text.UTF8Encoding($false)
$TStart = Get-Date

# 找不到 Python 时用来下载的地址（前两个国内快，最后一个是官方源）
$PyVersions = @('3.12.10', '3.12.7', '3.13.5')
$PySites = @('https://mirrors.huaweicloud.com/python',
             'https://registry.npmmirror.com/-/binary/python',
             'https://www.python.org/ftp/python')
# 装库的镜像，前两个国内快
$PipMirrors = @('https://mirrors.aliyun.com/pypi/simple/',
                'https://pypi.tuna.tsinghua.edu.cn/simple',
                'https://pypi.org/simple')

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
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $cmd @argList 2>&1 | ForEach-Object { Raw $_ }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    return $code
}

[System.IO.File]::WriteAllText($Report, '', $Utf8)
Log '========== 开始打包 =========='
Log ('开始时间：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Log ('打包工具放在：' + $Here)
Log ('项目放在：' + $Proj)
Log ''
Log '先说清楚：第 3、4 步要联网下载东西，那是为了在这台电脑上造软件。'
Log '造出来的软件拷到办案电脑上是什么都不用装的，办案内容也不出那台电脑。'

try {
    # ---------- 第 1 步：电脑情况 ----------
    Step 1 '看电脑情况'
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        Log ('系统：' + $os.Caption + ' 版本 ' + $os.Version + ' 内部号 ' + $os.BuildNumber + ' ' + $os.OSArchitecture)
    } catch { Log '读系统版本失败（不影响后面）' }
    try {
        $c = Get-PSDrive C
        Log ('C盘剩余：' + (Mb $c.Free) + '　总共：' + (Mb ($c.Free + $c.Used)) + '　（打包大概要占 3 GB）')
    } catch { Log '读磁盘空间失败（不影响后面）' }
    try {
        $mp = Get-MpComputerStatus
        $on = '没开'
        if ($mp.RealTimeProtectionEnabled) { $on = '开着' }
        Log ('Windows 自带杀毒：实时防护' + $on + ' 版本 ' + $mp.AntivirusVersion)
    } catch { Log '读不到自带杀毒状态（可能装了360或火绒，不影响后面）' }

    try {
        $av = @(Get-CimInstance -Namespace 'root/SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop)
        foreach ($a in $av) { Log ('安全软件：' + $a.displayName) }
        if ($av.Count -eq 0) { Log '没读到任何安全软件（可能全关了）' }
    } catch { Log '读不到安全软件列表（不影响后面）' }

    try {
        $cfa = (Get-MpPreference).EnableControlledFolderAccess
        if ($cfa -eq 1) {
            Log '注意：这台电脑开了「受控文件夹访问」，它会拦住往文件夹里写文件'
            Log '      关掉它：病毒和威胁防护 → 勒索软件防护 → 受控文件夹访问 → 关'
        } else { Log '受控文件夹访问：没开（不挡事）' }
    } catch { Log '读不到受控文件夹访问设置（不影响后面）' }

    $warn = @()
    if ($Proj -match '[^\x00-\x7F]') { $warn = $warn + '路径里有中文' }
    if ($Proj -match '[ ()&]') { $warn = $warn + '路径里有空格或括号' }
    foreach ($d in @('Downloads', 'Desktop', 'Documents', 'OneDrive')) {
        if ($Proj -like ('*' + [char]92 + $d + [char]92 + '*')) { $warn = $warn + ('位置在 ' + $d + ' 里面'); break }
    }
    if ($warn.Count -gt 0) {
        Log ('！这次放的位置有几个不利条件：' + ($warn -join '、'))
        Log '！本次先照旧试。要是失败，第一件事：把整个 windows-kit 挪到 C:\ff\windows-kit'
        Log '！（英文、短、没空格没括号、不在下载文件夹里），再重新双击 1-build.bat'
    }

    # ---------- 第 2 步：项目文件齐不齐 ----------
    Step 2 '检查项目文件'
    $need = @('agent\officer_app.py', 'agent\officer_pack.py', 'gambling_analysis.py',
              'case_pack.py', 'agent\mcp_server\common.py', 'agent\mcp_server\tools\__init__.py',
              'case_packs\wangdu\01_词表.csv', 'case_packs\wangdu\03_门槛.csv')
    $miss = @()
    foreach ($f in $need) { if (-not (Test-Path -LiteralPath (Join-Path $Proj $f))) { $miss = $miss + $f } }
    if ($miss.Count -gt 0) {
        Log '缺这些文件，没法打包:（这个工具必须放在项目文件夹里面）'
        foreach ($f in $miss) { Log ('  缺 ' + $f) }
        throw '项目文件不全'
    }
    if (-not (Test-Path -LiteralPath $Req)) { Log ('缺 ' + $Req); throw '缺依赖清单' }
    Log '项目文件齐了'

    # 一个一个试：这四个文件名的东西，这台电脑让不让往打包文件夹里放
    $ProbeDir = Join-Path $Dist 'probe'
    $DllBlocked = @()
    try {
        if (Test-Path -LiteralPath $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction Stop }
        New-Item -ItemType Directory -Path $ProbeDir -Force | Out-Null
        $buf = New-Object byte[] 65536
        ([System.Random]::new()).NextBytes($buf)
        foreach ($d in @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'vcomp140.dll')) {
            $pf = Join-Path $ProbeDir $d
            try {
                [System.IO.File]::WriteAllBytes($pf, $buf)
                if (-not (Test-Path -LiteralPath $pf)) { $DllBlocked = $DllBlocked + $d }
            } catch { $DllBlocked = $DllBlocked + $d }
        }
        Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        Log ('！清理试探文件夹没清掉（不影响后面）：' + $_)
    }
    if ($DllBlocked.Count -eq 0) {
        Log '写入试探过了：四个运行库文件名都让写，放心往下走'
    } else {
        Log ('！这几个文件名的东西，这台电脑不许放进打包文件夹：' + ($DllBlocked -join '、'))
        Log '！   里面装的是我们现编的随机字节，不可能是病毒 —— 这是按文件名拦的（防"程序劫持"的规则）'
        Log '！   拦人的就是第 1 步列出来的安全软件。三个办法：'
        Log '！   办法一（最省事，推荐）：临时退掉安全软件再重跑 ——'
        Log '！     屏幕右下角找到它的图标，右键 → 退出 / 关闭防护；打包十几分钟，打完再打开。'
        Log '！     这样打出来的软件自带全部文件，办案电脑什么都不用装。'
        Log '！   办法二：把打包文件夹加进白名单（360 安全卫士：木马查杀 → 左下信任区 → 添加文件夹）'
        Log '！     不加的话，打好的 fundflow.exe 也可能被它当可疑程序删掉，这一步早晚要加。'
        Log '！   办法三：什么都不改，继续跑 —— 脚本会自动改用"不打这几个文件"的方式，'
        Log '！     代价是那台电脑得装过微软 VC++ 运行库；缺了的话软件会在窗口上写红字提醒你。'
    }

    # ---------- 第 3 步：找打包用的 Python ----------
    Step 3 '找打包用的 Python（只为了造软件，办案电脑不用装）'
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
        foreach ($p in @(($env:LOCALAPPDATA + '\Programs\Python\Python312\python.exe'),
                         'C:\Program Files\Python312\python.exe',
                         'C:\Python312\python.exe')) {
            if (Test-Path -LiteralPath $p) {
                $PyCmd = $p; $PyPre = @(); $PyVer = ((& $p '-V' 2>&1 | Out-String).Trim() + '（按位置找到的）')
                break
            }
        }
    }
    if (-not $PyCmd -and (Test-Path -LiteralPath (Join-Path $PyDir 'python.exe'))) {
        $PyCmd = Join-Path $PyDir 'python.exe'; $PyPre = @()
        $PyVer = ((& $PyCmd '-V' 2>&1 | Out-String).Trim() + '（上次下载到本文件夹的）')
    }
    if (-not $PyCmd) {
        Log '这台电脑上没有可用的 Python（要 3.11 以上）。'
        Log '现在自己下载一个装进这个文件夹里，不改系统设置、不加到 PATH，删掉这个文件夹就干净了。'
        if (-not (Test-Path -LiteralPath $Work)) { New-Item -ItemType Directory -Path $Work | Out-Null }
        $Setup = Join-Path $Work 'python-setup.exe'
        $done = $false
        foreach ($site in $PySites) {
            if ($done) { break }
            foreach ($ver in $PyVersions) {
                if ($done) { break }
                $url = $site + '/' + $ver + '/python-' + $ver + '-amd64.exe'
                Log ('试着下载：' + $url)
                try {
                    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                    Invoke-WebRequest -Uri $url -OutFile $Setup -UseBasicParsing -TimeoutSec 180
                } catch {
                    Log ('  这个地址下不动：' + $_)
                    continue
                }
                if (-not (Test-Path -LiteralPath $Setup)) { continue }
                Log ('下载完了（' + (Mb ((Get-Item -LiteralPath $Setup).Length)) + '），开始安装到本文件夹')
                $ia = @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0',
                        'Include_test=0', 'Include_doc=0', 'SimpleInstall=1', 'TargetDir=' + $PyDir)
                $code = Run $Setup $ia
                Log ('安装器退出码：' + $code)
                if (Test-Path -LiteralPath (Join-Path $PyDir 'python.exe')) {
                    $PyCmd = Join-Path $PyDir 'python.exe'; $PyPre = @()
                    $PyVer = ((& $PyCmd '-V' 2>&1 | Out-String).Trim() + '（刚下载到本文件夹的）')
                    $done = $true
                } else {
                    Log '装完没找到 python.exe，换下一个地址再试'
                }
            }
        }
    }
    if (-not $PyCmd) {
        Log '还是没找到也下载不到 Python。多半是这台电脑连不上外网。'
        Log '换个网（手机热点）再双击一次；或者浏览器打开 python.org/downloads/windows'
        Log '下载 Python 3.12 安装包，双击安装，第一个画面最下面那个 Add python.exe to PATH 一定要打勾，'
        Log '装完关掉这个黑窗口，重新双击 1-build.bat。'
        throw '没有可用的 Python'
    }
    Log ('打包用这个 Python：' + $PyVer)
    $tkOut = ''
    if ($PyCmd -eq 'py') { $tkOut = (& py @($PyPre + @('-c', 'import tkinter;print(tkinter.TkVersion)')) 2>&1 | Out-String) }
    else { $tkOut = (& $PyCmd -c 'import tkinter;print(tkinter.TkVersion)' 2>&1 | Out-String) }
    Log ('界面组件 tkinter：' + $tkOut.Trim() + '（能打印版本号就是没问题）')

    # ---------- 第 3b 步：微软运行库（数学库要用，缺了打出来也是残的） ----------
    Step '3b' '检查微软 VC++ 运行库（numpy / pandas 这些数学库要用）'
    $Sys32 = Join-Path $env:SystemRoot 'System32'
    $need_dll = @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'vcomp140.dll')
    $miss_dll = @()
    foreach ($d in $need_dll) { if (-not (Test-Path -LiteralPath (Join-Path $Sys32 $d))) { $miss_dll = $miss_dll + $d } }
    if ($miss_dll.Count -eq 0) {
        Log '系统里四个运行库文件都在，不用装'
    } else {
        Log ('系统里缺：' + ($miss_dll -join '、') + '　现在下微软官方安装包（约 25 MB）给这台电脑装上')
        Log '（这是给"做软件的这台电脑"装的，办案电脑不用装。会弹一个安装窗口，点安装就行）'
        if (-not (Test-Path -LiteralPath $Work)) { New-Item -ItemType Directory -Path $Work | Out-Null }
        $Vc = Join-Path $Work 'vc_redist.x64.exe'
        $got = $false
        if ((Test-Path -LiteralPath $Vc) -and ((Get-Item -LiteralPath $Vc).Length -gt 1000000)) { $got = $true }
        if (-not $got) {
            $vcUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri $vcUrl -OutFile $Vc -UseBasicParsing -TimeoutSec 300
                if ((Test-Path -LiteralPath $Vc) -and ((Get-Item -LiteralPath $Vc).Length -gt 1000000)) { $got = $true }
            } catch { Log ('  这个地址下不动：' + $_) }
        }
        if ($got) {
            $code = Run $Vc @('/install', '/passive', '/norestart')
            Log ('运行库安装器退出码：' + $code + '（0 或 3010 都算装好了）')
        } else {
            Log '没下到安装包（这台电脑可能连不上微软的服务器）。手动装一次：'
            Log '浏览器打开 https://aka.ms/vs/17/release/vc_redist.x64.exe 下载，双击安装，'
            Log '装完关掉这个黑窗口，重新双击 1-build.bat。'
        }
        $miss2 = @()
        foreach ($d in $need_dll) { if (-not (Test-Path -LiteralPath (Join-Path $Sys32 $d))) { $miss2 = $miss2 + $d } }
        if ($miss2.Count -gt 0) {
            Log ('装完还缺：' + ($miss2 -join '、') + '　先继续往下试，第 4 步会验到底能不能用')
        } else {
            Log '运行库装好了'
        }
    }

    # ---------- 第 4 步：装打包要用的库 ----------
    Step 4 '下载打包要用的库（联网，大概三到五分钟，屏幕会哗哗刷字，别关窗口）'
    if (-not (Test-Path -LiteralPath $Venv)) {
        $va = @($PyPre) + @('-m', 'venv', $Venv)
        $code = Run $PyCmd $va
        if ($code -ne 0 -or -not (Test-Path -LiteralPath $Venv)) { Log '建工作文件夹失败'; throw '建工作文件夹失败' }
    } else {
        Log '上次建过了，这次接着用（快一点）'
    }
    $VPY = Join-Path $Venv 'Scripts\python.exe'
    $installed = $false
    foreach ($miro in $PipMirrors) {
        Log ('试这个下载源：' + $miro)
        $ia = @('-m', 'pip', 'install', '-r', $Req, '-i', $miro, '--trusted-host', ($miro -replace '^https://', '' -replace '/.*$', ''))
        $code = Run $VPY $ia
        if ($code -eq 0) { $installed = $true; break }
        Log '这个源没下动，换下一个'
    }
    if (-not $installed) {
        Log '三个下载源都没下动。多半是这台电脑连不上外网，或者单位网管挡了。'
        Log '换手机热点再跑一次，或者换台能上网的电脑打包（打出来的软件拷回去用，一样不用装东西）。'
        throw '下载依赖失败'
    }
    # 挨个试一遍，哪个用不了当场说清楚（上次就是数学库悄悄坏了没查出来）
    Log '挨个检查这些库能不能用'
    $mods = @('pandas', 'numpy', 'networkx', 'plotly', 'matplotlib', 'openpyxl', 'xlrd', 'PyInstaller')
    $pipName = @{ pandas = 'pandas'; numpy = 'numpy'; networkx = 'networkx'; plotly = 'plotly';
                  matplotlib = 'matplotlib'; openpyxl = 'openpyxl'; xlrd = 'xlrd';
                  PyInstaller = 'pyinstaller' }
    $bad = @()
    foreach ($m in $mods) {
        & $VPY -c ('import ' + $m) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $bad = $bad + $m }
    }
    if ($bad.Count -gt 0) {
        Log ('用不了：' + ($bad -join '、') + '　重装这几个再试一次')
        foreach ($m in $bad) {
            Run $VPY @('-m', 'pip', 'uninstall', '-y', $pipName[$m])
        }
        $ri = @('-m', 'pip', 'install', '--ignore-installed', '--no-deps', '-i', $PipMirrors[0],
                '--trusted-host', 'mirrors.aliyun.com')
        foreach ($m in $bad) { $ri = $ri + $pipName[$m] }
        Run $VPY $ri
        $bad2 = @()
        foreach ($m in $mods) {
            $o = (& $VPY -c ('import ' + $m) 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) {
                $bad2 = $bad2 + $m
                Log ('  还是不行：' + $m)
                foreach ($ln in ($o -split "`n")) { Raw ('    ' + $ln.Trim()) }
            }
        }
        if ($bad2.Count -gt 0) {
            Log ('这几个装上了还是用不了：' + ($bad2 -join '、'))
        $libsDir = Join-Path $Venv 'Lib\site-packages\numpy\.libs'
        if (Test-Path -LiteralPath $libsDir) {
            Log '数学库自己带的那堆文件里现在有什么（对照下面就知道缺哪个）：'
            foreach ($f in @(Get-ChildItem -LiteralPath $libsDir -File -ErrorAction SilentlyContinue)) {
                Log ('    ' + $f.Name + '　' + [math]::Round($f.Length / 1KB) + ' KB')
            }
        } else {
            Log '数学库自带的文件夹（numpy\.libs）根本没有 —— 说明数学库没装上'
        }
        Log '系统 System32 里的运行库：'
        foreach ($d in @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'vcomp140.dll')) {
            $sp = Join-Path $Sys32 $d
            if (Test-Path -LiteralPath $sp) {
                Log ('    有 ' + $d + '　' + [math]::Round((Get-Item -LiteralPath $sp).Length / 1KB) + ' KB')
            } else {
                Log ('    缺 ' + $d)
            }
        }
            Log '不能再往下打了 —— 打出来的软件是残的。比如数学库用不了，层级判定会偷偷换一条路，'
            Log '跑出来的结果就和咱们对过分的卷子不是同一套算法。那种东西不能给人用。'
            Log '数学库用不了，最常见两个原因：① 上面那份文件清单里缺文件 —— 第 2 步说的安全软件拦文件'
            Log '② 系统里真缺微软运行库 —— 那就双击 vc_redist.x64.exe 装一下。两种都先退掉安全软件再来一次最省事'
            throw '依赖检查没过'
        }
        Log '重装之后都能用了'
    }
    # 版本号交给旁边这个小文件去问：PowerShell 传带双引号的 python 代码会把引号吃掉，
    # 上次报的那个 "pyinstaller 没定义" 就是这么来的假错。
    $VerPy = Join-Path $Here 'check-versions.py'
    if (Test-Path -LiteralPath $VerPy) {
        $verLine = (& $VPY $VerPy 2>&1 | Out-String).Trim()
    } else {
        $verLine = '缺 check-versions.py 这个文件，没法核对版本'
    }
    Log ('版本核对：' + $verLine)

    # ---------- 第 5 步：打成 exe ----------
    Step 5 '打成能双击的软件（最慢的一步，5到15分钟，屏幕可能好久不动，别关窗口）'
    if (Test-Path -LiteralPath $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $Work) {
        Get-ChildItem -LiteralPath $Work -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'pyi-build' } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    # 入口不用 officer_app.py，用它外面那一层：连"打开就崩"都能把原因写下来
    # 判据表（case_packs）必须打进软件里：case_pack.py 一被 import 就要读它，
    # 没打进去 exe 会一打开就死（2026-11-12 早上那份《出了点问题.txt》就是这么来的）
    $AddPacks = (Join-Path $Proj 'case_packs') + ';case_packs'
    $entry = Join-Path $Here 'entry-fundflow.py'
    if (-not (Test-Path -LiteralPath $entry)) { throw '缺 entry-fundflow.py，不敢往下打' }
    $pa = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', 'fundflow',
            '--distpath', $Dist, '--workpath', (Join-Path $Work 'pyi-build'), '--specpath', $Work,
            '--paths', $Proj, '--paths', (Join-Path $Proj 'agent'), '--paths', (Join-Path $Proj 'agent\mcp_server'),
            '--hidden-import', 'officer_pack', '--hidden-import', 'case_pack', '--hidden-import', 'common',
            '--hidden-import', 'tools', '--hidden-import', 'adapter', '--hidden-import', 'gambling_analysis',
            '--hidden-import', 'tools_anonymize', '--collect-submodules', 'tools',
            '--collect-data', 'plotly', '--add-data', $AddPacks, $entry)
    $t0 = Get-Date
    $code = Run $VPY $pa
    $buildSec = [int]((Get-Date) - $t0).TotalSeconds
    Log ('打包工具退出码：' + $code + '　用时：' + $buildSec + ' 秒')
    # 打没打进判据表，当场验一次，别等第 6 步 exe 自己报错
    $包里判据 = Join-Path $AppDir '_internal\case_packs\wangdu\01_词表.csv'
    if (Test-Path -LiteralPath $包里判据) {
        Log '判据表已经打进软件里（_internal\case_packs\wangdu\01_词表.csv 在）'
    } else {
        Log '★★ 判据表没打进软件里，exe 一打开就会死在"找不到案由包"上'
        Log ('   应该在这个位置：' + $包里判据)
    }

    # 撞到"不许写运行库文件"就换个打法：这几个文件不打进包，改用系统里那份
    $ModeB = $false
    if ((-not (Test-Path -LiteralPath $Exe)) -and (Select-String -Path $Report -Pattern 'PermissionError' -Quiet)) {
        Log ''
        Log '上面是不许写运行库文件（安全软件拦的），换第二种打法：这几个文件不打进包里'
        $SpecFile = Join-Path $Work 'fundflow.spec'
        if (Test-Path -LiteralPath $SpecFile) {
            $sp = @(Get-Content -LiteralPath $SpecFile -Encoding UTF8)
            $nb = New-Object System.Collections.Generic.List[string]
            $ins = $false
            foreach ($ln in $sp) {
                if ((-not $ins) -and ($ln -match '^pyz\s*=\s*PYZ')) {
                    $nb.Add('import os as _os')
                    $nb.Add("_140 = ('vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll','vcomp140.dll','concrt140.dll','vccorlib140.dll','vccorlib140_app.dll','mpoapithreads.dll')")
                    $nb.Add('a.binaries = [b for b in a.binaries if _os.path.basename(str(b[0])).lower() not in _140]')
                    $ins = $true
                }
                $nb.Add($ln)
            }
            $Spec2 = Join-Path $Work 'fundflow-nodll.spec'
            [System.IO.File]::WriteAllLines($Spec2, $nb, $Utf8)
            Log ('改好的打包配置：' + $Spec2)
            Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction SilentlyContinue
            $pa2 = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', $Dist,
                     '--workpath', (Join-Path $Work 'pyi-build'), $Spec2)
            $code = Run $VPY $pa2
            Log ('第二种打法退出码：' + $code)
            if (Test-Path -LiteralPath $Exe) { $ModeB = $true }
        } else {
            Log '找不到刚生成的 fundflow.spec，第二种打法用不了'
        }
    }
    if ($ModeB) {
        Log '★ 这次是"第二种打法"：包里不带 vcruntime140.dll 那几个文件，改用系统里装好的那份'
        $Note = Join-Path $Here 'needs-vcruntime.txt'
        if (Test-Path -LiteralPath $Note) {
            Copy-Item -LiteralPath $Note -Destination (Join-Path $AppDir '缺运行库看这个.txt') -Force
            Log '  软件文件夹里多了一个「缺运行库看这个.txt」，给办案电脑的管理员看一眼就懂'
        }
        $Vc = Join-Path $Work 'vc_redist.x64.exe'
        if (Test-Path -LiteralPath $Vc) {
            Copy-Item -LiteralPath $Vc -Destination (Join-Path $AppDir 'vc_redist.x64.exe') -Force
            Log '  微软运行库安装包也拷进去了：vc_redist.x64.exe（在那台电脑双击装一次，一分钟）'
        }
    }
    if (-not (Test-Path -LiteralPath $Exe)) {
        Log '打完了，但没找到 exe。两种可能：① 打包本身没成功（往上翻最后报错那几行）② 杀毒软件把它当病毒删了'
        try {
            $hit2 = Get-MpThreatDetection | Sort-Object -Property InitialDetectionTime -Descending | Select-Object -First 5
            foreach ($h in $hit2) { Log ('  杀毒软件最近报过：' + $h.Resources) }
        } catch { }
        throw '没打出 exe'
    }

    # 判据表（案由包）摆在 exe 旁边：以后改判据不用重新打包
    $PackOut = Join-Path $AppDir 'case_packs'
    if (Test-Path -LiteralPath $PackOut) { Remove-Item -LiteralPath $PackOut -Recurse -Force -ErrorAction SilentlyContinue }
    Copy-Item -LiteralPath (Join-Path $Proj 'case_packs') -Destination $PackOut -Recurse -Force
    Log '判据表已放到软件旁边（case_packs 文件夹，改它不用重新打包）'
    if (Test-Path -LiteralPath $HowTo) {
        Copy-Item -LiteralPath $HowTo -Destination (Join-Path $AppDir '怎么用.txt') -Force
        Log '说明文件已放进软件文件夹：怎么用.txt'
    }

    $fs = @(Get-ChildItem -LiteralPath $AppDir -Recurse -File)
    $bytes = 0
    foreach ($f in $fs) { $bytes = $bytes + $f.Length }
    Log ''
    Log ('★ 打出来了：' + $Exe)
    Log ('★ 整个软件大小：' + (Mb $bytes) + '　里面 ' + $fs.Count + ' 个文件')
    Log ('★ 打包用时：' + $buildSec + ' 秒')

    # ---------- 第 6 步：验收（不用你准备账单） ----------
    Step 6 '验收：让打出来的 exe 自己造两份假账单跑一遍'
    $ExeSelfOk = $false
    $TempSelf = Join-Path $env:TEMP 'selftest-result.txt'
    $崩文件 = Join-Path $AppDir '出了点问题.txt'
    foreach ($旧 in @($SelfFile, $TempSelf, $崩文件)) {
        if (Test-Path -LiteralPath $旧) { Remove-Item -LiteralPath $旧 -Force -ErrorAction SilentlyContinue }
    }
    $t0 = Get-Date
    $env:PYTHONIOENCODING = 'utf-8'
    $code = 1
    $OutLog = Join-Path $Work 'exe-selftest-out.txt'
    $ErrLog = Join-Path $Work 'exe-selftest-err.txt'
    try {
        $p = Start-Process -FilePath $Exe -ArgumentList '--自检' -WorkingDirectory $AppDir `
                           -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
                           -Wait -PassThru
        $code = $p.ExitCode
    } catch { Log ('启动 exe 失败：' + $_) }
    $selfSec = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    Log ('自检退出码：' + $code + '　用时：' + $selfSec + ' 秒')
    $Self找着 = $null
    foreach ($f in @($SelfFile, $TempSelf)) {
        if (Test-Path -LiteralPath $f) { $Self找着 = $f; break }
    }
    if ($Self找着) {
        $txt = [System.IO.File]::ReadAllText($Self找着, [System.Text.Encoding]::UTF8)
        Log ('自检结果文件：' + $Self找着)
        Raw $txt
        if ($txt -match 'PASS') { Log '★ 自检通过：打出来的 exe 能自己干活'; $ExeSelfOk = $true }
        else { Log '★ 自检没过（上面是它自己写的全过程，发回来就能定位）' }
    } else {
        Log '没写出自检结果文件 —— 它没来得及写东西就出事了，看下面两坨'
    }
    foreach ($log in @($ErrLog, $OutLog)) {
        if ((Test-Path -LiteralPath $log) -and ((Get-Item -LiteralPath $log).Length -gt 0)) {
            Log ('exe 自己吐出来的东西（' + (Split-Path -Leaf $log) + '）：')
            # exe 吐出来的是 UTF-8，不写 Encoding 的话 PowerShell 5.1 会按 GBK 猜，
            # 报告里就成了一堆 nobody 看不懂的乱码（第 4 次打包报告就这样）
            foreach ($ln in @(Get-Content -LiteralPath $log -Encoding UTF8)) { Raw ('    ' + [string]$ln) }
        }
    }
    if (Test-Path -LiteralPath $崩文件) {
        Log 'exe 崩的时候自己写下来的原因：'
        foreach ($ln in @(Get-Content -LiteralPath $崩文件 -Encoding UTF8)) { Raw ('    ' + [string]$ln) }
    }

    # 6b 真点一遍窗口：民警那条路（选文件夹→点开始→出三样）在这台电脑上有屏幕，跑得动
    Log ''
    Log '第 6b 步：真点一遍窗口（会用源码跑，屏幕上会闪一下分析窗口，别点它）'
    $GuiTest = Join-Path $Proj 'agent\verify\gui_path_selftest.py'
    if (Test-Path -LiteralPath $GuiTest) {
        $g = Run $VPY @($GuiTest)
        if ($g -eq 0) { Log '★ 窗口那条路跑通：选文件夹→点开始→三样产物齐' }
        else { Log '★ 窗口那条路没跑通（上面有报错），这条比打包更要紧，务必把报告发回来' }
    } else {
        Log '没有 gui_path_selftest.py，跳过（不影响 exe 自检）'
    }

    # ---------- 第 7 步：装成一份，看看多大 ----------
    Step 7 '把软件压成一个文件，方便拷走'
    if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue }
    try {
        Compress-Archive -Path $AppDir -DestinationPath $Zip -CompressionLevel Optimal
        Log ('压缩包：' + $Zip + '　大小：' + (Mb ((Get-Item -LiteralPath $Zip).Length)))
    } catch {
        Log ('压缩失败（不影响软件本身）：' + $_)
    }

    # ---------- 第 8 步：桌面放个图标 ----------
    Step 8 '在桌面放一个图标，让你看看像不像普通软件'
    try {
        $desk = [Environment]::GetFolderPath('Desktop')
        $ws = New-Object -ComObject WScript.Shell
        $lnk = Join-Path $desk '网赌资金研判.lnk'
        $sc = $ws.CreateShortcut($lnk)
        $sc.TargetPath = $Exe
        $sc.WorkingDirectory = $AppDir
        $sc.Description = '双击打开：选账单文件夹，点开始'
        $sc.Save()
        Log ('桌面图标做好了：' + $lnk)
        Log '现在双击它试试：应该弹出一个窗口，什么都不用装、不用敲命令。'
    } catch {
        Log ('桌面图标没做成（不影响软件本身）：' + $_)
    }

    $total = [math]::Round(((Get-Date) - $TStart).TotalSeconds / 60, 1)
    Log ''
    Log '========== 打包跑完了 =========='
    Log ('一共花了 ' + $total + ' 分钟')
    Log ''
    if (-not $ExeSelfOk) {
        Log '★★ 要紧的一句话：打出来的 exe 自己没能跑通（第 6 步没过）。'
        Log '   这份东西现在只能算"打出来了"，不能算"能交给民警用"。'
        Log '   先别拷去办案电脑，把这份 build-report.txt 发回来，我照着改。'
        Log ''
    } else {
        Log '★★ 打出来的 exe 自己跑通了，双击它试试，应该直接弹窗口。'
        Log ''
    }
    Log ('★ 软件在这里：' + $AppDir)
    Log '★ 双击这个就能开：fundflow.exe（或者桌面上那个「网赌资金研判」图标）'
    Log '★ 拷到办案电脑：把整个 fundflow 文件夹（或者那个 officer-kit-开头 的压缩包）复制过去，'
    Log '  解压到任意位置就能用，那台电脑什么都不用装，也不用联网。'
    Log '★ 判据表在软件里面的 case_packs 文件夹，用 Excel 就能改，改完下次打开就生效。'
    Log ''
    Log '把 build-report.txt 发回来，我照着它定下一步怎么改。'
}
catch {
    Log ''
    Log ('这次中途停住了：' + $_)
    Log '不用管它，把 build-report.txt 发回来我看就行，报错原文都在里面。'
}

Write-Host ''
Write-Host '报告在这个位置：' $Report
try { Start-Process notepad.exe $Report } catch { }
if (Test-Path -LiteralPath $AppDir) {
    try { Start-Process explorer.exe $AppDir } catch { }
}
