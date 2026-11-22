# PC 环境一条龙：装库 + 跑七个自检，结果写到 C:\ff\pc-setup-report.txt
# 为什么写成这样：用户不懂命令行，双击一个文件就能把这台电脑弄成能打包、能自检的状态。
# 只读代码不动代码；不装 sklearn（360 会删它的 dll，而且分析机早就不吃它）。

$ErrorActionPreference = 'Continue'
$Here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root   = Split-Path -Parent $Here
$LogFile = 'C:\ff\pc-setup-report.txt'
$RepoUrl = 'https://github.com/Wanghaitao-design/fundflow-agent-dev.git'
$Venv   = 'C:\ff\dev-env'
$VPY    = Join-Path $Venv 'Scripts\python.exe'
$Mirrors = @('https://mirrors.aliyun.com/pypi/simple/', 'https://pypi.tuna.tsinghua.edu.cn/simple')

if (-not (Test-Path -LiteralPath 'C:\ff')) { New-Item -ItemType Directory -Path 'C:\ff' | Out-Null }
'PC 环境自检报告　开始时间 ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Out-File -LiteralPath $LogFile -Encoding utf8

function Log($m) {
    $line = ('[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $m)
    Write-Host $line
    $line | Out-File -LiteralPath $LogFile -Append -Encoding utf8
}
function Raw($m) {
    ('    ' + $m) | Out-File -LiteralPath $LogFile -Append -Encoding utf8
}
function Step($n, $t) {
    Log ''
    Log ('---------- ' + $n + '：' + $t + ' ----------')
}

$Fail = @()

# ---------- 第 1 步：这台电脑有什么 ----------
Step '1' '看电脑和已有的东西'
Log ('项目放在：' + $Root)
Log '！开工前先把打包文件夹加进安全软件白名单，不然后面每次都会被它拦：'
Log '！  360 安全卫士 → 木马查杀 → 左下角"信任区" → 添加文件夹 → 选 C:\ff　（要管理员权限）'
Log '！  不这么做的话，装库时会报 Permission denied: ...\xxx.dll，那不是你做错了，是它删文件'
$IsGitRepo = Test-Path -LiteralPath (Join-Path $Root '.git')
Log ('这是 git 仓库吗：' + $(if ($IsGitRepo) { '是' } else { '不是（这是解压出来的打包包，只跑库和自检，不碰 git）' }))
$gitVer = ''
try { $gitVer = (& git --version 2>&1 | Out-String).Trim() } catch { }
if ($gitVer) { Log ('git：' + $gitVer) } else {
    Log '！没找到 git。要能把改动传回仓库就得装一个：'
    Log '！  国内快：https://registry.npmmirror.com/-/binary/git-for-windows/ 下载 64-bit 的 Git-installer.exe'
    Log '！  装的时候一路下一步就行；装完把这个黑窗口关掉，重新双击一次本脚本'
    $Fail = $Fail + 'git 没装'
}

$Py = ''
foreach ($cand in @('3.14', '3.12', '3.11')) {
    $v = ''
    try { $v = (& py $cand --version 2>&1 | Out-String).Trim() } catch { }
    if ($v -and ($LASTEXITCODE -eq 0)) { $Py = 'py ' + $cand; Log ('打包/自检用这个 Python：' + $v); break }
}
if (-not $Py) {
    try { $v = (& python --version 2>&1 | Out-String).Trim(); if ($v) { $Py = 'python'; Log ('用 python：' + $v) } } catch { }
}
if (-not $Py) { Log '！这台电脑没有 Python 3.11/3.12/3.14。去 https://www.python.org/downloads/windows/ 装 3.12，'
               Log '！  第一个画面最下面那个 "Add python.exe to PATH" 一定要打勾'
               $Fail = $Fail + '没有 Python' }

# ---------- 第 2 步：仓库（有 git 才做） ----------
if ($gitVer -and $IsGitRepo) {
    Step '2' '看仓库分支状态（只看不改）'
    $b = (& git -C $Root rev-parse --abbrev-ref HEAD 2>&1 | Out-String).Trim()
    Log ('当前分支：' + $b)
    $h = (& git -C $Root log -1 --format='%h %ad %s' --date=short 2>&1 | Out-String).Trim()
    Log ('最新一条提交：' + $h)
    $u = (& git config --local user.email 2>&1 | Out-String).Trim()
    if (-not $u) {
        & git config --local user.name  'PC-windows' 2>&1 | Out-Null
        & git config --local user.email 'pc-windows@example.invalid' 2>&1 | Out-Null
        Log '给这台电脑配了提交用的署名（PC-windows / 占位邮箱 example.invalid，要把提交挂到真实账号请换成自己的邮箱）'
    } else { Log ('提交署名已有：' + $u) }
    Log '要新分支的话在 Orca 里说"从 main 拉一条 wht/pc 分支并推上去"，脚本不替你动 git'
}

# ---------- 第 3 步：虚拟环境 ----------
Step '3' '建/用虚拟环境 C:\ff\dev-env'
if (-not (Test-Path -LiteralPath $VPY)) {
    if ($Py) {
        Log '第一次建，大概半分钟'
        if ($Py -like 'py *') {
            $pre = ($Py -split ' ')[1]
            & py $pre -m venv $Venv 2>&1 | ForEach-Object { Raw $_ }
        } else {
            & python -m venv $Venv 2>&1 | ForEach-Object { Raw $_ }
        }
    }
} else { Log '已经建过了，接着用' }
if (-not (Test-Path -LiteralPath $VPY)) { Log '！虚拟环境没建成，下面几步做不了'; $Fail = $Fail + '虚拟环境' }

# ---------- 第 4 步：装库（绝不装 sklearn） ----------
Step '4' '装要用的库（联网，三五分钟，别关窗口）'
$Req = Join-Path $Here 'requirements-build.txt'
if ((Test-Path -LiteralPath $VPY) -and (Test-Path -LiteralPath $Req)) {
    $done = $false
    foreach ($mir in $Mirrors) {
        Log ('试这个下载源：' + $mir)
        & $VPY -m pip install --disable-pip-version-check -r $Req -i $mir --trusted-host mirrors.aliyun.com --trusted-host pypi.tuna.tsinghua.edu.cn 2>&1 |
            ForEach-Object { Raw $_ }
        if ($LASTEXITCODE -eq 0) { $done = $true; Log '库装好了'; break }
        Log '这个源没弄成，换下一个'
    }
    if (-not $done) {
        Log '！两个源都没装上。两种可能：'
        Log '！  ① 这台电脑连不上外网 —— 换手机热点再来一次'
        Log '！  ② 上面报错里有 Permission denied: ...\xxx.dll —— 那是安全软件删文件，'
        Log '！     先把 C:\ff 加进 360 信任区，再把 C:\ff\dev-env 这个文件夹删掉，重新双击本脚本'
        $Fail = $Fail + '库没装上'
    }
    & $VPY -m pip list 2>&1 | ForEach-Object { Raw $_ }
}

# ---------- 第 5 步：七个自检 ----------
Step '5' '跑七个自检（民警会点的路都得跑到）'
$Tests = @(
    @('agent\officer_app.py',            '--自检', '出三样产物，且没有 !! 红字'),
    @('agent\mcp_server\smoke.py',        '',       '老的一条龙'),
    @('agent\mcp_server\p1_smoke.py',     '',       '层级判定和判据表'),
    @('agent\mcp_server\p3_smoke.py',     '',       '造案子和三段式接口'),
    @('agent\mcp_server\p4_smoke.py',     '',       '账单脱敏和打包纪律'),
    @('agent\verify\report_check_selftest.py', '',  '报告检查工具自己'),
    @('agent\verify\洗钱加分行自检.py',    '',       'exe 里读不到源码时洗钱还能算')
)
if (Test-Path -LiteralPath $VPY) {
    foreach ($t in $Tests) {
        $f = Join-Path $Root $t[0]
        if (-not (Test-Path -LiteralPath $f)) { Log ('缺文件：' + $t[0]); $Fail = $Fail + $t[0]; continue }
        Log ('跑 ' + $t[0] + '　（' + $t[2] + '）')
        $out = ''
        if ($t[1]) { $out = (& $VPY -X utf8 $f $t[1] 2>&1 | Out-String) } else { $out = (& $VPY -X utf8 $f 2>&1 | Out-String) }
        $code = $LASTEXITCODE
        foreach ($ln in (($out -split "`r?`n") | Where-Object { $_.Trim() })) { Raw $ln.Trim() }
        if ($code -eq 0) { Log ('  退出码 0 → 绿') } else {
            Log ('  退出码 ' + $code + ' → 红，原文已经写进报告，把报告发回去就行')
            $Fail = $Fail + $t[0]
        }
    }
    Log '另外那条 agent\mcp_server\protocol_smoke.py 这台电脑跑不了（没装 mcp 包），从来没跑通过，不算你做得不对'
}

# ---------- 收尾 ----------
Step '6' '结论'
if ($Fail.Count -eq 0) {
    Log '★ 全绿。下一步：打开 Orca → 打开文件夹 ' + $Root + ' → 把用户给你的那段话贴给它'
} else {
    Log '★ 有事没成：' + ($Fail -join '；')
    Log '把这个文件原样发回去就行，不用你解释：' + $LogFile
}
Log ''
Log ('报告文件：' + $LogFile)
Write-Host ''
Write-Host '做完把 C:\ff\pc-setup-report.txt 发回去（或让 Orca 读给你听）'
Write-Host '按任意键关闭...'
try { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') } catch { Start-Sleep -Seconds 20 }
