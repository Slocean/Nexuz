# Windows 代码签名（Authenticode）

未签名的 `Nexuz.exe`（尤其是 PyInstaller 打包）很容易被 Windows Defender / SmartScreen 拦截或删除。  
**真正有效**的方式是购买并配置 **OV / EV 代码签名证书**；自签名只能缓解「未知发布者」，无法完全免杀。

## 推荐流程（有正式证书）

1. 向 DigiCert / Sectigo / GlobalSign 等购买 **Code Signing**（OV 即可起步，EV 对 SmartScreen 更好）
2. 导出为 `.pfx`，并设导出密码
3. 生成 base64：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("your.pfx")) | Set-Clipboard
```

4. GitHub 仓库 → **Settings → Secrets and variables → Actions** 添加：

| Secret | 值 |
|--------|-----|
| `WINDOWS_CERTIFICATE` | pfx 的 base64（一行） |
| `WINDOWS_CERTIFICATE_PASSWORD` | pfx 导出密码 |

5. 再跑 `release.bat`：Action 会在上传 Release 前自动 `signtool` 签名

## 临时自签名（开发 / 过渡）

```powershell
.\scripts\new_codesign_cert.ps1
```

按脚本提示把生成的 base64 / 密码填进上述两个 Secrets。  
自签名仍可能被 Defender 报毒，但比完全不签好一些；请尽快换成正式证书。

## 本地签名

```powershell
python package.py
.\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe -PfxPath .codesign\nexuz-codesign.pfx -Password "你的密码"
```

## 注意

- `.codesign/`、`*.pfx` 不要提交进 git
- 证书过期后需换新 Secrets 并重新发版
- 若仍被删：把 exe 提交 [Microsoft 误报申诉](https://www.microsoft.com/wdsi/filesubmission)，并积累签名后的下载信誉
