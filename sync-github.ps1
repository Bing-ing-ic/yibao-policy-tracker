# 同步本地已跟踪源码到 GitHub 仓库（纯 REST Git Data API，绕过被阻断的 github.com smart HTTP）
# 用法：在项目根目录执行  pwsh -File .\sync-github.ps1  或  .\sync-github.ps1 "提交说明"
# 说明：
#   - 凭据从 Windows 凭据管理器读取（git credential fill），脚本内不保存令牌。
#   - 仅推送 .git 跟踪的文件；frontend/data、frontend/assets、*.db、*.log 已被 .gitignore 排除。
#   - 数据快照由 GitHub Actions 在定时/手动运行时抓取并回提交，本机 DB 不入库。
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$message = if ($args.Count -ge 1) { $args[0] } else { "chore: 同步本地改动到 GitHub Pages 仓库" }

# 收集本地改动（data/assets/db/log 已被忽略，不会进入跟踪）
git add -A | Out-Null

$cred = ("protocol=https`nhost=github.com`n" | git credential fill)
$token = ($cred | Where-Object { $_ -like 'password=*' }) -replace 'password=', ''
if (-not $token) { throw "未在凭据管理器找到 GitHub 令牌，请先在 Git 中完成一次 GitHub 登录。" }

$owner = "Bing-ing-ic"
$repo  = "yibao-policy-tracker"
$base  = "https://api.github.com/repos/$owner/$repo"
$h = @{ Authorization = "Bearer $token"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }

function Api($method, $path, $bodyObj) {
  $p = @{ Method = $method; Uri = "$base$path"; Headers = $h; TimeoutSec = 30 }
  if ($null -ne $bodyObj) {
    $p.Body = [Text.Encoding]::UTF8.GetBytes(($bodyObj | ConvertTo-Json -Depth 10))
    $p.ContentType = 'application/json'
  }
  return Invoke-RestMethod @p
}

$br = Api Get "/branches/main"
$commitSha = $br.commit.sha
$cur = Api Get "/git/commits/$commitSha"
$treeSha = $cur.tree.sha

$files = git ls-files
if (-not $files) { Write-Host "没有需要同步的跟踪文件。"; exit 0 }

$treeEntries = @()
foreach ($f in $files) {
  $bytes = [IO.File]::ReadAllBytes((Join-Path $root $f))
  $blob = Api Post "/git/blobs" @{ content = [Convert]::ToBase64String($bytes); encoding = 'base64' }
  $treeEntries += [ordered]@{ path = $f; mode = '100644'; type = 'blob'; sha = $blob.sha }
}

$tree = Api Post "/git/trees" @{ base_tree = $treeSha; tree = $treeEntries }
$commit = Api Post "/git/commits" @{ message = $message; tree = $tree.sha; parents = @($commitSha) }
Api Patch "/git/refs/heads/main" @{ sha = $commit.sha; force = $false } | Out-Null

Write-Host ("同步完成：{0} 个文件，commit {1}" -f $files.Count, $commit.sha.Substring(0, 7))
